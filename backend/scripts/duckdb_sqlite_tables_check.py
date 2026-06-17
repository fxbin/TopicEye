#!/usr/bin/env python3
"""Check DuckDB sqlite_scanner table listing and verify key tables."""

import duckdb
import os

conn = duckdb.connect(":memory:")
conn.execute("INSTALL sqlite; LOAD sqlite;")

db_path = os.path.abspath("./topiceye.db")
conn.execute(f"ATTACH '{db_path}' AS oltp_db (TYPE SQLITE, READ_ONLY)")

# List tables via information_schema
try:
    tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='oltp_db'").fetchall()
    print(f"Tables via information_schema: {[t[0] for t in tables]}")
except Exception as e:
    print(f"information_schema failed: {e}")

# Check individual tables
for t in ["content_items", "ai_analyses", "sources", "topic_groups", "topic_trends"]:
    try:
        cnt = conn.execute(f"SELECT COUNT(*) FROM oltp_db.{t}").fetchone()
        print(f"  {t}: {cnt[0]} rows")
    except Exception as e:
        print(f"  {t}: ERROR - {e}")

# Test the today_picks analytical query
print("\n--- Testing today_picks analytical query ---")
try:
    results = conn.execute("""
        SELECT
            c.id, c.title, c.url, c.source_name,
            a.curation_score, a.creator_score, a.viral_score, a.risk_score,
            COALESCE(s.weight, 3) AS source_weight,
            CASE
                WHEN a.curation_score > 0 THEN a.curation_score + (COALESCE(s.weight, 3) - 3) * 8
                ELSE (COALESCE(a.creator_score, 0) + COALESCE(a.viral_score, 0)) / 2.0 + (COALESCE(s.weight, 3) - 3) * 8
            END AS adjusted_curation_score
        FROM oltp_db.content_items c
        LEFT JOIN oltp_db.ai_analyses a ON a.content_id = c.id
        LEFT JOIN oltp_db.sources s ON s.id = c.source_id
        WHERE a.curation_score IS NOT NULL
          AND a.risk_score <= 70
          AND c.duplicate_of IS NULL
          AND c.crawled_at >= CURRENT_TIMESTAMP - INTERVAL '48 hours'
        ORDER BY adjusted_curation_score DESC
        LIMIT 5
    """).fetchall()
    print(f"today_picks query returned {len(results)} items")
    for r in results:
        print(f"  [{r[0]}] {r[1][:50]}... curation={r[4]} adjusted={r[9]:.1f}")
except Exception as e:
    print(f"today_picks query failed: {e}")

conn.close()
print("\nDone!")
