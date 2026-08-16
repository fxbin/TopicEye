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

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

from app.core.config import settings
from app.core.db_backend import (
    create_database_profile,
    duckdb_attach_sql,
    duckdb_extension_name,
    redact_database_secrets,
)
from app.services._duckdb_picks_mixin import PicksMixin
from app.services._duckdb_reports_mixin import ReportsMixin
from app.services._duckdb_sql import (  # noqa: F401 — re-export for backward compat
    EMPTY_FEEDBACK_SCORES_CTE,
    IGNORED_CONTENT_CTE,
    LATEST_ANALYSIS_CTE,
    LATEST_FEEDBACK_SCORES_CTE,
    STATS_CURATION_FALLBACK_THRESHOLD,
)
from app.services._duckdb_stats_helpers import (  # noqa: F401 — re-export
    selected_stats_items,
    stats_date_key,
    stats_row_to_scoring_input,
    stats_source_key,
    stats_threshold_from_scored,
)
from app.services._duckdb_stats_mixin import StatsMixin
from app.services._duckdb_topics_mixin import TopicsMixin
from app.services.scoring_engine import CONFIG as SCORING_CONFIG, score_items  # noqa: F401

logger = logging.getLogger(__name__)

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

# ── DuckDB Analytics singleton ─────────────────────────────────────────


class DuckDBAnalytics(PicksMixin, TopicsMixin, StatsMixin, ReportsMixin):
    """
    Thread-local DuckDB connection that attaches OLTP data in READ_ONLY mode.

    Each thread gets its own in-memory DuckDB instance with the configured
    source attached. This avoids concurrency issues and ensures fresh data.

    Query methods are split into mixins:
    - PicksMixin: query_today_picks, query_low_follower_viral
    - TopicsMixin: query_topics, query_trend_topics, query_keyword_cloud
    - StatsMixin: query_stats_*, query_daily_stats, query_dashboard_stats
    - ReportsMixin: query_content_for_report, query_content_for_weekly, query_webnovel_weekly
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._profile = create_database_profile(settings.DATABASE_URL)
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


# ── Module-level singleton ─────────────────────────────────────────────

_analytics: DuckDBAnalytics | None = None
_lock = threading.Lock()


# DuckDB 是同步库且连接为 thread-local。固定单线程执行器保证：
# 1) 本执行器上只创建/复用一份 in-memory 连接（命中 thread-local 缓存）；
# 2) 查询保持串行——与旧的事件循环内直接调用语义一致，但不再阻塞事件循环。
_DUCKDB_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="topiceye-duckdb")

_T = TypeVar("_T")


async def run_query(query: Callable[[], _T]) -> _T:
    """在专用线程上执行同步 DuckDB 调用，供异步上下文使用。

    FastAPI endpoint / scheduler job 必须经由此助手调用 DuckDB：cache MISS
    的首次调用会触发 connect + INSTALL/LOAD + ATTACH + 查询，直接在事件
    循环上执行可达数百 ms 到秒级，会拖垮所有并发请求。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_DUCKDB_EXECUTOR, query)


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
