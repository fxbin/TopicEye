"""
DuckDB analytics stats mixin — extracted from duckdb_service.py.
Part of the DuckDBAnalytics class split.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services._duckdb_sql import (
    IGNORED_CONTENT_CTE,
    LATEST_ANALYSIS_CTE,
)
from app.services._duckdb_stats_helpers import (
    selected_stats_items,
    stats_date_key,
    stats_row_to_scoring_input,
    stats_source_key,
    stats_threshold_from_scored,
)
from app.services.scoring_engine import CONFIG as SCORING_CONFIG, score_items

ACCEPTED_EVENT_MEMBER_PREDICATE = """
NOT EXISTS (
    SELECT 1
    FROM oltp_db.content_event_members event_member
    JOIN oltp_db.content_event_groups event_group
      ON event_group.id = event_member.event_group_id
    WHERE event_member.content_id = c.id
      AND event_group.status = 'active'
      AND event_member.review_status IN ('auto', 'confirmed')
)
"""


class StatsMixin:
    def query_stats_curation_threshold(self, days: int = 7) -> float:
        """Unified scorer threshold for the stats surfaces."""
        scored_items = self._query_stats_scored_items(days=days)
        return stats_threshold_from_scored(scored_items)

    def _query_stats_scored_items(
        self,
        days: int = 7,
        *,
        hours: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return latest analyzed stats candidates with unified scorer results."""
        conn = self._get_conn()
        window = timedelta(hours=hours) if hours is not None else timedelta(days=days)
        cutoff = (datetime.now(UTC) - window).isoformat()
        rows = conn.execute(
            f"""
            WITH {LATEST_ANALYSIS_CTE},
            {self._feedback_scores_cte(conn)},
            {IGNORED_CONTENT_CTE}
            SELECT
                c.id,
                c.source_id,
                COALESCE(s.name, c.source_name, '未知') AS source_name,
                LOWER(COALESCE(CAST(s.source_type AS VARCHAR), 'unknown')) AS source_type,
                COALESCE(c.category, '未分类') AS category,
                c.crawled_at,
                a.curation_score,
                a.info_density,
                a.actionability,
                a.source_weight AS analysis_source_weight,
                a.creator_score,
                a.viral_score,
                a.freshness_score,
                a.quality_score,
                a.hot_score,
                a.risk_score,
                COALESCE(s.weight, 3) AS source_weight_db,
                COALESCE(f.feedback_score, 0) AS feedback_score
            FROM latest_analysis a
            JOIN oltp_db.content_items c ON c.id = a.content_id
            LEFT JOIN oltp_db.sources s ON s.id = c.source_id
            LEFT JOIN feedback_scores f ON f.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= ?
              AND ignored.content_id IS NULL
              AND {ACCEPTED_EVENT_MEMBER_PREDICATE}
              AND a.curation_score IS NOT NULL
        """,
            [cutoff],
        ).fetchall()

        columns = [
            "id",
            "source_id",
            "source_name",
            "source_type",
            "category",
            "crawled_at",
            "curation_score",
            "info_density",
            "actionability",
            "analysis_source_weight",
            "creator_score",
            "viral_score",
            "freshness_score",
            "quality_score",
            "hot_score",
            "risk_score",
            "source_weight_db",
            "feedback_score",
        ]
        item_rows = [dict(zip(columns, row, strict=False)) for row in rows]
        row_map = {row["id"]: row for row in item_rows}
        scored = score_items([stats_row_to_scoring_input(row) for row in item_rows])
        scored_items: list[dict[str, Any]] = []
        for breakdown, item in scored:
            row = dict(row_map[item.content_id])
            row["final_score"] = breakdown.final_score
            row["threshold_used"] = breakdown.threshold_used
            row["selected"] = breakdown.selected
            scored_items.append(row)
        return scored_items

    def _stats_selected_counts_by_source(self, scored_items: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for item in selected_stats_items(scored_items):
            key = stats_source_key(item)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _stats_selected_counts_by_date(self, scored_items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in selected_stats_items(scored_items):
            key = stats_date_key(item.get("crawled_at"))
            counts[key] = counts.get(key, 0) + 1
        return counts

    def query_stats_overview(
        self,
        days: int = 7,
        scored_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Content overview KPI cards, computed in DuckDB."""
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        if scored_items is None:
            scored_items = self._query_stats_scored_items(days=days)
        threshold = stats_threshold_from_scored(scored_items)

        row = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                COUNT(c.id) AS total,
                COUNT(CASE WHEN a.curation_score IS NOT NULL THEN c.id END) AS analyzed
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND {ACCEPTED_EVENT_MEMBER_PREDICATE}
        """).fetchone()
        today_row = conn.execute(f"""
            WITH {IGNORED_CONTENT_CTE}
            SELECT COUNT(c.id)
            FROM oltp_db.content_items c
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{today_start}'
              AND ignored.content_id IS NULL
              AND {ACCEPTED_EVENT_MEMBER_PREDICATE}
        """).fetchone()

        return {
            "total": row[0] or 0,
            "analyzed": row[1] or 0,
            "curated": len(selected_stats_items(scored_items)),
            "curation_threshold": round(threshold, 1),
            "today_new": today_row[0] or 0,
        }

    def query_stats_source_distribution(
        self,
        days: int = 7,
        scored_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Source distribution, computed in DuckDB."""
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        if scored_items is None:
            scored_items = self._query_stats_scored_items(days=days)
        selected_counts = self._stats_selected_counts_by_source(scored_items)
        rows = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                COALESCE(s.name, '未知') AS source_name,
                LOWER(COALESCE(CAST(s.source_type AS VARCHAR), 'unknown')) AS source_type,
                COUNT(c.id) AS content_count
            FROM oltp_db.content_items c
            LEFT JOIN oltp_db.sources s ON s.id = c.source_id
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND {ACCEPTED_EVENT_MEMBER_PREDICATE}
            GROUP BY s.id, s.name, s.source_type
            HAVING COUNT(c.id) > 0
            ORDER BY content_count DESC
            LIMIT 20
        """).fetchall()
        sources = []
        for row in rows:
            content_count = row[2] or 0
            curated_count = selected_counts.get((row[0], row[1]), 0)
            sources.append(
                {
                    "source_name": row[0],
                    "source_type": row[1],
                    "content_count": content_count,
                    "curated_count": curated_count,
                    "curation_rate": round(curated_count / content_count * 100, 1) if content_count else 0,
                }
            )
        return {"sources": sources}

    def query_stats_category_distribution(self, days: int = 7) -> dict[str, Any]:
        """Category distribution, computed in DuckDB."""
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                COALESCE(c.category, '未分类') AS category,
                COUNT(c.id) AS content_count,
                ROUND(AVG(a.curation_score), 1) AS avg_score
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND {ACCEPTED_EVENT_MEMBER_PREDICATE}
            GROUP BY c.category
            ORDER BY content_count DESC
        """).fetchall()
        return {
            "categories": [
                {
                    "category": row[0],
                    "content_count": row[1] or 0,
                    "avg_score": float(row[2]) if row[2] is not None else 0,
                }
                for row in rows
            ]
        }

    def query_stats_daily_trend(
        self,
        days: int = 7,
        scored_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Daily volume trend, computed in DuckDB."""
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        if scored_items is None:
            scored_items = self._query_stats_scored_items(days=days)
        selected_counts = self._stats_selected_counts_by_date(scored_items)
        rows = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                CAST(c.crawled_at AS DATE) AS crawl_date,
                COUNT(c.id) AS content_count,
                COUNT(CASE WHEN a.id IS NOT NULL THEN c.id END) AS analyzed_count
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND {ACCEPTED_EVENT_MEMBER_PREDICATE}
            GROUP BY CAST(c.crawled_at AS DATE)
            ORDER BY crawl_date ASC
        """).fetchall()
        return {
            "trend": [
                {
                    "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                    "content_count": row[1] or 0,
                    "curated_count": selected_counts.get(
                        row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                        0,
                    ),
                    "analyzed_count": row[2] or 0,
                }
                for row in rows
            ]
        }

    def query_stats_novel_platforms(self) -> dict[str, Any]:
        """Novel radar platform counts, computed in DuckDB."""
        conn = self._get_conn()
        fanqie = conn.execute("""
            SELECT COUNT(id), MAX(crawled_at)
            FROM oltp_db.fanqie_books
        """).fetchone()
        qimao = conn.execute("""
            SELECT COUNT(id), MAX(crawled_at)
            FROM oltp_db.qimao_books
        """).fetchone()
        zhihu = conn.execute("""
            SELECT COUNT(id), MAX(updated_at)
            FROM oltp_db.zhihu_albums
        """).fetchone()

        def fmt(value):
            if value is None:
                return None
            return value.isoformat() if hasattr(value, "isoformat") else str(value)

        return {
            "platforms": [
                {"name": "番茄小说", "table": "fanqie", "count": fanqie[0] or 0, "last_sync": fmt(fanqie[1])},
                {"name": "七猫小说", "table": "qimao", "count": qimao[0] or 0, "last_sync": fmt(qimao[1])},
                {"name": "知乎盐选", "table": "zhihu", "count": zhihu[0] or 0, "last_sync": fmt(zhihu[1])},
            ]
        }

    def query_daily_stats(self) -> dict[str, Any]:
        """Statistics for daily report generation."""
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        scored_items = self._query_stats_scored_items(hours=48)
        risk_threshold = float(SCORING_CONFIG["risk_threshold"])

        row = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                COUNT(*) AS total_items,
                AVG(a.curation_score) AS avg_curation,
                MAX(a.curation_score) AS max_curation,
                COUNT(DISTINCT c.topic_id) AS topic_count,
                COUNT(
                    CASE WHEN NOT ({ACCEPTED_EVENT_MEMBER_PREDICATE})
                    THEN 1 END
                ) AS event_member_count
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND a.risk_score <= {risk_threshold}
        """).fetchone()

        return {
            "total_items": row[0] or 0,
            "curated_count": len(selected_stats_items(scored_items)),
            "avg_curation": round(float(row[1] or 0), 1),
            "max_curation": round(float(row[2] or 0), 1),
            "topic_count": row[3] or 0,
            "event_member_count": row[4] or 0,
        }

    def query_dashboard_stats(self, days: int = 7) -> dict[str, Any]:
        """Full stats workspace payload, with legacy dashboard fields preserved."""
        scored_items = self._query_stats_scored_items(days=days)
        selected_items = selected_stats_items(scored_items)
        selected_by_source = self._stats_selected_counts_by_source(scored_items)
        selected_by_date = self._stats_selected_counts_by_date(scored_items)
        overview = self.query_stats_overview(days=days, scored_items=scored_items)
        source_distribution = self.query_stats_source_distribution(days=days, scored_items=scored_items)
        category_distribution = self.query_stats_category_distribution(days=days)
        daily_trend = self.query_stats_daily_trend(days=days, scored_items=scored_items)
        novel_platforms = self.query_stats_novel_platforms()

        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        # ── KPI row ────────────────────────────────────────────────────────
        kpi_row = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                COUNT(DISTINCT c.id) AS total_crawled,
                ROUND(AVG(a.curation_score), 1) AS avg_curation,
                COUNT(DISTINCT c.source_id) AS active_sources
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
        """).fetchone()

        # ── Source breakdown (curated count per source) ───────────────────
        source_rows = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                s.name,
                s.source_type,
                COUNT(DISTINCT c.id) AS content_count,
                ROUND(AVG(a.curation_score), 1) AS avg_score
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN oltp_db.sources s ON s.id = c.source_id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
            GROUP BY s.id, s.name, s.source_type
            HAVING COUNT(DISTINCT c.id) > 0
            ORDER BY content_count DESC
            LIMIT 20
        """).fetchall()

        # ── Daily volume trend ─────────────────────────────────────────────
        trend_rows = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT
                CAST(c.crawled_at AS DATE) AS crawl_date,
                COUNT(DISTINCT c.id) AS content_count,
                ROUND(AVG(a.curation_score), 1) AS avg_curation
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
            GROUP BY CAST(c.crawled_at AS DATE)
            ORDER BY crawl_date ASC
        """).fetchall()

        return {
            "overview": overview,
            "sources": source_distribution["sources"],
            "categories": category_distribution["categories"],
            "trend": daily_trend["trend"],
            "platforms": novel_platforms["platforms"],
            "kpi": {
                "total_crawled": kpi_row[0] or 0,
                "total_curated": len(selected_items),
                "avg_curation": round(float(kpi_row[1] or 0), 1),
                "active_sources": kpi_row[2] or 0,
            },
            "source_breakdown": [
                {
                    "source_name": row[0] or "未知",
                    "source_type": row[1] or "rss",
                    "content_count": row[2] or 0,
                    "curated_count": selected_by_source.get(
                        (row[0] or "未知", (row[1] or "rss").lower()),
                        0,
                    ),
                    "avg_score": round(float(row[3] or 0), 1),
                }
                for row in source_rows
            ],
            "daily_trend": [
                {
                    "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                    "content_count": row[1] or 0,
                    "curated_count": selected_by_date.get(
                        row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                        0,
                    ),
                    "avg_curation": round(float(row[2] or 0), 1),
                }
                for row in trend_rows
            ],
        }
