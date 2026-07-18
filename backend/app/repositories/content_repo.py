"""
ContentItem Repository.

Extends BaseRepository with content-specific queries:
  - duplicate detection via content_hash
  - status lifecycle helpers
  - topic-grouped queries
  - bulk status updates
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import database_profile
from app.core.db_backend import now_naive_utc
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.content import ContentItem, ContentStatus
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.base import BaseRepository
from app.repositories._content_repo_types import (  # noqa: F401 — re-export for scoring_flow et al.
    ANALYSIS_STALE_MINUTES,
    ScoringContentRow,
)

logger = logging.getLogger(__name__)

class ContentRepo(BaseRepository[ContentItem]):
    model = ContentItem
    filter_fields = {"source_type", "platform", "status", "category"}

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    # ── Visibility helper ─────────────────────────────────────────

    def _visibility_clauses(
        self,
        visible_user_id: int | None,
        public_only: bool = False,
    ) -> list:
        """Return WHERE clause(s) for ADR 0001 content visibility.

        - ``public_only=True``    → ``[owner_user_id IS NULL]``
        - ``visible_user_id`` set → ``[OR(owner_user_id IS NULL, owner_user_id == visible_user_id)]``
        - neither set             → ``[]`` (no filter, internal/batch callers)
        """
        if public_only:
            return [self.model.owner_user_id.is_(None)]
        if visible_user_id is not None:
            return [or_(self.model.owner_user_id.is_(None), self.model.owner_user_id == visible_user_id)]
        return []

    # ── Lookup helpers ─────────────────────────────────────────────

    async def get_by_url(self, url: str) -> ContentItem | None:
        """Find a content item by its URL."""
        result = await self.db.execute(select(self.model).where(self.model.url == url))
        return result.scalar_one_or_none()

    async def get_with_analyses(self, id: int) -> ContentItem | None:
        """Fetch a content item eagerly loaded with its AI analyses."""
        result = await self.db.execute(
            select(self.model).options(selectinload(self.model.analyses)).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    # ── Status lifecycle ───────────────────────────────────────────

    async def get_by_status(
        self,
        status: ContentStatus,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ContentItem]:
        """Fetch items with a given status, ordered by creation time."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.status == status)
            .order_by(self.model.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def list_pending_for_analysis(
        self,
        *,
        limit: int = 20,
        hours: int | None = None,
    ) -> Sequence[ContentItem]:
        """Fetch recent pending or stale analyzing items for analysis, newest collected first."""
        stale_cutoff = now_naive_utc() - timedelta(minutes=ANALYSIS_STALE_MINUTES)
        stmt = (
            select(self.model)
            .where(
                (self.model.status == ContentStatus.PENDING)
                | ((self.model.status == ContentStatus.ANALYZING) & (self.model.updated_at <= stale_cutoff))
                | ((self.model.status == ContentStatus.ERROR) & (self.model.updated_at <= stale_cutoff))
            )
            .order_by(self.model.crawled_at.desc(), self.model.created_at.desc())
            .limit(limit)
        )
        if hours is not None:
            stmt = stmt.where(self.model.crawled_at >= now_naive_utc() - timedelta(hours=hours))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def claim_pending_analysis_ids(
        self,
        *,
        limit: int = 20,
        hours: int | None = None,
    ) -> list[int]:
        """Claim pending or stale analysis candidates and return claimed IDs in queue order."""

        async def _claim() -> list[int]:
            if database_profile.is_sqlite:
                await begin_immediate_for_sqlite(self.db)

            stale_cutoff = now_naive_utc() - timedelta(minutes=ANALYSIS_STALE_MINUTES)
            claimed_at = now_naive_utc()
            stmt = (
                select(self.model.id)
                .where(
                    (self.model.status == ContentStatus.PENDING)
                    | ((self.model.status == ContentStatus.ANALYZING) & (self.model.updated_at <= stale_cutoff))
                    | ((self.model.status == ContentStatus.ERROR) & (self.model.updated_at <= stale_cutoff))
                )
                # LLM 规则过滤：skip_analysis=True 的内容（低信号/自吹/过短）不入队
                .where(self.model.skip_analysis.is_(False))
                .order_by(self.model.crawled_at.desc(), self.model.created_at.desc())
                .limit(limit)
            )
            if hours is not None:
                stmt = stmt.where(self.model.crawled_at >= now_naive_utc() - timedelta(hours=hours))
            if database_profile.is_postgresql:
                stmt = stmt.with_for_update(skip_locked=True)

            result = await self.db.execute(stmt)
            pending_ids = [int(row[0]) for row in result.all()]
            if not pending_ids:
                return []

            update_result = await self.db.execute(
                update(self.model)
                .where(self.model.id.in_(pending_ids))
                .where(
                    (self.model.status == ContentStatus.PENDING)
                    | ((self.model.status == ContentStatus.ANALYZING) & (self.model.updated_at <= stale_cutoff))
                    | ((self.model.status == ContentStatus.ERROR) & (self.model.updated_at <= stale_cutoff))
                )
                .values(status=ContentStatus.ANALYZING, updated_at=claimed_at)
            )
            await self.db.flush()
            if update_result.rowcount == len(pending_ids):
                return pending_ids

            refreshed = await self.db.execute(
                select(self.model.id)
                .where(self.model.id.in_(pending_ids))
                .where(self.model.status == ContentStatus.ANALYZING)
            )
            refreshed_ids = {int(row[0]) for row in refreshed.all()}
            return [content_id for content_id in pending_ids if content_id in refreshed_ids]

        return await retry_sqlite_locked(
            _claim,
            attempts=4,
            base_delay=0.1,
            on_retry=self.db.rollback,
        )

    async def update_status(self, id: int, status: ContentStatus) -> ContentItem:
        """Transition a single item to a new status."""
        return await self.update(id, status=status)

    async def bulk_update_status(
        self,
        ids: list[int],
        status: ContentStatus,
    ) -> int:
        """
        Bulk-update status for multiple items.
        Returns the number of rows matched.
        """
        stmt = update(self.model).where(self.model.id.in_(ids)).values(status=status, updated_at=now_naive_utc())
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def release_analyzing_to_pending(self, ids: list[int]) -> int:
        """Release still-in-flight analysis claims back to pending."""
        if not ids:
            return 0
        stmt = (
            update(self.model)
            .where(self.model.id.in_(ids))
            .where(self.model.status == ContentStatus.ANALYZING)
            .values(status=ContentStatus.PENDING, updated_at=now_naive_utc())
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    # ── Topic & duplicate helpers ──────────────────────────────────

    async def get_by_topic(
        self,
        topic_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[ContentItem], int]:
        """Paginated listing of items belonging to a topic group."""
        return await self.list_paginated(
            page=page,
            page_size=page_size,
            filters={"topic_id": topic_id},
            sort_by="published_at",
            sort_order="desc",
        )

    async def get_duplicates_of(self, canonical_id: int) -> Sequence[ContentItem]:
        """Fetch all items marked as duplicates of a canonical item."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.duplicate_of == canonical_id)
            .order_by(self.model.similarity_score.desc())
        )
        return result.scalars().all()

    async def mark_as_duplicate(
        self,
        item_id: int,
        canonical_id: int,
        similarity_score: float = 0.0,
    ) -> ContentItem:
        """Mark an item as a duplicate of another item."""
        return await self.update(
            item_id,
            duplicate_of=canonical_id,
            similarity_score=similarity_score,
        )

    async def assign_topic(
        self,
        item_id: int,
        topic_id: int,
    ) -> ContentItem:
        """Assign a content item to a topic group."""
        return await self.update(item_id, topic_id=topic_id)

    async def unassign_topic(self, item_id: int) -> ContentItem:
        """Remove a content item from its topic group."""
        return await self.update(item_id, topic_id=None)

    # ── Stats / counts ─────────────────────────────────────────────

    async def count_by_status(self) -> dict[ContentStatus, int]:
        """Return a breakdown of item counts per status."""
        stmt = select(self.model.status, func.count()).group_by(self.model.status)
        result = await self.db.execute(stmt)
        return {status: count for status, count in result.all()}

    async def count_by_category(self) -> dict[str, int]:
        """Return a breakdown of item counts per category."""
        stmt = (
            select(self.model.category, func.count())
            .where(self.model.category.isnot(None))
            .group_by(self.model.category)
        )
        result = await self.db.execute(stmt)
        return {category: count for category, count in result.all()}

    async def delete_old_pending(self, cutoff_days: int = 90) -> int:
        """删除超过指定天数的 pending 状态内容。返回删除数量。"""
        from sqlalchemy import delete as sa_delete

        cutoff = now_naive_utc() - timedelta(days=cutoff_days)
        stmt = (
            sa_delete(self.model)
            .where(self.model.status == ContentStatus.PENDING)
            .where(self.model.created_at < cutoff)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    # ── Eager-loaded paginated listing ────────────────────────────

    async def list_paginated_with_analyses(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: dict | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        exclude_ids: set | None = None,
        exclude_source_types: set[str] | None = None,
        time_cutoff: datetime | None = None,
        visible_user_id: int | None = None,
        public_only: bool = False,
        search_query: str | None = None,
    ) -> tuple[Sequence[ContentItem], int]:
        """Like list_paginated but eager-loads analyses relation.

        When ``visible_user_id`` is provided, restrict to content that is either
        public (``owner_user_id IS NULL``) or owned by that user — i.e. enforces
        ADR 0001 visibility for user-facing list endpoints. Pass ``None`` (the
        default) for batch/internal callers that must see all rows.
        """
        stmt = select(self.model).options(selectinload(self.model.analyses))
        count_stmt = select(func.count()).select_from(self.model)
        for clause in self._visibility_clauses(visible_user_id, public_only):
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

        if filters:
            for field, value in filters.items():
                if value is None:
                    continue
                col = getattr(self.model, field, None)
                if col is None:
                    continue
                if isinstance(value, str) and ("%" in value or "_" in value):
                    stmt = stmt.where(col.ilike(value))
                    count_stmt = count_stmt.where(col.ilike(value))
                else:
                    stmt = stmt.where(col == value)
                    count_stmt = count_stmt.where(col == value)

        # Full-text-ish search across title + summary + raw_content (OR)
        if search_query:
            pattern = f"%{search_query}%"
            search_clause = or_(
                self.model.title.ilike(pattern),
                self.model.summary.ilike(pattern),
                self.model.raw_content.ilike(pattern),
            )
            stmt = stmt.where(search_clause)
            count_stmt = count_stmt.where(search_clause)

        # Exclude ignored item IDs
        if exclude_ids:
            stmt = stmt.where(self.model.id.notin_(exclude_ids))
            count_stmt = count_stmt.where(self.model.id.notin_(exclude_ids))
        if exclude_source_types:
            stmt = stmt.where(self.model.source_type.notin_(exclude_source_types))
            count_stmt = count_stmt.where(self.model.source_type.notin_(exclude_source_types))

        # Time range filter
        if time_cutoff:
            stmt = stmt.where(self.model.crawled_at >= time_cutoff)
            count_stmt = count_stmt.where(self.model.crawled_at >= time_cutoff)

        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        sort_col = getattr(self.model, sort_by, self.model.created_at)
        stmt = stmt.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc())

        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        result = await self.db.execute(stmt)
        items = result.scalars().unique().all()
        return items, total

    # ── Detail with metrics + analyses ────────────────────────────

    async def get_detail(
        self,
        id: int,
        visible_user_id: int | None = None,
        public_only: bool = False,
    ) -> ContentItem | None:
        """Fetch a content item eagerly loaded with metrics and analyses.

        When ``visible_user_id`` is provided, the row is only returned if it
        is public or owned by that user; otherwise ``None`` is returned.
        Pass ``None`` (the default) for internal callers that must see all.
        """
        stmt = (
            select(self.model)
            .options(selectinload(self.model.metrics))
            .options(selectinload(self.model.analyses))
            .where(self.model.id == id)
        )
        for clause in self._visibility_clauses(visible_user_id, public_only):
            stmt = stmt.where(clause)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ── Favorites listing ─────────────────────────────────────────

    async def list_favorites(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[ContentItem], int]:
        """Paginated listing of favorited items with analyses."""
        return await self.list_paginated_with_analyses(
            page=page,
            page_size=page_size,
            filters={"is_favorited": True},
            sort_by="updated_at",
            sort_order="desc",
        )

    # ── Today picks candidates (SQLite fallback) ─────────────────

    async def list_for_today_picks(
        self,
        hours: int = 48,
        category: str | None = None,
        visible_user_id: int | None = None,
    ) -> Sequence[ContentItem]:
        """Fetch items with analyses + source for today-picks scoring.

        When ``visible_user_id`` is provided, restrict to public content
        (``owner_user_id IS NULL``) or content owned by that user. ``None``
        means no visibility filter (batch/internal callers).
        """
        from app.models.analysis import AiAnalysis
        from app.services.scoring_engine import CONFIG as SCORING_CONFIG

        cutoff = now_naive_utc() - timedelta(hours=hours)
        risk_threshold = float(SCORING_CONFIG["risk_threshold"])
        latest_analysis_id = self._latest_analysis_id_subquery(AiAnalysis)
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.analyses),
                selectinload(self.model.source),
            )
            .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
            .where(self.model.crawled_at >= cutoff)
            .where(AiAnalysis.risk_score <= risk_threshold)
        )
        if category:
            stmt = stmt.where(self.model.category == category)
        for clause in self._visibility_clauses(visible_user_id):
            stmt = stmt.where(clause)
        result = await self.db.execute(stmt)
        return result.scalars().unique().all()

    async def list_for_report_window(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        category: str | None = None,
        visible_user_id: int | None = None,
        exclude_ids: set[int] | None = None,
    ) -> Sequence[ContentItem]:
        """Fetch analyzed items in a precise report window for daily report snapshots.

        When ``visible_user_id`` is provided, restrict to public content
        (``owner_user_id IS NULL``) or content owned by that user. ``None``
        means no visibility filter (legacy / admin callers).

        口径与 today-picks / DuckDB query_today_picks 对齐：剔除重复内容
        (``duplicate_of IS NULL``) 与已忽略内容 (``exclude_ids``)。
        """
        from app.models.analysis import AiAnalysis
        from app.services.scoring_engine import CONFIG as SCORING_CONFIG

        risk_threshold = float(SCORING_CONFIG["risk_threshold"])
        latest_analysis_id = self._latest_analysis_id_subquery(AiAnalysis)
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.analyses),
                selectinload(self.model.source),
            )
            .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
            .where(self.model.crawled_at >= window_start)
            .where(self.model.crawled_at <= window_end)
            .where(AiAnalysis.risk_score <= risk_threshold)
            .where(AiAnalysis.curation_score.isnot(None))
            .where(self.model.duplicate_of.is_(None))
        )
        for clause in self._visibility_clauses(visible_user_id):
            stmt = stmt.where(clause)
        if exclude_ids:
            stmt = stmt.where(self.model.id.notin_(exclude_ids))
        if category:
            stmt = stmt.where(self.model.category == category)
        result = await self.db.execute(stmt)
        return result.scalars().unique().all()

    # ── Scoring candidates (generic, reusable) ─────────────────────────

    async def list_for_scoring(
        self,
        *,
        filters: dict | None = None,
        exclude_ids: set | None = None,
        exclude_source_types: set[str] | None = None,
        time_cutoff: datetime | None = None,
        limit: int = 500,
        visible_user_id: int | None = None,
        public_only: bool = False,
    ) -> tuple[Sequence[ContentItem], int]:
        """
        Fetch ANALYZED items with analyses + source for scoring pipeline.
        Applies all standard filters (source_type, platform, category, keyword, etc.).
        Returns (items, total_count) where total is the count of all ANALYZED items
        matching filters (for correct pagination total).
        """
        from sqlalchemy import func, select

        from app.models.analysis import AiAnalysis

        latest_analysis_id = self._latest_analysis_id_subquery(AiAnalysis)

        # Count query — all analyzed matching filters
        count_stmt = (
            select(func.count(self.model.id))
            .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
            .where(self.model.status == ContentStatus.ANALYZED)
        )

        # Data query — eager-load analyses + source
        data_stmt = (
            select(self.model)
            .options(
                selectinload(self.model.analyses),
                selectinload(self.model.source),
            )
            .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
            .where(self.model.status == ContentStatus.ANALYZED)
        )

        for field, value in (filters or {}).items():
            if value is None:
                continue
            col = getattr(self.model, field, None)
            if col is None:
                continue
            if isinstance(value, str) and ("%" in value or "_" in value):
                count_stmt = count_stmt.where(col.ilike(value))
                data_stmt = data_stmt.where(col.ilike(value))
            else:
                count_stmt = count_stmt.where(col == value)
                data_stmt = data_stmt.where(col == value)

        if exclude_ids:
            count_stmt = count_stmt.where(self.model.id.notin_(exclude_ids))
            data_stmt = data_stmt.where(self.model.id.notin_(exclude_ids))
        if exclude_source_types:
            count_stmt = count_stmt.where(self.model.source_type.notin_(exclude_source_types))
            data_stmt = data_stmt.where(self.model.source_type.notin_(exclude_source_types))
        if time_cutoff:
            count_stmt = count_stmt.where(self.model.crawled_at >= time_cutoff)
            data_stmt = data_stmt.where(self.model.crawled_at >= time_cutoff)
        for clause in self._visibility_clauses(visible_user_id, public_only):
            count_stmt = count_stmt.where(clause)
            data_stmt = data_stmt.where(clause)

        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        data_stmt = data_stmt.order_by(self.model.crawled_at.desc()).limit(limit)
        result = await self.db.execute(data_stmt)
        items = result.scalars().unique().all()
        return items, total

    async def count_for_scoring(
        self,
        *,
        exclude_ids: set | None = None,
        exclude_source_types: set[str] | None = None,
        time_cutoff: datetime | None = None,
        visible_user_id: int | None = None,
    ) -> int:
        """Count items with analysis rows eligible for scoring diagnostics.

        ``visible_user_id`` 与 ``list_scoring_rows`` 同口径：非 None 时只计
        公共池 + 该用户私有内容，保证漏斗计数与加载行口径一致。
        """
        from app.models.analysis import AiAnalysis

        stmt = select(func.count(self.model.id)).where(
            exists().where(AiAnalysis.content_id == self.model.id),
        )

        if exclude_ids:
            stmt = stmt.where(self.model.id.notin_(exclude_ids))
        if exclude_source_types:
            stmt = stmt.where(self.model.source_type.notin_(exclude_source_types))
        if time_cutoff:
            stmt = stmt.where(self.model.crawled_at >= time_cutoff)
        for clause in self._visibility_clauses(visible_user_id):
            stmt = stmt.where(clause)

        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def count_collected_for_scoring_window(
        self,
        *,
        exclude_ids: set | None = None,
        exclude_source_types: set[str] | None = None,
        time_cutoff: datetime | None = None,
        visible_user_id: int | None = None,
    ) -> int:
        """Count collected content in the same source scope as scoring diagnostics.

        ``visible_user_id`` 与 ``count_for_scoring`` / ``list_scoring_rows`` 同口径。
        """
        stmt = select(func.count(self.model.id))

        if exclude_ids:
            stmt = stmt.where(self.model.id.notin_(exclude_ids))
        if exclude_source_types:
            stmt = stmt.where(self.model.source_type.notin_(exclude_source_types))
        if time_cutoff:
            stmt = stmt.where(self.model.crawled_at >= time_cutoff)
        for clause in self._visibility_clauses(visible_user_id):
            stmt = stmt.where(clause)

        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_scoring_rows(
        self,
        *,
        exclude_ids: set | None = None,
        exclude_source_types: set[str] | None = None,
        time_cutoff: datetime | None = None,
        limit: int = 500,
        visible_user_id: int | None = None,
    ) -> list[ScoringContentRow]:
        """Fetch only columns needed by the scoring debug payload."""
        from app.models.analysis import AiAnalysis
        from app.models.source import Source

        latest_analysis_id = self._latest_analysis_id_subquery(AiAnalysis)

        stmt = (
            select(
                self.model.id,
                self.model.title,
                self.model.url,
                self.model.source_id,
                self.model.source_name,
                self.model.category,
                self.model.summary,
                self.model.tags,
                self.model.is_favorited,
                self.model.published_at,
                self.model.crawled_at,
                func.coalesce(Source.weight, 3).label("source_weight_db"),
                AiAnalysis.summary.label("ai_summary"),
                AiAnalysis.recommendation,
                AiAnalysis.recommended_reason,
                AiAnalysis.tags.label("analysis_tags"),
                AiAnalysis.creator_angles,
                AiAnalysis.curation_score,
                AiAnalysis.info_density,
                AiAnalysis.actionability,
                AiAnalysis.source_weight,
                AiAnalysis.creator_score,
                AiAnalysis.viral_score,
                AiAnalysis.freshness_score,
                AiAnalysis.quality_score,
                AiAnalysis.hot_score,
                AiAnalysis.risk_score,
            )
            .select_from(self.model)
            .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
            .outerjoin(Source, Source.id == self.model.source_id)
        )

        if exclude_ids:
            stmt = stmt.where(self.model.id.notin_(exclude_ids))
        if exclude_source_types:
            stmt = stmt.where(self.model.source_type.notin_(exclude_source_types))
        if time_cutoff:
            stmt = stmt.where(self.model.crawled_at >= time_cutoff)
        for clause in self._visibility_clauses(visible_user_id):
            stmt = stmt.where(clause)

        stmt = stmt.order_by(self.model.crawled_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return [ScoringContentRow(**row._mapping) for row in result.all()]

    def _latest_analysis_id_subquery(self, analysis_model):
        """Return a correlated subquery for the latest analysis row per content item."""
        return latest_analysis_id_subquery(self.model, analysis_model)

    # ── Recent items ───────────────────────────────────────────────

    async def get_recent(
        self,
        *,
        limit: int = 20,
        status: ContentStatus | None = None,
        source_type: str | None = None,
        platform: str | None = None,
    ) -> Sequence[ContentItem]:
        """Fetch the most recent items, optionally filtered."""
        stmt = select(self.model).order_by(self.model.created_at.desc())

        if status is not None:
            stmt = stmt.where(self.model.status == status)
        if source_type is not None:
            stmt = stmt.where(self.model.source_type == source_type)
        if platform is not None:
            stmt = stmt.where(self.model.platform == platform)

        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()
