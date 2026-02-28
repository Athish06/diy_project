
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["USE_TF"] = "0"          # prevent transformers from importing broken TF

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.service import SafetyRuleExtractionService

LOG_DIR = Path(__file__).resolve().parent.parent  # safety-extraction/
LOG_FILE = LOG_DIR / "extraction.log"

logger = logging.getLogger("safety_extraction")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)




def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Safety Rule Extraction Service — "
        "extract actionable safety rules from PDF documents via Groq.",
    )
    parser.add_argument(
        "input",
        help="Path to a PDF file or a directory containing PDFs.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output JSON file path. Default: output/<doc>_<timestamp>.json",
    )
    parser.add_argument(
        "--model",
        default="qwen/qwen3-32b",
        help="Groq model name (default: qwen/qwen3-32b).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.9,
        help="Cosine similarity threshold for dedup (default: 0.9).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)

    # Collect PDF files
    if input_path.is_dir():
        pdf_files = sorted(input_path.glob("*.pdf"))
        if not pdf_files:
            logger.error("No PDF files found in %s", input_path)
            sys.exit(1)
        logger.info("Found %d PDF files in %s", len(pdf_files), input_path)
    elif input_path.is_file():
        pdf_files = [input_path]
    else:
        logger.error("Input path does not exist: %s", input_path)
        sys.exit(1)

    # Initialise service
    service = SafetyRuleExtractionService(
        model_name=args.model,
        similarity_threshold=args.threshold,
    )

    if len(pdf_files) == 1:
        # Single document mode — per-doc dedup only
        pdf_path = pdf_files[0]
        try:
            rules = service.process_document(pdf_path)

            if not rules:
                logger.warning("No rules extracted from %s", pdf_path.name)
                sys.exit(0)

            out_path = Path(args.output) if args.output else (
                LOG_DIR / "output" / f"{pdf_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

            total_pages = max(
                (r.get("page_number", 0) for r in rules), default=0
            )

            service.save_results(
                rules=rules,
                output_path=out_path,
                document_name=pdf_path.stem,
                total_pages=total_pages,
            )

            print(f"\n{'=' * 50}")
            print(f"Document:    {pdf_path.name}")
            print(f"Rules:       {len(rules)}")
            print(f"Output:      {out_path}")
            print(f"{'=' * 50}\n")

        except Exception as exc:
            logger.error(
                "Failed to process %s: %s", pdf_path.name, exc, exc_info=True,
            )
            sys.exit(1)

    else:
        # Batch mode — cross-document global deduplication
        logger.info(
            "Batch mode: %d PDFs — rules will be deduplicated across ALL documents.",
            len(pdf_files),
        )

        rules = service.process_batch(pdf_files)

        if not rules:
            logger.warning("No rules extracted from any document.")
            sys.exit(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(args.output) if args.output else (
            LOG_DIR / "output" / f"batch_{len(pdf_files)}_docs_{timestamp}.json"
        )

        # Total pages across all docs
        total_pages = max(
            (r.get("page_number", 0) for r in rules), default=0
        )

        source_documents = [p.stem for p in pdf_files]

        service.save_results(
            rules=rules,
            output_path=out_path,
            document_name="batch",
            total_pages=total_pages,
            source_documents=source_documents,
        )

        # Per-document breakdown
        doc_counts: dict[str, int] = {}
        for rule in rules:
            src = rule.get("source_document", "unknown")
            doc_counts[src] = doc_counts.get(src, 0) + 1

        print(f"\n{'=' * 60}")
        print(f"BATCH RESULTS — {len(pdf_files)} documents processed")
        print(f"{'=' * 60}")
        print(f"Total deduplicated rules:  {len(rules)}")
        print(f"Output:                    {out_path}")
        print(f"\nPer-document breakdown:")
        for doc_name, count in sorted(doc_counts.items()):
            print(f"  {doc_name:<40} {count} rules")
        print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
