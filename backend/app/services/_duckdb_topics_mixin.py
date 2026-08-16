"""
DuckDB analytics mixin — extracted from duckdb_service.py.
Part of the DuckDBAnalytics class split.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any


class TopicsMixin:
    def query_topics(self) -> list[dict[str, Any]]:
        """Get all topic groups ordered by best_score."""
        conn = self._get_conn()
        results = conn.execute("""
            SELECT id, name, summary, keywords, best_score, content_count
            FROM oltp_db.topic_groups
            ORDER BY best_score DESC
        """).fetchall()

        return [
            {
                "id": row[0],
                "name": row[1],
                "summary": row[2],
                "keywords": row[3],
                "best_score": float(row[4]) if row[4] else 0.0,
                "content_count": row[5] or 0,
            }
            for row in results
        ]

    def query_trend_topics(self, days: int = 7) -> list[dict[str, Any]]:
        """Get topic trend data for the last N days."""
        conn = self._get_conn()
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        results = conn.execute(f"""
            SELECT id, snapshot_date, topic_id, topic_name, content_count,
                   avg_score, max_score, pick_count, top_items,
                   provenance_status, calculation_version, created_at
            FROM oltp_db.topic_trends
            WHERE topic_id IS NOT NULL
              AND snapshot_date >= '{cutoff}'
            ORDER BY snapshot_date, topic_id
        """).fetchall()

        return [
            {
                "date": str(row[1]) if hasattr(row[1], "isoformat") else str(row[1]),
                "snapshot_id": row[0],
                "topic_id": row[2],
                "topic_name": row[3],
                "content_count": row[4],
                "avg_score": float(row[5]) if row[5] else 0.0,
                "max_score": float(row[6]) if row[6] else 0.0,
                "pick_count": row[7] or 0,
                # topic_trends.top_items is a JSON string column in SQLite.
                # The DuckDB ATTACH view returns the raw text, so we parse
                # it here to honour the contract ``top_items: list[dict]``.
                # If the stored value is corrupt or missing, fall back to [].
                "top_items": (
                    json.loads(row[8])
                    if isinstance(row[8], str) and row[8]
                    else (row[8] if isinstance(row[8], list) else [])
                ),
                "provenance_status": row[9] or "unavailable",
                "calculation_version": row[10] or "legacy-v1",
                "generated_at": row[11].isoformat() if hasattr(row[11], "isoformat") else row[11],
            }
            for row in results
        ]

    def query_keyword_cloud(self, days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
        """Get keyword frequency for word cloud, aggregated over N days."""
        conn = self._get_conn()
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        results = conn.execute(f"""
            SELECT
                keyword,
                SUM(content_count) AS total,
                CASE
                    WHEN COUNT(*) = SUM(CASE WHEN provenance_status = 'complete' THEN 1 ELSE 0 END)
                        THEN 'complete'
                    WHEN SUM(CASE WHEN provenance_status IN ('complete', 'sample_only') THEN 1 ELSE 0 END) > 0
                        THEN 'partial'
                    ELSE 'unavailable'
                END AS traceability
            FROM oltp_db.topic_trends
            WHERE keyword IS NOT NULL
              AND snapshot_date >= '{cutoff}'
            GROUP BY keyword
            ORDER BY total DESC
            LIMIT {limit}
        """).fetchall()

        return [{"keyword": row[0], "count": int(row[1]), "traceability": row[2]} for row in results]
