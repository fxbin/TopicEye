#!/usr/bin/env python3
"""Verify DuckDB analytics layer works correctly."""

import sys

sys.path.insert(0, ".")

from app.services.duckdb_service import (
    DuckDBAnalytics,
    get_analytics,
    query_today_picks,
    query_topics,
    query_trend_topics,
    query_keyword_cloud,
    query_content_for_report,
)

print("All imports OK")

# Test DuckDBAnalytics initialization
analytics = DuckDBAnalytics()
print(f"Available: {analytics.available}")

# Test query_today_picks
picks = analytics.query_today_picks(hours=48)
print(f"today_picks: {len(picks)} items")
if picks:
    print(f"  First: [{picks[0]['id']}] {picks[0]['title'][:60]}... adjusted={picks[0]['adjusted_curation_score']}")

# Test query_topics
topics = analytics.query_topics()
print(f"topics: {len(topics)} groups")

# Test query_trend_topics
trends = analytics.query_trend_topics(days=7)
print(f"trend_topics: {len(trends)} rows")

# Test query_keyword_cloud
kw = analytics.query_keyword_cloud(days=7)
print(f"keywords: {len(kw)} entries")

# Test query_content_for_report
report_data = analytics.query_content_for_report(hours=48)
print(f"report_data: {len(report_data)} items")

# Test backward-compatible function API
picks2 = query_today_picks(hours=48)
print(f"backward-compat query_today_picks: {len(picks2)} items")

analytics.close()
print("\nAll queries passed!")
