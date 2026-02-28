"""
Database access layer for the safety-extraction pipeline.

Connects to Supabase PostgreSQL via the session pooler (port 6543).
Environment variable required:
    DATABASE_URL — Postgres connection string.
"""

import logging
import os
import re
from typing import Any

import psycopg2
import psycopg2.extras

logger = logging.getLogger("safety_extraction.db")


def get_connection(register_vec: bool = True) -> psycopg2.extensions.connection:
    """
    Return a new psycopg2 connection.

    ``register_vec`` — if True, register the pgvector type adapter
    so that embedding columns come back as Python lists.
    Set to False when the ``vector`` extension may not yet exist.
    """
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    # Supabase session-pooler needs port 6543 (not 5432)
    url = re.sub(r":5432/", ":6543/", raw_url)

    conn = psycopg2.connect(url)

    if register_vec:
        try:
            from pgvector.psycopg2 import register_vector
            register_vector(conn)
        except Exception:
            logger.debug("pgvector adapter registration skipped (extension may not exist yet).")

    return conn


def init_schema() -> None:
    """Run schema.sql to create tables + indexes (idempotent)."""
    from pathlib import Path

    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    conn = get_connection(register_vec=False)
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
        logger.info("Schema initialised (or already exists).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read helpers (used by webapp.py and the Tauri bridge)
# ---------------------------------------------------------------------------

def fetch_rules(
    category: str | None = None,
    severity: int | None = None,
    document: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """
    Fetch rules with optional filters and pagination.

    Returns ``(rules_list, total_count)``.
    """
    conn = get_connection(register_vec=False)
    try:
        conditions: list[str] = []
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
            like = f"%{search}%"
            params.extend([like, like])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Total count
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM safety_rules{where}", params)
            total = cur.fetchone()[0]

        # Fetch page
        offset = (page - 1) * per_page
        order = " ORDER BY validated_severity DESC, id"
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, rule_id, original_text, actionable_rule, materials, "
                f"suggested_severity, validated_severity, categories, "
                f"source_document, page_number, section_heading, created_at "
                f"FROM safety_rules{where}{order} LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            rows = cur.fetchall()

        rules = []
        for row in rows:
            r = dict(row)
            # Convert datetime to ISO string
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            # rule_id is already UUID-as-text from the driver
            if r.get("rule_id"):
                r["rule_id"] = str(r["rule_id"])
            rules.append(r)

        return rules, total
    finally:
        conn.close()


def fetch_filter_options() -> dict[str, list]:
    """Return distinct categories, severities, and documents for filter dropdowns."""
    conn = get_connection(register_vec=False)
    try:
        with conn.cursor() as cur:
            # Categories (unnest the array column)
            cur.execute(
                "SELECT DISTINCT unnest(categories) AS cat "
                "FROM safety_rules ORDER BY cat"
            )
            categories = [r[0] for r in cur.fetchall()]

            # Severities
            cur.execute(
                "SELECT DISTINCT validated_severity FROM safety_rules "
                "WHERE validated_severity IS NOT NULL ORDER BY validated_severity DESC"
            )
            severities = [r[0] for r in cur.fetchall()]

            # Documents
            cur.execute(
                "SELECT DISTINCT source_document FROM safety_rules "
                "ORDER BY source_document"
            )
            documents = [r[0] for r in cur.fetchall()]

        return {
            "categories": categories,
            "severities": severities,
            "documents": documents,
        }
    finally:
        conn.close()


def get_stats() -> dict[str, Any]:
    """Aggregate stats for the dashboard."""
    conn = get_connection(register_vec=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM safety_rules")
            total_rules = cur.fetchone()[0]

            cur.execute(
                "SELECT source_document, COUNT(*) AS cnt "
                "FROM safety_rules GROUP BY source_document ORDER BY cnt DESC"
            )
            by_document = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute(
                "SELECT unnest(categories) AS cat, COUNT(*) AS cnt "
                "FROM safety_rules GROUP BY cat ORDER BY cnt DESC"
            )
            by_category = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute(
                "SELECT validated_severity, COUNT(*) AS cnt "
                "FROM safety_rules WHERE validated_severity IS NOT NULL "
                "GROUP BY validated_severity ORDER BY validated_severity DESC"
            )
            by_severity = [{"severity": r[0], "count": r[1]} for r in cur.fetchall()]

        return {
            "total_rules": total_rules,
            "by_document": by_document,
            "by_category": by_category,
            "by_severity": by_severity,
        }
    finally:
        conn.close()
