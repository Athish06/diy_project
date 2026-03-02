"""Database read queries for safety rules, extraction runs, and filter options."""

import json
from typing import Any

import psycopg2.extras

from db.connection import get_db_connection


def fetch_rules_from_db(
    category: str | None = None,
    severity: int | None = None,
    document: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Fetch existing rules with optional filters and pagination."""
    conn = get_db_connection()
    try:
        conditions = []
        params: list[Any] = []

        if category:
            conditions.append("%s = ANY(categories)")
            params.append(category)
        if severity is not None:
            conditions.append("validated_severity = %s")
            params.append(severity)
        if document:
            conditions.append("source_document = %s")
            params.append(document)
        if search:
            conditions.append("(actionable_rule ILIKE %s OR original_text ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM safety_rules{where_clause}", params)
            total = cur.fetchone()[0]

        offset = (page - 1) * per_page
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, rule_id, original_text, actionable_rule, materials,
                       suggested_severity, validated_severity, categories,
                       source_document, page_number, section_heading, run_id, created_at
                FROM safety_rules{where_clause}
                ORDER BY validated_severity DESC, id
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            rows = cur.fetchall()

        rules = []
        for row in rows:
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("rule_id"):
                r["rule_id"] = str(r["rule_id"])
            rules.append(r)

        return {"rules": rules, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


def fetch_filter_options_from_db() -> dict:
    """Fetch distinct filter values (categories, severities, documents)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT unnest(categories) AS cat FROM safety_rules ORDER BY cat"
            )
            categories = [row[0] for row in cur.fetchall()]

            cur.execute(
                "SELECT DISTINCT validated_severity FROM safety_rules "
                "WHERE validated_severity IS NOT NULL ORDER BY validated_severity DESC"
            )
            severities = [row[0] for row in cur.fetchall()]

            cur.execute(
                "SELECT DISTINCT source_document FROM safety_rules ORDER BY source_document"
            )
            documents = [row[0] for row in cur.fetchall()]

        return {"categories": categories, "severities": severities, "documents": documents}
    finally:
        conn.close()


def fetch_rules_by_document() -> dict:
    """Get rules grouped by source_document for card view."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    source_document AS name,
                    COUNT(*) AS rule_count,
                    ARRAY_AGG(DISTINCT unnest_cat) AS categories,
                    ROUND(AVG(validated_severity)::numeric, 1) AS avg_severity,
                    MAX(created_at) AS last_updated
                FROM safety_rules,
                     LATERAL unnest(categories) AS unnest_cat
                GROUP BY source_document
                ORDER BY source_document
            """)
            rows = cur.fetchall()

        documents = []
        for row in rows:
            r = dict(row)
            if r.get("last_updated"):
                r["last_updated"] = r["last_updated"].isoformat()
            if r.get("avg_severity"):
                r["avg_severity"] = float(r["avg_severity"])
            documents.append(r)

        return {"documents": documents}
    finally:
        conn.close()


def fetch_extraction_runs() -> dict:
    """Get all extraction runs with evaluation results."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, run_timestamp, model_used, total_pages, rule_count,
                       document_count, source_documents, json_source_file,
                       file_url, evaluation_results, created_at
                FROM extraction_runs
                ORDER BY id DESC
            """)
            rows = cur.fetchall()

        runs = []
        for row in rows:
            r = dict(row)
            if r.get("run_timestamp"):
                r["run_timestamp"] = r["run_timestamp"].isoformat()
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("evaluation_results") and isinstance(r["evaluation_results"], str):
                r["evaluation_results"] = json.loads(r["evaluation_results"])
            runs.append(r)

        return {"runs": runs}
    finally:
        conn.close()


def fetch_rules_by_run(run_id: int, page: int = 1, per_page: int = 50) -> dict:
    """Fetch rules filtered by run_id."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM safety_rules WHERE run_id = %s", (run_id,))
            total = cur.fetchone()[0]

        offset = (page - 1) * per_page
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, rule_id, original_text, actionable_rule, materials,
                       suggested_severity, validated_severity, categories,
                       source_document, page_number, section_heading, run_id, created_at
                FROM safety_rules
                WHERE run_id = %s
                ORDER BY validated_severity DESC, id
                LIMIT %s OFFSET %s
                """,
                (run_id, per_page, offset),
            )
            rows = cur.fetchall()

        rules = []
        for row in rows:
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("rule_id"):
                r["rule_id"] = str(r["rule_id"])
            rules.append(r)

        return {"rules": rules, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()
