"""
DuckDB analytics layer for TopicEye.

Architecture:
    DuckDB connects in-memory and ATTACHes the configured OLTP database
    (SQLite or PostgreSQL) in READ_ONLY mode.  Analytical queries run directly
    against the attached tables.  Zero sync, zero redundancy — data is always
    fresh.

    SQLAlchemy: OLTP source of truth (SQLite or PostgreSQL writes).
    DuckDB: fixed OLAP layer (reads only, for analytical/aggregation queries).
    If DuckDB extension loading or ATTACH fails, analytical read APIs report the
    layer as unavailable instead of falling back to OLTP queries.

Usage:
    from app.services.duckdb_service import DuckDBAnalytics
    analytics = DuckDBAnalytics()
    picks = analytics.query_today_picks(hours=48)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
from datetime import date, datetime, timedelta, timezone, UTC
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.db_backend import (
    create_database_profile,
    duckdb_attach_sql,
    duckdb_extension_name,
    redact_database_secrets,
)
from app.services.scoring_engine import CONFIG as SCORING_CONFIG, ScoringInput, score_items
from app.services._duckdb_sql import (  # noqa: F401 — re-export for backward compat
    EMPTY_FEEDBACK_SCORES_CTE,
    IGNORED_CONTENT_CTE,
    LATEST_ANALYSIS_CTE,
    LATEST_FEEDBACK_SCORES_CTE,
    STATS_CURATION_FALLBACK_THRESHOLD,
)

logger = logging.getLogger(__name__)
# ── DuckDB Analytics singleton ─────────────────────────────────────────


class DuckDBAnalytics:
    """
    Thread-local DuckDB connection that attaches OLTP data in READ_ONLY mode.

    Each thread gets its own in-memory DuckDB instance with the configured
    source attached. This avoids concurrency issues and ensures fresh data.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._profile = create_database_profile(
            settings.DATABASE_URL,
            sqlite_domain_split_enabled=settings.DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED,
            sqlite_domain_dir=settings.DATABASE_SQLITE_DOMAIN_DIR,
        )
        self._attach_alias = "oltp_db"
        self._available: bool | None = None  # tri-state: None=unchecked
        self._last_error: str | None = None

    def _get_conn(self):
        """Get or create a thread-local DuckDB connection with OLTP attached."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        import duckdb

        conn = duckdb.connect(":memory:")
        conn.execute(f"SET threads={int(settings.DUCKDB_THREADS)}")
        conn.execute(f"SET memory_limit='{settings.DUCKDB_MEMORY_LIMIT}'")
        extension_dir = Path(settings.DUCKDB_EXTENSION_DIR).expanduser().resolve()
        extension_dir.mkdir(parents=True, exist_ok=True)
        conn.execute(f"SET extension_directory='{str(extension_dir)}'")

        extension = duckdb_extension_name(self._profile)
        conn.execute(f"INSTALL {extension}; LOAD {extension};")
        conn.execute(duckdb_attach_sql(self._profile, alias=self._attach_alias))

        self._local.conn = conn
        logger.info(
            "DuckDB analytics: attached %s OLTP source as %s (thread %s)",
            self._profile.backend,
            self._attach_alias,
            threading.current_thread().name,
        )
        return conn

    def close(self) -> None:
        """Close the thread-local DuckDB connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
            logger.info("DuckDB analytics: connection closed")

    @property
    def available(self) -> bool:
        """Check if DuckDB analytics layer is available."""
        if self._available is not None:
            return self._available
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1 FROM oltp_db.content_items LIMIT 1")
            self._available = True
            self._last_error = None
        except Exception as e:
            self._last_error = redact_database_secrets(str(e), self._profile)
            logger.warning("DuckDB analytics not available: %s", self._last_error)
            self._available = False
        return self._available

    def reset_availability(self) -> None:
        """Reset availability check (e.g. after a failure)."""
        self._available = None
        self._last_error = None

    def status(self) -> dict[str, Any]:
        """Return operational status for health and settings endpoints."""
        available = self.available
        return {
            "status": "ok" if available else "unavailable",
            "available": available,
            "backend": self._profile.backend,
            "extension": duckdb_extension_name(self._profile),
            "attach_alias": self._attach_alias,
            "mode": "duckdb_attach_read_only",
            "error": self._last_error,
        }

    def _feedback_scores_cte(self, conn) -> str:
        """Return feedback CTE, falling back when upgraded/test DBs lack the table."""
        try:
            exists = conn.execute("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'oltp_db'
                  AND table_name = 'user_feedback'
            """).fetchone()
            if exists and exists[0]:
                return LATEST_FEEDBACK_SCORES_CTE
        except Exception as exc:
            logger.debug("DuckDB feedback score CTE disabled: %s", exc)
        return EMPTY_FEEDBACK_SCORES_CTE

    # ── Analytical queries ──────────────────────────────────────────────

    def query_today_picks(
        self,
        hours: int = 48,
        curation_threshold: float = 55,
        weight_bonus: int = 8,
        risk_threshold: float | None = None,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Top curated picks from the last N hours.

        Runs the curation scoring + source weight adjustment entirely in DuckDB.
        Returns items with adjusted_curation_score >= threshold.
        """
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        params: list[Any] = [cutoff]
        feedback_min = float(SCORING_CONFIG["feedback_score_min"])
        feedback_max = float(SCORING_CONFIG["feedback_score_max"])
        feedback_weight = float(SCORING_CONFIG["w_feedback"])
        risk_threshold = float(SCORING_CONFIG["risk_threshold"] if risk_threshold is None else risk_threshold)
        category_clause = ""
        if category:
            category_clause = " AND c.category = ?"
            params.append(category)
        _ = limit

        results = conn.execute(
            f"""
            WITH {LATEST_ANALYSIS_CTE},
            {self._feedback_scores_cte(conn)},
            {IGNORED_CONTENT_CTE}
            SELECT
                c.id, c.title, c.url, c.source_id, c.source_name, c.source_type,
                c.platform, c.author,
                c.published_at, c.crawled_at,
                c.content_hash, c.summary, c.raw_content, c.cover_url,
                c.category, c.tags, c.language, c.status, c.is_favorited,
                c.topic_id, c.duplicate_of, c.similarity_score,
                c.created_at, c.updated_at,
                a.id AS analysis_id, a.created_at AS analysis_created_at,
                a.quality_score, a.hot_score, a.freshness_score,
                a.creator_score, a.viral_score, a.risk_score,
                a.curation_score, a.info_density, a.actionability,
                a.recommended_reason, a.recommendation,
                a.summary AS ai_summary, a.tags AS ai_tags,
                a.enrichment_status, a.enrichment,
                COALESCE(s.weight, 3) AS source_weight_db,
                COALESCE(f.feedback_score, 0) AS feedback_score,
                CASE
                    WHEN a.curation_score > 0
                        THEN a.curation_score + (COALESCE(s.weight, 3) - 3) * {weight_bonus}
                             + LEAST({feedback_max}, GREATEST({feedback_min}, COALESCE(f.feedback_score, 0))) * {feedback_weight}
                    ELSE (COALESCE(a.creator_score, 0) + COALESCE(a.viral_score, 0)) / 2.0
                         + (COALESCE(s.weight, 3) - 3) * {weight_bonus}
                         + LEAST({feedback_max}, GREATEST({feedback_min}, COALESCE(f.feedback_score, 0))) * {feedback_weight}
                END AS adjusted_curation_score
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN oltp_db.sources s ON s.id = c.source_id
            LEFT JOIN feedback_scores f ON f.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= ?
              AND ignored.content_id IS NULL
              AND a.risk_score <= {risk_threshold}
              AND a.curation_score IS NOT NULL
              {category_clause}
            ORDER BY adjusted_curation_score DESC
        """,
            params,
        ).fetchall()

        columns = [
            "id",
            "title",
            "url",
            "source_id",
            "source_name",
            "source_type",
            "platform",
            "author",
            "published_at",
            "crawled_at",
            "content_hash",
            "summary",
            "raw_content",
            "cover_url",
            "category",
            "tags",
            "language",
            "status",
            "is_favorited",
            "topic_id",
            "duplicate_of",
            "similarity_score",
            "created_at",
            "updated_at",
            "analysis_id",
            "analysis_created_at",
            "quality_score",
            "hot_score",
            "freshness_score",
            "creator_score",
            "viral_score",
            "risk_score",
            "curation_score",
            "info_density",
            "actionability",
            "recommended_reason",
            "recommendation",
            "ai_summary",
            "ai_tags",
            "enrichment_status",
            "enrichment",
            "source_weight_db",
            "feedback_score",
            "adjusted_curation_score",
        ]

        items: list[dict[str, Any]] = []
        for row in results:
            item = dict(zip(columns, row))
            if item["adjusted_curation_score"] < curation_threshold:
                continue
            # Serialize datetime fields
            for dt_field in ("published_at", "crawled_at", "created_at", "updated_at", "analysis_created_at"):
                val = item.get(dt_field)
                if val and hasattr(val, "isoformat"):
                    item[dt_field] = val.isoformat()
            # Round floats
            item["adjusted_curation_score"] = round(float(item["adjusted_curation_score"]), 1)
            for score_field in (
                "quality_score",
                "hot_score",
                "freshness_score",
                "creator_score",
                "viral_score",
                "risk_score",
                "curation_score",
                "info_density",
                "actionability",
                "feedback_score",
                "similarity_score",
            ):
                val = item.get(score_field)
                if val is not None:
                    item[score_field] = float(val)
            items.append(item)

        return items

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
            SELECT snapshot_date, topic_id, topic_name, content_count,
                   avg_score, max_score, pick_count, top_items
            FROM oltp_db.topic_trends
            WHERE topic_id IS NOT NULL
              AND snapshot_date >= '{cutoff}'
            ORDER BY snapshot_date, topic_id
        """).fetchall()

        return [
            {
                "date": str(row[0]) if hasattr(row[0], "isoformat") else str(row[0]),
                "topic_id": row[1],
                "topic_name": row[2],
                "content_count": row[3],
                "avg_score": float(row[4]) if row[4] else 0.0,
                "max_score": float(row[5]) if row[5] else 0.0,
                "pick_count": row[6] or 0,
                # topic_trends.top_items is a JSON string column in SQLite.
                # The DuckDB ATTACH view returns the raw text, so we parse
                # it here to honour the contract ``top_items: list[dict]``.
                # If the stored value is corrupt or missing, fall back to [].
                "top_items": (
                    json.loads(row[7])
                    if isinstance(row[7], str) and row[7]
                    else (row[7] if isinstance(row[7], list) else [])
                ),
            }
            for row in results
        ]

    def query_keyword_cloud(self, days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
        """Get keyword frequency for word cloud, aggregated over N days."""
        conn = self._get_conn()
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        results = conn.execute(f"""
            SELECT keyword, SUM(content_count) AS total
            FROM oltp_db.topic_trends
            WHERE keyword IS NOT NULL
              AND snapshot_date >= '{cutoff}'
            GROUP BY keyword
            ORDER BY total DESC
            LIMIT {limit}
        """).fetchall()

        return [{"keyword": row[0], "count": int(row[1])} for row in results]

    def query_stats_curation_threshold(self, days: int = 7) -> float:
        """Unified scorer threshold for the stats surfaces."""
        scored_items = self._query_stats_scored_items(days=days)
        return self._stats_threshold_from_scored(scored_items)

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
              AND c.duplicate_of IS NULL
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
        item_rows = [dict(zip(columns, row)) for row in rows]
        row_map = {row["id"]: row for row in item_rows}
        scored = score_items([self._stats_row_to_scoring_input(row) for row in item_rows])
        scored_items: list[dict[str, Any]] = []
        for breakdown, item in scored:
            row = dict(row_map[item.content_id])
            row["final_score"] = breakdown.final_score
            row["threshold_used"] = breakdown.threshold_used
            row["selected"] = breakdown.selected
            scored_items.append(row)
        return scored_items

    @staticmethod
    def _stats_row_to_scoring_input(row: dict[str, Any]) -> ScoringInput:
        return ScoringInput(
            content_id=row["id"],
            title="",
            category=row.get("category"),
            source_id=row.get("source_id"),
            source_name=row.get("source_name"),
            crawled_at=row.get("crawled_at"),
            curation_score=row.get("curation_score") or 0,
            info_density=row.get("info_density") or 50,
            actionability=row.get("actionability") or 50,
            source_weight=row.get("analysis_source_weight") or 50,
            creator_score=row.get("creator_score") or 0,
            viral_score=row.get("viral_score") or 0,
            freshness_score=row.get("freshness_score") or 0,
            quality_score=row.get("quality_score") or 0,
            hot_score=row.get("hot_score") or 0,
            risk_score=row.get("risk_score") or 0,
            source_weight_db=row.get("source_weight_db") or 3,
            feedback_score=row.get("feedback_score") or 0,
        )

    @staticmethod
    def _stats_threshold_from_scored(scored_items: list[dict[str, Any]]) -> float:
        for item in scored_items:
            threshold = item.get("threshold_used")
            if threshold is not None:
                return round(float(threshold), 1)
        return STATS_CURATION_FALLBACK_THRESHOLD

    @staticmethod
    def _selected_stats_items(scored_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in scored_items if item.get("selected")]

    @staticmethod
    def _stats_date_key(value: Any) -> str:
        if hasattr(value, "date"):
            return value.date().isoformat()
        return str(value).split(" ")[0]

    @staticmethod
    def _stats_source_key(item: dict[str, Any]) -> tuple[str, str]:
        return (item.get("source_name") or "未知", item.get("source_type") or "unknown")

    def _stats_selected_counts_by_source(self, scored_items: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for item in self._selected_stats_items(scored_items):
            key = self._stats_source_key(item)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _stats_selected_counts_by_date(self, scored_items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._selected_stats_items(scored_items):
            key = self._stats_date_key(item.get("crawled_at"))
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
        threshold = self._stats_threshold_from_scored(scored_items)

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
              AND c.duplicate_of IS NULL
        """).fetchone()
        today_row = conn.execute(f"""
            WITH {IGNORED_CONTENT_CTE}
            SELECT COUNT(c.id)
            FROM oltp_db.content_items c
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{today_start}'
              AND ignored.content_id IS NULL
              AND c.duplicate_of IS NULL
        """).fetchone()

        return {
            "total": row[0] or 0,
            "analyzed": row[1] or 0,
            "curated": len(self._selected_stats_items(scored_items)),
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
              AND c.duplicate_of IS NULL
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
              AND c.duplicate_of IS NULL
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
              AND c.duplicate_of IS NULL
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
                COUNT(CASE WHEN c.duplicate_of IS NOT NULL THEN 1 END) AS dup_count
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND a.risk_score <= {risk_threshold}
        """).fetchone()

        return {
            "total_items": row[0] or 0,
            "curated_count": len(self._selected_stats_items(scored_items)),
            "avg_curation": round(float(row[1] or 0), 1),
            "max_curation": round(float(row[2] or 0), 1),
            "topic_count": row[3] or 0,
            "dup_count": row[4] or 0,
        }

    def query_dashboard_stats(self, days: int = 7) -> dict[str, Any]:
        """Full stats workspace payload, with legacy dashboard fields preserved."""
        scored_items = self._query_stats_scored_items(days=days)
        selected_items = self._selected_stats_items(scored_items)
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

    def query_content_for_report(self, hours: int = 48) -> list[dict[str, Any]]:
        """Fetch recently analyzed content for daily report generation."""
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

        results = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {IGNORED_CONTENT_CTE}
            SELECT c.id, c.title, c.url, c.category, c.source_name, a.summary,
                   a.creator_score, a.viral_score, a.quality_score, a.risk_score,
                   a.recommended_reason
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= '{cutoff}'
              AND ignored.content_id IS NULL
              AND a.curation_score IS NOT NULL
            ORDER BY (COALESCE(a.creator_score, 0) + COALESCE(a.viral_score, 0)) DESC
            LIMIT 100
        """).fetchall()

        return [
            {
                "id": row[0],
                "title": row[1],
                "url": row[2],
                "category": row[3],
                "source_name": row[4],
                "summary": row[5] or "",
                "creator_score": float(row[6]) if row[6] else 0,
                "viral_score": float(row[7]) if row[7] else 0,
                "quality_score": float(row[8]) if row[8] else 0,
                "risk_score": float(row[9]) if row[9] else 0,
                "recommended_reason": row[10] or "",
            }
            for row in results
        ]

    def query_content_for_weekly(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Fetch analyzed content for a given week date range (YYYY-MM-DD strings).

        Returns items sorted by curation_score descending, with additional fields
        for weekly digest generation (tags, recommendation, curation_score).
        """
        conn = self._get_conn()
        feedback_min = float(SCORING_CONFIG["feedback_score_min"])
        feedback_max = float(SCORING_CONFIG["feedback_score_max"])
        feedback_weight = float(SCORING_CONFIG["w_feedback"])

        results = conn.execute(f"""
            WITH {LATEST_ANALYSIS_CTE},
            {self._feedback_scores_cte(conn)},
            {IGNORED_CONTENT_CTE}
            SELECT c.id, c.title, c.category, c.source_name, c.platform,
                   c.crawled_at,
                   a.summary, a.creator_score, a.viral_score, a.quality_score,
                   a.hot_score, a.freshness_score, a.risk_score,
                   a.curation_score, a.info_density, a.actionability,
                   a.source_weight, a.tags, a.recommendation,
                   a.recommended_reason,
                   COALESCE(s.weight, 3) AS source_weight_db,
                   COALESCE(f.feedback_score, 0) AS feedback_score,
                   COALESCE(a.curation_score, 0)
                       + LEAST({feedback_max}, GREATEST({feedback_min}, COALESCE(f.feedback_score, 0))) * {feedback_weight}
                       AS adjusted_score
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN oltp_db.sources s ON s.id = c.source_id
            LEFT JOIN feedback_scores f ON f.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE CAST(c.crawled_at AS DATE) >= DATE '{start_date}'
              AND CAST(c.crawled_at AS DATE) <= DATE '{end_date}'
              AND ignored.content_id IS NULL
              AND a.curation_score IS NOT NULL
            ORDER BY adjusted_score DESC, COALESCE(a.creator_score, 0) DESC
        """).fetchall()

        return [
            {
                "id": row[0],
                "title": row[1],
                "category": row[2] or "未分类",
                "source_name": row[3] or "",
                "platform": row[4] or "",
                "crawled_at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5],
                "summary": row[6] or "",
                "creator_score": float(row[7]) if row[7] else 0,
                "viral_score": float(row[8]) if row[8] else 0,
                "quality_score": float(row[9]) if row[9] else 0,
                "hot_score": float(row[10]) if row[10] else 0,
                "freshness_score": float(row[11]) if row[11] else 0,
                "risk_score": float(row[12]) if row[12] else 0,
                "curation_score": float(row[13]) if row[13] else 0,
                "info_density": float(row[14]) if row[14] else 50,
                "actionability": float(row[15]) if row[15] else 50,
                "source_weight": float(row[16]) if row[16] else 50,
                "tags": row[17] or [],
                "recommendation": row[18] or "",
                "recommended_reason": row[19] or "",
                "source_weight_db": int(row[20]) if row[20] else 3,
                "feedback_score": float(row[21]) if row[21] else 0,
                "adjusted_score": round(float(row[22] or 0), 1),
            }
            for row in results
        ]


# ── Module-level singleton ─────────────────────────────────────────────

_analytics: DuckDBAnalytics | None = None
_lock = threading.Lock()


def get_analytics() -> DuckDBAnalytics:
    """Get the module-level DuckDBAnalytics singleton."""
    global _analytics
    if _analytics is None:
        with _lock:
            if _analytics is None:
                _analytics = DuckDBAnalytics()
    return _analytics


def close_analytics() -> None:
    """Close the DuckDBAnalytics singleton."""
    global _analytics
    if _analytics is not None:
        _analytics.close()
        _analytics = None


# ── Backward-compatible function API ───────────────────────────────────
# These match the original function signatures so existing callers work
# without any changes.


def query_today_picks(hours: int = 48, **kwargs) -> list[dict[str, Any]]:
    return get_analytics().query_today_picks(hours=hours, **kwargs)


def query_topics() -> list[dict[str, Any]]:
    return get_analytics().query_topics()


def query_trend_topics(days: int = 7) -> list[dict[str, Any]]:
    return get_analytics().query_trend_topics(days=days)


def query_keyword_cloud(days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
    return get_analytics().query_keyword_cloud(days=days, limit=limit)


def query_stats_overview(days: int = 7) -> dict[str, Any]:
    return get_analytics().query_stats_overview(days=days)


def query_stats_source_distribution(days: int = 7) -> dict[str, Any]:
    return get_analytics().query_stats_source_distribution(days=days)


def query_stats_category_distribution(days: int = 7) -> dict[str, Any]:
    return get_analytics().query_stats_category_distribution(days=days)


def query_stats_daily_trend(days: int = 7) -> dict[str, Any]:
    return get_analytics().query_stats_daily_trend(days=days)


def query_stats_novel_platforms() -> dict[str, Any]:
    return get_analytics().query_stats_novel_platforms()


def query_daily_stats() -> dict[str, Any]:
    return get_analytics().query_daily_stats()


def query_dashboard_stats(days: int = 7) -> dict[str, Any]:
    return get_analytics().query_dashboard_stats(days=days)


def query_content_for_report(hours: int = 48) -> list[dict[str, Any]]:
    return get_analytics().query_content_for_report(hours=hours)


def query_content_for_weekly(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Fetch analyzed content for a given week date range (YYYY-MM-DD strings)."""
    return get_analytics().query_content_for_weekly(start_date=start_date, end_date=end_date)
