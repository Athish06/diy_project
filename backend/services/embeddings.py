"""
Embedding generation and pgvector cosine-similarity search.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim) — same model
as the safety-extraction pipeline that populated the safety_rules table.

Singleton pattern: the model is loaded once and reused.
"""

import logging
import os
import re
from typing import Any

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("diy.embeddings")

# Top-K rules to retrieve per step.
# 10 gives a good balance: enough coverage for safety, small enough for the LLM context.
DEFAULT_TOP_K = 10
DEFAULT_SIMILARITY_THRESHOLD = 0.30


class EmbeddingService:
    """Generate 384-dim embeddings and query pgvector for matching rules."""

    _instance: "EmbeddingService | None" = None

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", model_name)
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        logger.info("Embedding model loaded.")

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts into 384-dim vectors."""
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return [emb.tolist() if hasattr(emb, "tolist") else list(emb) for emb in embeddings]

    def embed_text(self, text: str) -> list[float]:
        """Encode a single text string."""
        return self.embed_texts([text])[0]

    # ------------------------------------------------------------------
    # Step embedding (combines action_summary + step_text + excerpt)
    # ------------------------------------------------------------------

    def embed_steps(self, steps: list[dict[str, Any]]) -> list[list[float]]:
        """
        Generate embeddings for a list of DIY steps.

        For each step, combine action_summary + step_text + transcript_excerpt
        to create a rich semantic representation.
        """
        texts = []
        for step in steps:
            parts = [
                step.get("action_summary", ""),
                step.get("step_text", ""),
            ]
            excerpt = step.get("transcript_excerpt", "")
            if excerpt:
                parts.append(excerpt)
            texts.append(" ".join(p for p in parts if p))

        if not texts:
            return []

        return self.embed_texts(texts)

    # ------------------------------------------------------------------
    # pgvector search
    # ------------------------------------------------------------------

    def _get_db_url(self) -> str:
        """Resolve the Supabase PostgreSQL connection URL."""
        url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
        if not url:
            raise RuntimeError(
                "DATABASE_URL or SUPABASE_URL environment variable is not set."
            )
        # Supabase session-pooler requires port 6543 instead of 5432
        return re.sub(r":5432/", ":6543/", url)

    def find_matching_rules(
        self,
        step_embedding: list[float],
        categories: list[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> list[dict[str, Any]]:
        """
        Query pgvector for rules most similar to the step embedding.

        Uses the IVFFlat index with cosine distance operator (<=>).
        Optionally filters by safety categories for precision.
        """
        db_url = self._get_db_url()
        conn = psycopg2.connect(db_url)
        try:
            vec_str = "[" + ",".join(str(float(x)) for x in step_embedding) + "]"

            query = """
                SELECT
                    rule_id, actionable_rule, original_text, materials,
                    validated_severity, categories, source_document,
                    page_number, section_heading,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM safety_rules
                WHERE embedding IS NOT NULL
            """
            params: list[Any] = [vec_str]

            if categories:
                query += " AND categories && %s::text[]"
                params.append(categories)

            query += """
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            params.extend([vec_str, top_k])

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            results = []
            for row in rows:
                r = dict(row)
                sim = float(r.get("similarity", 0))
                if sim >= threshold:
                    r["similarity"] = round(sim, 4)
                    if r.get("rule_id"):
                        r["rule_id"] = str(r["rule_id"])
                    results.append(r)

            logger.info(
                "pgvector search: %d candidates above %.2f threshold (from %d returned)",
                len(results), threshold, len(rows),
            )
            return results

        finally:
            conn.close()

    def find_rules_for_step(
        self,
        step: dict[str, Any],
        step_embedding: list[float],
        safety_categories: list[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        """
        Full rule-matching pipeline for one step:
        1. Category-filtered search for precision
        2. Fallback to unfiltered if too few results
        3. Merge and deduplicate
        """
        candidates = []

        # First try: filter by video's safety categories
        if safety_categories:
            candidates = self.find_matching_rules(
                step_embedding, categories=safety_categories, top_k=top_k
            )

        # Fallback: unfiltered search if too few category-filtered results
        if len(candidates) < 3:
            all_candidates = self.find_matching_rules(
                step_embedding, categories=None, top_k=top_k
            )
            seen_ids = {c["rule_id"] for c in candidates}
            for c in all_candidates:
                if c["rule_id"] not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c["rule_id"])

        return candidates
