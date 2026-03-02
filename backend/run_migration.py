"""
Database migration script.

Run once:  python run_migration.py
"""

import os
import re
import sys
from pathlib import Path

# Load .env from this directory
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from db.migration import MIGRATIONS


def get_connection():
    import psycopg2
    raw_url = os.getenv("SUPABASE_URL", "")
    if not raw_url:
        print("ERROR: SUPABASE_URL not set in .env")
        sys.exit(1)
    url = re.sub(r":5432/", ":6543/", raw_url)
    return psycopg2.connect(url)


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
