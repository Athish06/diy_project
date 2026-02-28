"""
Migrate extraction JSON output into PostgreSQL + pgvector (Supabase).

Usage:
    python -m src.migrate output/batch_23_docs_20260228_184812.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import psycopg2.extras

from src.db import get_connection, init_schema

logger = logging.getLogger("safety_extraction.migrate")


def _load_json(path: Path) -> tuple[dict, list[dict]]:
    """Load the extraction JSON and return (metadata, rules)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list):
        return {}, data

    rules = data.pop("rules", [])
    return data, rules


def _insert_run_metadata(
    conn: psycopg2.extensions.connection, meta: dict, json_file: str,
) -> int | None:
    """Insert a row into extraction_runs and return the id."""
    if not meta:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extraction_runs
                (run_timestamp, model_used, total_pages, rule_count,
                 document_count, source_documents, json_source_file)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                meta.get("extraction_timestamp"),
                meta.get("model_used"),
                meta.get("total_pages", 0),
                meta.get("rule_count", 0),
                meta.get("document_count", 1),
                meta.get("source_documents", []),
                json_file,
            ),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
        logger.info("Extraction run recorded — id=%d", run_id)
        return run_id


def _insert_rules(
    conn: psycopg2.extensions.connection, rules: list[dict],
) -> int:
    """Batch-insert rules using execute_values for speed."""
    if not rules:
        return 0

    insert_sql = """
        INSERT INTO safety_rules
            (rule_id, original_text, actionable_rule, materials,
             suggested_severity, validated_severity, categories,
             source_document, page_number, section_heading, embedding)
        VALUES %s
        ON CONFLICT (rule_id) DO NOTHING
    """

    rows = []
    for r in rules:
        # Convert embedding to pgvector-compatible list
        emb = r.get("embedding")
        if emb is not None:
            if isinstance(emb, np.ndarray):
                emb = emb.tolist()
            # pgvector expects a string like '[0.1,0.2,...]'
            emb_str = "[" + ",".join(str(float(v)) for v in emb) + "]"
        else:
            emb_str = None

        rows.append((
            r.get("rule_id"),
            r.get("original_text", ""),
            r.get("actionable_rule", ""),
            r.get("materials", []),
            r.get("suggested_severity"),
            r.get("validated_severity"),
            r.get("categories", []),
            r.get("source_document", ""),
            r.get("page_number"),
            r.get("section_heading", "Unknown Section"),
            emb_str,
        ))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, insert_sql, rows, page_size=100,
        )
    conn.commit()

    inserted = len(rows)
    logger.info("Inserted %d rules into safety_rules table.", inserted)
    return inserted


def migrate(json_path: Path) -> None:
    """Full migration: init schema → insert metadata → insert rules."""
    logger.info("Starting migration from %s", json_path.name)

    # 1. Init schema (idempotent — IF NOT EXISTS)
    init_schema()

    # 2. Load JSON
    meta, rules = _load_json(json_path)
    logger.info(
        "Loaded %d rules | model=%s | documents=%s",
        len(rules),
        meta.get("model_used", "?"),
        meta.get("document_count", "?"),
    )

    # 3. Connect and insert
    conn = get_connection()
    try:
        _insert_run_metadata(conn, meta, json_path.name)
        inserted = _insert_rules(conn, rules)
        logger.info("Migration complete — %d rules in database.", inserted)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate extraction JSON into PostgreSQL + pgvector.",
    )
    parser.add_argument(
        "json_file",
        help="Path to the extraction JSON output file.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    json_path = Path(args.json_file)
    if not json_path.exists():
        logger.error("File not found: %s", json_path)
        sys.exit(1)

    migrate(json_path)


if __name__ == "__main__":
    main()
