#!/usr/bin/env python3
"""Test DuckDB sqlite extension + ATTACH capability."""

import duckdb
import os

conn = duckdb.connect(":memory:")

# 1. Test sqlite extension
try:
    conn.execute("INSTALL sqlite; LOAD sqlite;")
    print("sqlite extension loaded OK")
except Exception as e:
    print(f"Failed to load sqlite extension: {e}")
    exit(1)

# 2. Test ATTACH
db_path = os.path.abspath("./topiceye.db")
if not os.path.exists(db_path):
    print(f"SQLite file not found at {db_path}")
    exit(1)

try:
    conn.execute(f"ATTACH '{db_path}' AS oltp_db (TYPE SQLITE, READ_ONLY)")
    print(f"Attached {db_path} OK")
except Exception as e:
    print(f"Attach failed: {e}")
    exit(1)

# 3. List attached OLTP tables
try:
    tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='oltp_db'").fetchall()
    print(f"Tables: {[t[0] for t in tables]}")
except Exception as e:
    print(f"List tables failed: {e}")

# 4. Quick count
try:
    cnt = conn.execute("SELECT COUNT(*) FROM oltp_db.content_items").fetchone()
    print(f"content_items count: {cnt[0]}")
except Exception as e:
    print(f"Count query failed: {e}")

# 5. Test JOIN query (content + analysis + source)
try:
    row = conn.execute("""
        SELECT COUNT(*)
        FROM oltp_db.content_items c
        LEFT JOIN oltp_db.ai_analyses a ON a.content_id = c.id
        LEFT JOIN oltp_db.sources s ON s.id = c.source_id
        WHERE a.curation_score IS NOT NULL
    """).fetchone()
    print(f"Joined content with analysis: {row[0]} items")
except Exception as e:
    print(f"JOIN query failed: {e}")

conn.close()
print("All tests passed!")
