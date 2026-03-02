"""Database connection helper for Supabase PostgreSQL."""

import os
import re

import psycopg2


def get_db_connection():
    """Get a psycopg2 connection using DATABASE_URL or SUPABASE_URL.

    Supabase session-pooler requires port 6543 instead of 5432.
    """
    raw_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL or SUPABASE_URL not set")
    url = re.sub(r":5432/", ":6543/", raw_url)
    return psycopg2.connect(url)
