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
from app.services._duckdb_stats_helpers import (  # noqa: F401 — re-export
    stats_row_to_scoring_input,
    stats_threshold_from_scored,
    selected_stats_items,
    stats_date_key,
    stats_source_key,
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

    def _content_visibility_clause(
        self,
        conn,
        *,
        public_only: bool,
        visible_user_id: int | None,
    ) -> tuple[str, list[Any]]:
        """Return a content-owner filter when the attached schema supports it.

        Some historical/test databases predate ``content_items.owner_user_id``.
        Keeping the feature-detection fallback lets those read-only analytical
        fixtures stay compatible while production data gets the same visibility
        contract as the OLTP path.
        """
        if not public_only and visible_user_id is None:
            return "", []
        if not self._oltp_column_exists(conn, "content_items", "owner_user_id"):
            logger.debug("DuckDB attached content_items has no owner_user_id column; visibility filter disabled")
            return "", []
        if public_only:
            return " AND c.owner_user_id IS NULL", []
        return " AND (c.owner_user_id IS NULL OR c.owner_user_id = ?)", [visible_user_id]

    def _oltp_column_exists(self, conn, table_name: str, column_name: str) -> bool:
        """Return whether an attached OLTP table exposes a column.

        The production schema is migrated together, but read-only development
        snapshots and historical test fixtures can lag behind.  Analytics
        should keep serving the compatible subset rather than failing an
        entire endpoint because an optional score or ownership field is new.
        """
        try:
            result = conn.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'oltp_db'
                  AND table_name = ?
                  AND column_name = ?
                """,
                [table_name, column_name],
            ).fetchone()
            return bool(result and result[0])
        except Exception as exc:
            logger.debug(
                "DuckDB attached schema lookup failed for %s.%s: %s",
                table_name,
                column_name,
                exc,
            )
            return False

    # ── Analytical queries ──────────────────────────────────────────────

    def query_today_picks(
        self,
        hours: int = 48,
        curation_threshold: float = 55,
        weight_bonus: int = 8,
        risk_threshold: float | None = None,
        category: str | None = None,
        limit: int | None = None,
        visible_user_id: int | None = None,
        public_only: bool = True,
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
        visibility_clause, visibility_params = self._content_visibility_clause(
            conn,
            public_only=public_only,
            visible_user_id=visible_user_id,
        )
        params.extend(visibility_params)
        analysis_source_weight_expr = (
            "a.source_weight AS analysis_source_weight"
            if self._oltp_column_exists(conn, "ai_analyses", "source_weight")
            else "CAST(NULL AS DOUBLE) AS analysis_source_weight"
        )
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
                c.content_hash, c.summary, c.cover_url,
                c.category, c.tags, c.language, c.status, c.is_favorited,
                c.topic_id, c.duplicate_of, c.similarity_score,
                c.created_at, c.updated_at,
                a.id AS analysis_id, a.created_at AS analysis_created_at,
                a.quality_score, a.hot_score, a.freshness_score,
                a.creator_score, a.viral_score, a.risk_score,
                a.curation_score, a.info_density, a.actionability,
                {analysis_source_weight_expr},
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
              {visibility_clause}
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
            "analysis_source_weight",
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
                "analysis_source_weight",
                "feedback_score",
                "similarity_score",
            ):
                val = item.get(score_field)
                if val is not None:
                    item[score_field] = float(val)
            items.append(item)

        return items

    def query_low_follower_viral(
        self,
        hours: int = 48,
        category: str | None = None,
        limit: int = 500,
        offset: int = 0,
        visible_user_id: int | None = None,
        public_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Low-Follower Viral discovery via DuckDB.

        Pushes the entire LFV scoring + sorting + pagination into SQL,
        eliminating the 500-row Python batch fetch + Python sort.

        Returns (page_items, total).
        """
        import math

        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        risk_threshold = float(SCORING_CONFIG["risk_threshold"])
        now_ts = datetime.now(UTC).timestamp()

        category_clause = ""
        params: list[Any] = [cutoff]
        if category:
            category_clause = " AND c.category = ?"
            params.append(category)
        visibility_clause, visibility_params = self._content_visibility_clause(
            conn,
            public_only=public_only,
            visible_user_id=visible_user_id,
        )
        params.extend(visibility_params)

        # LFV score formula (mirrors scoring_engine.score_low_follower_viral):
        #   content_score   = viral*0.45 + creator*0.30 + quality*0.25
        #   obscure_factor  = GREATEST(0.05, 1 - source_weight/100)
        #   freshness_boost = 1 + freshness_score/200
        #   time_decay      = GREATEST(0.3, LEAST(1.0, EXP(-0.02 * hours_age)))
        #   lfv_final       = content_score * obscure_factor * freshness_boost * time_decay
        lfv_sql = f"""
            WITH {LATEST_ANALYSIS_CTE},
                 {self._feedback_scores_cte(conn)},
                 {IGNORED_CONTENT_CTE},
                 scored AS (
                    SELECT
                        c.id, c.title, c.url, c.source_id, c.source_name, c.source_type,
                        c.platform, c.author, c.published_at, c.crawled_at,
                        c.content_hash, c.summary, c.cover_url,
                        c.category, c.tags, c.language, c.status,
                        c.topic_id, c.duplicate_of, c.similarity_score,
                        c.created_at, c.updated_at,
                        a.id AS analysis_id, a.created_at AS analysis_created_at,
                        a.quality_score, a.hot_score, a.freshness_score,
                        a.creator_score, a.viral_score, a.risk_score,
                        a.curation_score, a.info_density, a.actionability,
                        a.source_weight, a.recommended_reason, a.recommendation,
                        a.summary AS ai_summary, a.tags AS ai_tags,
                        COALESCE(s.weight, 3) AS source_weight_db,
                        COALESCE(f.feedback_score, 0) AS feedback_score,
                        -- LFV computation
                        COALESCE(a.viral_score, 0) * 0.45
                          + COALESCE(a.creator_score, 0) * 0.30
                          + COALESCE(a.quality_score, 0) * 0.25 AS content_score,
                        GREATEST(0.05, 1.0 - COALESCE(a.source_weight, 50) / 100.0) AS obscure_factor,
                        1.0 + COALESCE(a.freshness_score, 0) / 200.0 AS freshness_boost,
                        GREATEST(0.3, LEAST(1.0, EXP(-0.02 * (
                            ({now_ts} - EPOCH(COALESCE(c.published_at, c.crawled_at))) / 3600.0
                        )))) AS time_decay
                    FROM oltp_db.content_items c
                    LEFT JOIN latest_analysis a ON a.content_id = c.id
                    LEFT JOIN oltp_db.sources s ON s.id = c.source_id
                    LEFT JOIN feedback_scores f ON f.content_id = c.id
                    LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
                    WHERE c.status = 'analyzed'
                      AND c.crawled_at >= ?
                      AND ignored.content_id IS NULL
                      AND a.risk_score <= {risk_threshold}
                      AND c.duplicate_of IS NULL
                      {category_clause}
                      {visibility_clause}
                )
            SELECT * FROM scored
            ORDER BY content_score * obscure_factor * freshness_boost * time_decay DESC
            LIMIT ? OFFSET ?
        """
        query_params = params + [limit, offset]
        results = conn.execute(lfv_sql, query_params).fetchall()

        # Total count (separate query without LIMIT/OFFSET)
        count_sql = f"""
            WITH {LATEST_ANALYSIS_CTE},
                 {IGNORED_CONTENT_CTE},
                 scored AS (
                    SELECT c.id
                    FROM oltp_db.content_items c
                    LEFT JOIN latest_analysis a ON a.content_id = c.id
                    LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
                    WHERE c.status = 'analyzed'
                      AND c.crawled_at >= ?
                      AND ignored.content_id IS NULL
                      AND a.risk_score <= {risk_threshold}
                      AND c.duplicate_of IS NULL
                      {category_clause}
                      {visibility_clause}
                )
            SELECT COUNT(*) FROM scored
        """
        total = conn.execute(count_sql, params).fetchone()[0]

        columns = [
            "id", "title", "url", "source_id", "source_name", "source_type",
            "platform", "author", "published_at", "crawled_at",
            "content_hash", "summary", "cover_url",
            "category", "tags", "language", "status",
            "topic_id", "duplicate_of", "similarity_score",
            "created_at", "updated_at",
            "analysis_id", "analysis_created_at",
            "quality_score", "hot_score", "freshness_score",
            "creator_score", "viral_score", "risk_score",
            "curation_score", "info_density", "actionability",
            "source_weight", "recommended_reason", "recommendation",
            "ai_summary", "ai_tags",
            "source_weight_db", "feedback_score",
            "content_score", "obscure_factor", "freshness_boost", "time_decay",
        ]

        items: list[dict[str, Any]] = []
        for row in results:
            item = dict(zip(columns, row))
            # Compute final LFV score
            lfv_final = round(
                float(item["content_score"])
                * float(item["obscure_factor"])
                * float(item["freshness_boost"])
                * float(item["time_decay"]),
                2,
            )
            # Serialize datetime fields
            for dt_field in ("published_at", "crawled_at", "created_at", "updated_at", "analysis_created_at"):
                val = item.get(dt_field)
                if val and hasattr(val, "isoformat"):
                    item[dt_field] = val.isoformat()
            # Round floats
            for score_field in (
                "quality_score", "hot_score", "freshness_score", "creator_score",
                "viral_score", "risk_score", "curation_score", "info_density",
                "actionability", "similarity_score", "obscure_factor",
                "freshness_boost", "time_decay", "content_score",
            ):
                val = item.get(score_field)
                if val is not None:
                    item[score_field] = round(float(val), 4 if score_field in ("obscure_factor", "freshness_boost", "time_decay") else 2)

            items.append({
                "lfv_final": lfv_final,
                "content_score": item["content_score"],
                "obscure_factor": item["obscure_factor"],
                "freshness_boost": item["freshness_boost"],
                "time_decay": item["time_decay"],
                "source_weight": item.get("source_weight"),
                "raw_item": item,
            })

        return items, total

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
            "curated_count": len(selected_stats_items(scored_items)),
            "avg_curation": round(float(row[1] or 0), 1),
            "max_curation": round(float(row[2] or 0), 1),
            "topic_count": row[3] or 0,
            "dup_count": row[4] or 0,
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
            SELECT c.id, c.title, c.url, c.category, c.source_name, c.platform,
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
                "url": row[2] or "",
                "category": row[3] or "未分类",
                "source_name": row[4] or "",
                "platform": row[5] or "",
                "crawled_at": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6],
                "summary": row[7] or "",
                "creator_score": float(row[8]) if row[8] else 0,
                "viral_score": float(row[9]) if row[9] else 0,
                "quality_score": float(row[10]) if row[10] else 0,
                "hot_score": float(row[11]) if row[11] else 0,
                "freshness_score": float(row[12]) if row[12] else 0,
                "risk_score": float(row[13]) if row[13] else 0,
                "curation_score": float(row[14]) if row[14] else 0,
                "info_density": float(row[15]) if row[15] else 50,
                "actionability": float(row[16]) if row[16] else 50,
                "source_weight": float(row[17]) if row[17] else 50,
                "tags": row[18] or [],
                "recommendation": row[19] or "",
                "recommended_reason": row[20] or "",
                "source_weight_db": int(row[21]) if row[21] else 3,
                "feedback_score": float(row[22]) if row[22] else 0,
                "adjusted_score": round(float(row[23] or 0), 1),
            }
            for row in results
        ]

    # ── Webnovel weekly report queries ─────────────────────────────────

    def query_webnovel_weekly(self, days: int = 7) -> dict[str, Any]:
        """Build webnovel weekly report data entirely in DuckDB.

        Uses window functions to compute rank movements across snapshots.
        Any SQL failure will raise to caller for OLTP fallback.
        """
        import json as _json

        conn = self._get_conn()
        today = date.today()
        start = today - timedelta(days=max(3, min(days, 31)) - 1)
        start_iso = start.isoformat()
        end_iso = today.isoformat()

        # ── 番茄排名快照变化（窗口函数） ──
        rows = conn.execute(f"""
            WITH ranked AS (
                SELECT book_id, book_name, rank_type, category_id,
                       position, read_count, snapshot_date,
                       FIRST_VALUE(position) OVER (PARTITION BY book_id, rank_type ORDER BY snapshot_date) AS first_pos,
                       LAST_VALUE(position) OVER (PARTITION BY book_id, rank_type ORDER BY snapshot_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS last_pos,
                       FIRST_VALUE(read_count) OVER (PARTITION BY book_id, rank_type ORDER BY snapshot_date) AS first_reads,
                       LAST_VALUE(read_count) OVER (PARTITION BY book_id, rank_type ORDER BY snapshot_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS last_reads,
                       FIRST_VALUE(snapshot_date) OVER (PARTITION BY book_id, rank_type ORDER BY snapshot_date) AS first_date,
                       LAST_VALUE(snapshot_date) OVER (PARTITION BY book_id, rank_type ORDER BY snapshot_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS last_date
                FROM oltp_db.fanqie_rank_snapshots
                WHERE snapshot_date >= '{start_iso}' AND snapshot_date <= '{end_iso}'
            ),
            movements AS (
                SELECT DISTINCT book_id, book_name, rank_type, category_id,
                       last_pos AS position, (first_pos - last_pos) AS change,
                       first_reads, last_reads, first_date, last_date
                FROM ranked
                WHERE first_date != last_date
            )
            SELECT book_name, rank_type, category_id, position, change,
                   CAST(first_reads AS BIGINT) AS first_reads,
                   CAST(last_reads AS BIGINT) AS last_reads
            FROM movements
            WHERE change != 0
            ORDER BY ABS(change) DESC
            LIMIT 24
        """).fetchall()
        fanqie_movements: list[dict] = []
        read_count_delta = 0
        for row in rows:
            fanqie_movements.append({
                "platform": "fanqie", "platform_label": "番茄小说",
                "title": row[0] or "", "author": "",
                "category": row[2] or "未分类", "rank_type": row[1] or "",
                "position": int(row[3]) if row[3] else 0,
                "change": int(row[4]) if row[4] else 0,
                "url": None,
            })
            fr = int(row[5]) if row[5] else 0
            lr = int(row[6]) if row[6] else 0
            read_count_delta += max(0, lr - fr)

        # 番茄日级计数
        daily_rows = conn.execute(f"""
            SELECT snapshot_date, COUNT(*) AS cnt
            FROM oltp_db.fanqie_rank_snapshots
            WHERE snapshot_date >= '{start_iso}' AND snapshot_date <= '{end_iso}'
            GROUP BY snapshot_date ORDER BY snapshot_date
        """).fetchall()
        fanqie_daily_counts = [{"date": str(r[0]), "count": int(r[1])} for r in daily_rows]
        fanqie_snapshot_dates = [str(r[0]) for r in daily_rows]

        # 番茄分类热度
        cat_rows = conn.execute(f"""
            WITH latest AS (
                SELECT MAX(snapshot_date) AS d FROM oltp_db.fanqie_rank_snapshots
                WHERE snapshot_date >= '{start_iso}' AND snapshot_date <= '{end_iso}'
            )
            SELECT COALESCE(c.name, s.category_id) AS cat, COUNT(*) AS cnt
            FROM oltp_db.fanqie_rank_snapshots s
            LEFT JOIN oltp_db.fanqie_categories c ON c.fanqie_id = s.category_id
            WHERE s.snapshot_date = (SELECT d FROM latest)
            GROUP BY cat ORDER BY cnt DESC LIMIT 10
        """).fetchall()
        fanqie_category_mix = [{"category": str(r[0]), "count": int(r[1])} for r in cat_rows]

        # ── 番茄当前 rank_pos_diff ──
        count_row = conn.execute("SELECT COUNT(*) FROM oltp_db.fanqie_books").fetchone()
        fanqie_count = int(count_row[0]) if count_row else 0
        cur_rows = conn.execute("""
            SELECT book_name, author, category_name, rank_type, current_pos, rank_pos_diff, book_id
            FROM oltp_db.fanqie_books
            WHERE rank_pos_diff IS NOT NULL AND rank_pos_diff != 0
            ORDER BY ABS(rank_pos_diff) DESC LIMIT 30
        """).fetchall()
        fanqie_current = [{
            "platform": "fanqie", "platform_label": "番茄小说",
            "title": r[0] or "", "author": r[1] or "",
            "category": r[2] or "未分类", "rank_type": r[3] or "",
            "position": int(r[4]) if r[4] else 0,
            "change": int(r[5]) if r[5] else 0,
            "url": f"https://fanqienovel.com/page/{r[6]}" if r[6] else None,
        } for r in cur_rows]

        # ── 七猫 ──
        count_row = conn.execute("SELECT COUNT(*) FROM oltp_db.qimao_books").fetchone()
        qimao_count = int(count_row[0]) if count_row else 0
        cur_rows = conn.execute("""
            SELECT title, author, category1_name, channel, rank_type, position, index_change, book_id
            FROM oltp_db.qimao_books
            WHERE index_change IS NOT NULL AND index_change != 0
            ORDER BY ABS(index_change) DESC LIMIT 30
        """).fetchall()
        qimao_current = [{
            "platform": "qimao", "platform_label": "七猫小说",
            "title": r[0] or "", "author": r[1] or "",
            "category": r[2] or "未分类", "rank_type": f"{r[3]}_{r[4]}",
            "position": int(r[5]) if r[5] else 0,
            "change": int(r[6]) if r[6] else 0,
            "url": f"https://www.qimao.com/shuku/{r[7]}/" if r[7] else None,
        } for r in cur_rows]
        cat_rows = conn.execute("""
            SELECT category1_name, COUNT(*) AS cnt FROM oltp_db.qimao_books
            WHERE category1_name IS NOT NULL
            GROUP BY category1_name ORDER BY cnt DESC LIMIT 8
        """).fetchall()
        qimao_categories = [{"category": str(r[0]), "count": int(r[1])} for r in cat_rows]

        # ── 知乎 ──
        count_row = conn.execute("SELECT COUNT(*) FROM oltp_db.zhihu_albums").fetchone()
        zhihu_count = int(count_row[0]) if count_row else 0
        cur_rows = conn.execute("""
            SELECT title, author, COALESCE(category2_name, category1_name) AS cat,
                   sort_type, position, rank_pos_diff, url
            FROM oltp_db.zhihu_albums
            WHERE rank_pos_diff IS NOT NULL AND rank_pos_diff != 0
            ORDER BY ABS(rank_pos_diff) DESC, position ASC LIMIT 30
        """).fetchall()
        zhihu_current = [{
            "platform": "zhihu", "platform_label": "知乎盐选",
            "title": r[0] or "", "author": r[1] or "",
            "category": r[2] or "未分类", "rank_type": r[3] or "",
            "position": int(r[4]) if r[4] else 0,
            "change": int(r[5]) if r[5] else 0,
            "url": r[6],
        } for r in cur_rows]
        cat_rows = conn.execute("""
            SELECT category2_name, COUNT(*) AS cnt FROM oltp_db.zhihu_albums
            WHERE category2_name IS NOT NULL
            GROUP BY category2_name ORDER BY cnt DESC LIMIT 8
        """).fetchall()
        zhihu_categories = [{"category": str(r[0]), "count": int(r[1])} for r in cat_rows]

        # ── 黑岩 / 点众（trending 快照） ──
        def _trending_platform(source: str) -> tuple[list[dict], int, list[dict], list[str]]:
            count_row = conn.execute(f"""
                SELECT COUNT(*) FROM oltp_db.trending_items WHERE source = '{source}'
            """).fetchone()
            count = int(count_row[0]) if count_row else 0

            cat_field = "sortName" if source == "heiyan" else "shelf"
            cat_rows = conn.execute(f"""
                SELECT json_extract_string(extra, '$.{cat_field}') AS cat, COUNT(*) AS cnt
                FROM oltp_db.trending_items
                WHERE source = '{source}' AND extra IS NOT NULL
                GROUP BY cat ORDER BY cnt DESC LIMIT 8
            """).fetchall()
            categories = [{"category": str(r[0] or "未分类"), "count": int(r[1])} for r in cat_rows]

            snap_rows = conn.execute(f"""
                SELECT snapshot_date, items
                FROM oltp_db.trending_snapshots
                WHERE source = '{source}'
                  AND snapshot_date >= '{start_iso}' AND snapshot_date <= '{end_iso}'
                ORDER BY snapshot_date
            """).fetchall()
            movements: list[dict] = []
            snap_dates: list[str] = []
            if snap_rows:
                snap_dates = sorted({str(r[0]) for r in snap_rows})
                best_rank: dict[tuple[str, str], tuple[int, str | None]] = {}
                for row in snap_rows:
                    snap_date = str(row[0])
                    items_data = row[1]
                    if isinstance(items_data, str):
                        items_data = _json.loads(items_data)
                    if not items_data:
                        continue
                    for item in items_data:
                        title = (item.get("title") or "").strip()
                        if not title:
                            continue
                        rank = item.get("rank", 0)
                        key = (snap_date, title)
                        if key not in best_rank or rank < best_rank[key][0]:
                            best_rank[key] = (rank, item.get("url"))

                by_title: dict[str, list[tuple[str, int, str | None]]] = {}
                for (sd, title), (rank, url) in best_rank.items():
                    by_title.setdefault(title, []).append((sd, rank, url))

                for title, entries in by_title.items():
                    entries.sort(key=lambda e: e[0])
                    first, latest = entries[0], entries[-1]
                    if first[0] == latest[0]:
                        continue
                    change = first[1] - latest[1]
                    if change == 0:
                        continue
                    movements.append({
                        "platform": source,
                        "platform_label": "黑岩书城" if source == "heiyan" else "点众阅读",
                        "title": title, "author": "",
                        "category": "未分类", "rank_type": "rank",
                        "position": latest[1], "change": change,
                        "url": latest[2],
                    })
                movements.sort(key=lambda m: abs(m["change"]), reverse=True)
            return movements, count, categories, snap_dates

        heiyan_movements, heiyan_count, heiyan_categories, heiyan_dates = _trending_platform("heiyan")
        ishugui_movements, ishugui_count, ishugui_categories, ishugui_dates = _trending_platform("ishugui")

        # ── 合并番茄快照 + 当前 movements ──
        all_fanqie = list(fanqie_current)
        if fanqie_movements:
            keys = {(m["platform"], m["title"], m["rank_type"]) for m in all_fanqie}
            all_fanqie.extend(m for m in fanqie_movements if (m["platform"], m["title"], m["rank_type"]) not in keys)

        # ── 跨平台涨跌归一化 ──
        platform_movements = {
            "fanqie": all_fanqie, "qimao": qimao_current,
            "zhihu": zhihu_current, "heiyan": heiyan_movements,
            "ishugui": ishugui_movements,
        }
        top_risers, top_fallers, rising_total, falling_total = [], [], 0, 0
        rising_pool, falling_pool = [], []
        for movements in platform_movements.values():
            risers = sorted([m for m in movements if m["change"] > 0], key=lambda m: m["change"], reverse=True)
            fallers = sorted([m for m in movements if m["change"] < 0], key=lambda m: m["change"])
            rising_total += len(risers)
            falling_total += len(fallers)
            rising_pool.extend(risers[:5])
            falling_pool.extend(fallers[:5])
        top_risers = sorted(rising_pool, key=lambda m: m["change"], reverse=True)[:10]
        top_fallers = sorted(falling_pool, key=lambda m: m["change"])[:10]

        # ── 组装最终结果 ──
        safe_days = max(3, min(days, 31))
        return {
            "period": {
                "start": start_iso, "end": end_iso, "days": safe_days,
                "label": f"{start.month}月{start.day}日 ~ {today.month}月{today.day}日",
            },
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": {
                "total_items": fanqie_count + qimao_count + zhihu_count + heiyan_count + ishugui_count,
                "snapshot_days": len(fanqie_snapshot_dates),
                "rising_count": rising_total,
                "falling_count": falling_total,
                "read_count_delta": read_count_delta,
            },
            "platforms": [
                {"platform": "fanqie", "label": "番茄小说", "item_count": fanqie_count,
                 "rising_count": len([m for m in all_fanqie if m["change"] > 0]),
                 "falling_count": len([m for m in all_fanqie if m["change"] < 0]),
                 "history_days": len(fanqie_snapshot_dates)},
                {"platform": "qimao", "label": "七猫小说", "item_count": qimao_count,
                 "rising_count": len([m for m in qimao_current if m["change"] > 0]),
                 "falling_count": len([m for m in qimao_current if m["change"] < 0]),
                 "history_days": 1 if qimao_count else 0},
                {"platform": "zhihu", "label": "知乎盐选", "item_count": zhihu_count,
                 "rising_count": len([m for m in zhihu_current if m["change"] > 0]),
                 "falling_count": len([m for m in zhihu_current if m["change"] < 0]),
                 "history_days": 1 if zhihu_count else 0},
                {"platform": "heiyan", "label": "黑岩书城", "item_count": heiyan_count,
                 "rising_count": len([m for m in heiyan_movements if m["change"] > 0]),
                 "falling_count": len([m for m in heiyan_movements if m["change"] < 0]),
                 "history_days": len(heiyan_dates)},
                {"platform": "ishugui", "label": "点众阅读", "item_count": ishugui_count,
                 "rising_count": len([m for m in ishugui_movements if m["change"] > 0]),
                 "falling_count": len([m for m in ishugui_movements if m["change"] < 0]),
                 "history_days": len(ishugui_dates)},
            ],
            "daily_counts": fanqie_daily_counts,
            "top_risers": top_risers,
            "top_fallers": top_fallers,
            "category_mix": {
                "fanqie": fanqie_category_mix, "qimao": qimao_categories,
                "zhihu": zhihu_categories, "heiyan": heiyan_categories,
                "ishugui": ishugui_categories,
            },
            "notes": [
                "番茄小说已保存日级排名快照，可展示周内排名变化曲线。",
                "七猫小说使用 API 返回的 index_change（最近一次同步的变化）。",
                "知乎盐选使用最近一次同步的排名变化（rank_pos_diff）。",
                "黑岩书城与点众阅读基于趋势雷达每日快照对比首末日排名，分类取自最新实时数据。",
                "跨平台涨跌榜采用每平台配额制（各取前 5），避免不同榜单量纲差异导致的偏倚。",
            ],
        }


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

def query_webnovel_weekly(days: int = 7) -> dict[str, Any]:
    """Build webnovel weekly report data via DuckDB."""
    return get_analytics().query_webnovel_weekly(days=days)
