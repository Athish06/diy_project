

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.embeddings import EmbeddingProcessor
from src.exceptions import ExtractionError
from src.ingestion import ingest_pdf
from src.llm import GroqExtractor
from src.severity import override_severity
from src.validator import RuleValidator

logger = logging.getLogger("safety_extraction")


class SafetyRuleExtractionService:
   
    def __init__(
        self,
        groq_api_key: str | None = None,
        model_name: str = "qwen/qwen3-32b",
        embedding_model: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.9,
        max_retries: int = 3,
    ) -> None:
        api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY must be provided or set as environment variable."
            )

        self._extractor = GroqExtractor(
            api_key=api_key,
            model_name=model_name,
            max_retries=max_retries,
        )
        self._validator = RuleValidator()
        self._embedder = EmbeddingProcessor(
            model_name=embedding_model,
            similarity_threshold=similarity_threshold,
        )
        self._model_name = model_name

        logger.info(
            "Service initialised — llm=%s, embedder=%s, sim_threshold=%.2f",
            model_name, embedding_model, similarity_threshold,
        )

    def _extract_and_validate(self, file_path: str | Path) -> list[dict[str, Any]]:
        
        file_path = Path(file_path)
        document_name = file_path.stem

        logger.info("=" * 60)
        logger.info("Processing document: %s", file_path.name)
        logger.info("=" * 60)

        # 1. Ingest
        pages = ingest_pdf(file_path)
        if not pages:
            logger.warning("No extractable pages found in %s", file_path.name)
            return []

        # 2. Extract rules per page
        all_rules: list[dict[str, Any]] = []
        extraction_errors: list[str] = []

        for page_data in pages:
            try:
                page_rules = self._extractor.extract_rules(
                    text=page_data["text"],
                    document_name=document_name,
                    page_number=page_data["page_number"],
                    section_heading=page_data["section_heading"],
                )
                all_rules.extend(page_rules)
            except ExtractionError as exc:
                logger.error("Extraction failed: %s", exc)
                extraction_errors.append(str(exc))
                continue

        logger.info(
            "Raw extraction: %d rules from %d pages (%d errors).",
            len(all_rules), len(pages), len(extraction_errors),
        )

        if not all_rules:
            logger.warning("No rules extracted from %s", file_path.name)
            return []

        # 3. Validate and normalise
        all_rules = self._validator.validate_and_normalize(all_rules)

        # 4. Severity overrides
        all_rules = override_severity(all_rules)

        logger.info(
            "Pre-dedup rules for '%s': %d", file_path.name, len(all_rules),
        )
        return all_rules

    def process_document(self, file_path: str | Path) -> list[dict[str, Any]]:
        """
        Full pipeline for a single PDF.

        For multi-document processing with cross-document dedup,
        use ``process_batch()`` instead.
        """
        all_rules = self._extract_and_validate(file_path)
        if not all_rules:
            return []

        # Embeddings + dedup + IDs
        all_rules = self._embedder.generate_embeddings(all_rules)
        all_rules = self._embedder.deduplicate_rules(all_rules)
        for rule in all_rules:
            rule["rule_id"] = str(uuid.uuid4())

        logger.info(
            "Pipeline complete for '%s': %d final rules.",
            Path(file_path).name, len(all_rules),
        )
        return all_rules

    def process_batch(
        self, file_paths: list[str | Path],
    ) -> list[dict[str, Any]]:
        """
        Flow per PDF:  ingest → extract → validate → severity override
        Then globally:  embed all rules once → deduplicate across full set → assign IDs

        This ensures that if two different PDFs contain the same rule
        (e.g. "Wear safety goggles"), only one copy survives.
        """
        combined_rules: list[dict[str, Any]] = []
        doc_stats: list[dict[str, Any]] = []

        for file_path in file_paths:
            file_path = Path(file_path)
            try:
                rules = self._extract_and_validate(file_path)
                doc_stats.append({
                    "document": file_path.name,
                    "rules_before_dedup": len(rules),
                })
                combined_rules.extend(rules)
            except Exception as exc:
                logger.error(
                    "Failed to process %s: %s", file_path.name, exc,
                    exc_info=True,
                )
                doc_stats.append({
                    "document": file_path.name,
                    "rules_before_dedup": 0,
                    "error": str(exc),
                })

        logger.info("=" * 60)
        logger.info("BATCH SUMMARY — %d documents, %d total rules before dedup",
                     len(file_paths), len(combined_rules))
        logger.info("=" * 60)

        if not combined_rules:
            logger.warning("No rules extracted from any document.")
            return []

        # Global: embed once across all rules
        combined_rules = self._embedder.generate_embeddings(combined_rules)

        # Global: deduplicate across ALL documents
        combined_rules = self._embedder.deduplicate_rules(combined_rules)

        # Assign rule IDs
        for rule in combined_rules:
            rule["rule_id"] = str(uuid.uuid4())

        # Per-document stats after dedup
        for stat in doc_stats:
            doc_name = stat["document"].rsplit(".", 1)[0]
            surviving = sum(
                1 for r in combined_rules
                if r.get("source_document") == doc_name
            )
            stat["rules_after_dedup"] = surviving

        logger.info(
            "Batch complete: %d final deduplicated rules across %d documents.",
            len(combined_rules), len(file_paths),
        )
        for stat in doc_stats:
            logger.info(
                "  %-40s %d extracted → %d after global dedup%s",
                stat["document"],
                stat.get("rules_before_dedup", 0),
                stat.get("rules_after_dedup", 0),
                f"  [ERROR: {stat['error']}]" if "error" in stat else "",
            )

        return combined_rules



    def save_results(
        self,
        rules: list[dict[str, Any]],
        output_path: str | Path,
        document_name: str = "",
        total_pages: int = 0,
        source_documents: list[str] | None = None,
    ) -> Path:
        """
        Write results to JSON with metadata envelope.

        For batch processing, pass ``source_documents`` (list of PDF names)
        to record all contributing files.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        envelope: dict[str, Any] = {
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "model_used": self._model_name,
            "total_pages": total_pages,
            "rule_count": len(rules),
        }

        if source_documents and len(source_documents) > 1:
            # Batch mode — multiple source documents
            envelope["document_name"] = "batch"
            envelope["source_documents"] = source_documents
            envelope["document_count"] = len(source_documents)
        else:
            envelope["document_name"] = document_name

        envelope["rules"] = rules

        def _default(obj: Any) -> Any:
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, uuid.UUID):
                return str(obj)
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=_default, ensure_ascii=False)

        logger.info("Results saved to: %s", output_path)
        return output_path
