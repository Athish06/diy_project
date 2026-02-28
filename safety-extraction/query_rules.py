"""
CLI bridge for querying safety rules from the database.

Called by the Tauri Rust backend via subprocess:

    python query_rules.py [--category X] [--severity N] [--document D]
                          [--search S] [--page N] [--per_page N]
    python query_rules.py --filters       # return filter options only

Outputs JSON to stdout.
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

# Force UTF-8 stdout so Unicode characters in rules don't crash on Windows (cp1252)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Ensure the parent package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from src.db import fetch_filter_options, fetch_rules, get_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Query safety rules from DB")
    parser.add_argument("--category", default=None)
    parser.add_argument("--severity", type=int, default=None)
    parser.add_argument("--document", default=None)
    parser.add_argument("--search", default=None)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per_page", type=int, default=50)
    parser.add_argument("--filters", action="store_true",
                        help="Return filter options only (categories, severities, documents)")
    parser.add_argument("--stats", action="store_true",
                        help="Return aggregate statistics")
    args = parser.parse_args()

    if args.filters:
        result = fetch_filter_options()
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.stats:
        result = get_stats()
        print(json.dumps(result, ensure_ascii=False))
        return

    rules, total = fetch_rules(
        category=args.category,
        severity=args.severity,
        document=args.document,
        search=args.search,
        page=args.page,
        per_page=args.per_page,
    )

    result = {
        "rules": rules,
        "total": total,
        "page": args.page,
        "per_page": args.per_page,
    }
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
