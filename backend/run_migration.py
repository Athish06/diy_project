"""
Database migration script — adds run_id to safety_rules,
evaluation_results + file_url to extraction_runs.

Run once:  python run_migration.py
"""

import os
import re
import sys
from pathlib import Path

# Load .env from this directory
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")


def get_connection():
    import psycopg2
    raw_url = os.getenv("SUPABASE_URL", "")
    if not raw_url:
        print("ERROR: SUPABASE_URL not set in .env")
        sys.exit(1)
    url = re.sub(r":5432/", ":6543/", raw_url)
    return psycopg2.connect(url)


MIGRATIONS = [
    # 1. Add run_id column to safety_rules
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'safety_rules' AND column_name = 'run_id'
        ) THEN
            ALTER TABLE safety_rules ADD COLUMN run_id INTEGER REFERENCES extraction_runs(id);
        END IF;
    END $$;
    """,
    # 2. Set existing rules to run_id = 1
    """
    UPDATE safety_rules SET run_id = 1 WHERE run_id IS NULL;
    """,
    # 3. Create index on run_id
    """
    CREATE INDEX IF NOT EXISTS idx_rules_run_id ON safety_rules (run_id);
    """,
    # 4. Add evaluation_results JSONB column to extraction_runs
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'extraction_runs' AND column_name = 'evaluation_results'
        ) THEN
            ALTER TABLE extraction_runs ADD COLUMN evaluation_results JSONB;
        END IF;
    END $$;
    """,
    # 5. Add file_url column to extraction_runs
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'extraction_runs' AND column_name = 'file_url'
        ) THEN
            ALTER TABLE extraction_runs ADD COLUMN file_url TEXT;
        END IF;
    END $$;
    """,
]


def main():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for i, sql in enumerate(MIGRATIONS, 1):
                print(f"Running migration {i}/{len(MIGRATIONS)}...")
                cur.execute(sql)
        conn.commit()
        print("All migrations completed successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
