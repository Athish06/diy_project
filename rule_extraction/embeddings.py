"""
embeddings.py — Embedding generation and cosine-similarity deduplication
for the rule extraction pipeline.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim).
This module is used standalone by extract_rules.py during the extraction phase.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("safety_extraction")


class EmbeddingProcessor:
    """Generate 384-dim embeddings and deduplicate rules by cosine similarity."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.9,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", model_name)
        self._embedder = SentenceTransformer(model_name)
        self._similarity_threshold = similarity_threshold

    def generate_embeddings(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Encode each rule's actionable_rule into a 384-dim vector."""
        if not rules:
            return rules

        texts = [r.get("actionable_rule", "") for r in rules]
        embeddings = self._embedder.encode(texts, show_progress_bar=False)

        for rule, emb in zip(rules, embeddings):
            rule["embedding"] = emb.tolist() if hasattr(emb, "tolist") else list(emb)

        logger.info("Generated embeddings for %d rules.", len(rules))
        return rules

    def deduplicate_rules(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove near-duplicate rules using cosine similarity."""
        if len(rules) <= 1:
            return rules

        emb_list: list[np.ndarray] = []
        for rule in rules:
            emb = rule.get("embedding")
            if emb is None:
                raise ValueError(
                    "Rule missing 'embedding'. "
                    "Call generate_embeddings() before deduplicate_rules()."
                )
            emb_list.append(np.array(emb, dtype=np.float32))

        emb_matrix = np.stack(emb_list)
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1e-10, norms)
        normed = emb_matrix / norms
        sim_matrix = normed @ normed.T

        keep_mask = [True] * len(rules)
        duplicate_count = 0

        for i in range(len(rules)):
            if not keep_mask[i]:
                continue
            for j in range(i + 1, len(rules)):
                if not keep_mask[j]:
                    continue
                sim = float(sim_matrix[i, j])
                if sim > self._similarity_threshold:
                    keep_mask[j] = False
                    duplicate_count += 1
                    logger.info(
                        "Duplicate removed (sim=%.3f): '%s' ≈ '%s'",
                        sim,
                        rules[i].get("actionable_rule", "")[:60],
                        rules[j].get("actionable_rule", "")[:60],
                    )

        deduped = [r for r, keep in zip(rules, keep_mask) if keep]
        logger.info(
            "Deduplication: %d rules → %d rules (%d duplicates removed).",
            len(rules), len(deduped), duplicate_count,
        )
        return deduped
