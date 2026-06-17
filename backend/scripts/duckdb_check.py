#!/usr/bin/env python
"""
Manual DuckDB integration check.

NOT a pytest test — requires DuckDB + sqlite extension installed.
Run manually:
    python scripts/duckdb_check.py
"""

import sys
import os

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

from app.services.duckdb_service import (
    DuckDBAnalytics,
    query_today_picks,
    query_topics,
    query_daily_stats,
)


def main():
    analytics = DuckDBAnalytics()

    print("=== DuckDB availability check ===")
    available = analytics.available
    if not available:
        print("DuckDB not available (duckdb package or sqlite extension missing)")
        print("This is OK — the app falls back to SQLAlchemy queries.")
        return

    print("OK — DuckDB analytics layer is available\n")

    print("=== query_today_picks ===")
    picks = query_today_picks()
    print(f"Picks: {len(picks)} items")
    if picks:
        print("First pick:", picks[0]["title"], "| adj_score:", picks[0].get("adjusted_curation_score"))

    print("\n=== query_topics ===")
    topics = query_topics()
    print(f"Topics: {len(topics)}")

    print("\n=== query_daily_stats ===")
    stats = query_daily_stats()
    print("Stats:", stats)

    print("\nALL OK")


if __name__ == "__main__":
    main()
