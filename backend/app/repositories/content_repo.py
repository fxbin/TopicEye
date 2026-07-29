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
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Text, cast, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import database_profile
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.core.time import naive_utc_now
from app.models.content import ContentItem, ContentStatus
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventReviewStatus,
    EventStatus,
)
from app.repositories._content_repo_types import (  # noqa: F401 — re-export for scoring_flow et al.
    ANALYSIS_STALE_MINUTES,
    ScoringContentRow,
)
from app.repositories._query_helpers import (
    apply_content_scope,
    apply_filters,
    apply_visibility,
    visibility_clauses,
)
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisClaim:
    """A durable ownership record returned when an analysis item is claimed.

    ``fencing_token`` is deliberately opaque: callers must pass it back when
    completing or failing the job.  A newly claimed worker receives a new
    token, so an expired worker can never commit a late result.
    """

    content_id: int
    fencing_token: str
    lease_expires_at: datetime


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

        Delegates to the shared ``visibility_clauses`` helper so that all
        repositories use the same visibility logic.
        """
        return visibility_clauses(
            self.model,
            visible_user_id=visible_user_id,
            public_only=public_only,
        )

    @staticmethod
    def _accepted_event_member_exists():
        return exists(
            select(ContentEventMember.id)
            .join(
                ContentEventGroup,
                ContentEventGroup.id == ContentEventMember.event_group_id,
            )
            .where(
                ContentEventMember.content_id == ContentItem.id,
                ContentEventGroup.status == EventStatus.ACTIVE,
                ContentEventMember.review_status.in_(
                    (EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED)
                ),
            )
        )

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

    @staticmethod
    def _analysis_candidate_condition(*, stale_cutoff: datetime, now: datetime):
        """Return rows that may be claimed by the durable analysis queue."""
        return (
            (ContentItem.status == ContentStatus.PENDING)
            | (
                (ContentItem.status == ContentStatus.ANALYZING)
                & (
                    # New claim protocol: the lease, rather than an unrelated
                    # content update, defines whether work can be taken over.
                    (
                        (ContentItem.analysis_lease_expires_at.is_not(None))
                        & (ContentItem.analysis_lease_expires_at <= now)
                    )
                    # Legacy rows created before the migration have no lease.
                    | ((ContentItem.analysis_lease_expires_at.is_(None)) & (ContentItem.updated_at <= stale_cutoff))
                )
            )
            | (
                (ContentItem.status == ContentStatus.ERROR)
                & (ContentItem.updated_at <= stale_cutoff)
                & (ContentItem.analysis_attempts < max(1, int(settings.ANALYSIS_MAX_ATTEMPTS)))
                & ((ContentItem.analysis_next_retry_at.is_(None)) | (ContentItem.analysis_next_retry_at <= now))
            )
        )

    @staticmethod
    def _analysis_lease_expiry(now: datetime) -> datetime:
        lease_seconds = max(1, int(settings.ANALYSIS_LEASE_SECONDS))
        return now + timedelta(seconds=lease_seconds)

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
        """Fetch eligible pending or stale items for analysis, newest collected first."""
        now = naive_utc_now()
        stale_cutoff = now - timedelta(minutes=ANALYSIS_STALE_MINUTES)
        stmt = (
            select(self.model)
            .where(self._analysis_candidate_condition(stale_cutoff=stale_cutoff, now=now))
            # 与 claim_pending_analysis_ids 使用同一资格条件。该查询还承担
            # post-sync "是否仍有积压" 的判断，不能把显式跳过 LLM 的内容算入。
            .where(self.model.skip_analysis.is_(False))
            .order_by(self.model.crawled_at.desc(), self.model.created_at.desc())
            .limit(limit)
        )
        if hours is not None:
            stmt = stmt.where(self.model.crawled_at >= naive_utc_now() - timedelta(hours=hours))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_pending_for_analysis(self) -> int:
        """统计仍可被分析队列领取的内容数（模型池积压深度）。

        与 :meth:`list_pending_for_analysis` / :meth:`claim_pending_analysis_jobs`
        使用完全相同的资格谓词（同一 candidate condition + ``skip_analysis=False``），
        只计数不取行，供 ``/metrics`` 导出 ``topiceye_analysis_pending_total``。
        保持谓词同步是 MP-P0-T4 的正确性不变量，不得在此另写一套条件。
        """
        now = naive_utc_now()
        stale_cutoff = now - timedelta(minutes=ANALYSIS_STALE_MINUTES)
        count = await self.db.scalar(
            select(func.count())
            .select_from(self.model)
            .where(self._analysis_candidate_condition(stale_cutoff=stale_cutoff, now=now))
            .where(self.model.skip_analysis.is_(False))
        )
        return count or 0

    async def claim_pending_analysis_ids(
        self,
        *,
        limit: int = 20,
        hours: int | None = None,
    ) -> list[int]:
        """Compatibility wrapper returning IDs for legacy batch callers.

        New consumers should use :meth:`claim_pending_analysis_jobs` and keep
        the returned fencing tokens through completion.  IDs alone cannot
        prove ownership after a lease expires.
        """
        claims = await self.claim_pending_analysis_jobs(limit=limit, hours=hours)
        return [claim.content_id for claim in claims]

    async def claim_pending_analysis_jobs(
        self,
        *,
        limit: int = 20,
        hours: int | None = None,
    ) -> list[AnalysisClaim]:
        """Atomically claim eligible work and return durable ownership tokens."""

        async def _claim() -> list[AnalysisClaim]:
            if database_profile.is_sqlite:
                await begin_immediate_for_sqlite(self.db)

            claimed_at = naive_utc_now()
            stale_cutoff = claimed_at - timedelta(minutes=ANALYSIS_STALE_MINUTES)
            candidate_condition = self._analysis_candidate_condition(stale_cutoff=stale_cutoff, now=claimed_at)
            stmt = (
                select(self.model.id)
                .where(candidate_condition)
                # LLM 规则过滤：skip_analysis=True 的内容（低信号/自吹/过短）不入队
                .where(self.model.skip_analysis.is_(False))
                .order_by(self.model.crawled_at.desc(), self.model.created_at.desc())
                .limit(limit)
            )
            if hours is not None:
                stmt = stmt.where(self.model.crawled_at >= naive_utc_now() - timedelta(hours=hours))
            if database_profile.is_postgresql:
                stmt = stmt.with_for_update(skip_locked=True)

            result = await self.db.execute(stmt)
            pending_ids = [int(row[0]) for row in result.all()]
            if not pending_ids:
                return []

            lease_expires_at = self._analysis_lease_expiry(claimed_at)
            claims: list[AnalysisClaim] = []
            # A per-row token is intentional.  A bulk UPDATE cannot assign a
            # distinct fencing token to each item, and the selected rows are
            # locked on PostgreSQL / protected by BEGIN IMMEDIATE on SQLite.
            for content_id in pending_ids:
                fencing_token = uuid4().hex
                update_result = await self.db.execute(
                    update(self.model)
                    .where(self.model.id == content_id)
                    .where(candidate_condition)
                    .values(
                        status=ContentStatus.ANALYZING,
                        updated_at=claimed_at,
                        analysis_attempts=self.model.analysis_attempts + 1,
                        analysis_next_retry_at=None,
                        analysis_claim_token=fencing_token,
                        analysis_lease_expires_at=lease_expires_at,
                    )
                )
                if update_result.rowcount:
                    claims.append(
                        AnalysisClaim(
                            content_id=content_id,
                            fencing_token=fencing_token,
                            lease_expires_at=lease_expires_at,
                        )
                    )
            await self.db.flush()
            return claims

        return await retry_sqlite_locked(
            _claim,
            attempts=4,
            base_delay=0.1,
            on_retry=self.db.rollback,
        )

    async def claim_analysis_job(self, content_id: int) -> AnalysisClaim | None:
        """Claim one eligible item and return its fencing token.

        This is the single-item counterpart to ``claim_pending_analysis_jobs``
        and lets API-triggered analysis use the durable protocol immediately.
        """

        async def _claim() -> AnalysisClaim | None:
            claimed_at = naive_utc_now()
            candidate_condition = self._analysis_candidate_condition(
                stale_cutoff=claimed_at - timedelta(minutes=ANALYSIS_STALE_MINUTES),
                now=claimed_at,
            )
            fencing_token = uuid4().hex
            lease_expires_at = self._analysis_lease_expiry(claimed_at)
            result = await self.db.execute(
                update(self.model)
                .where(self.model.id == content_id)
                .where(self.model.skip_analysis.is_(False))
                .where(candidate_condition)
                .values(
                    status=ContentStatus.ANALYZING,
                    updated_at=claimed_at,
                    analysis_attempts=self.model.analysis_attempts + 1,
                    analysis_next_retry_at=None,
                    analysis_claim_token=fencing_token,
                    analysis_lease_expires_at=lease_expires_at,
                )
            )
            await self.db.flush()
            if not result.rowcount:
                return None
            return AnalysisClaim(
                content_id=content_id,
                fencing_token=fencing_token,
                lease_expires_at=lease_expires_at,
            )

        return await retry_sqlite_locked(
            _claim,
            attempts=4,
            base_delay=0.1,
            on_retry=self.db.rollback,
        )

    async def renew_analysis_lease(self, content_id: int, fencing_token: str) -> bool:
        """Extend a claim only if this worker still owns its fencing token."""
        now = naive_utc_now()
        result = await self.db.execute(
            update(self.model)
            .where(self.model.id == content_id)
            .where(self.model.status == ContentStatus.ANALYZING)
            .where(self.model.analysis_claim_token == fencing_token)
            .values(
                updated_at=now,
                analysis_lease_expires_at=self._analysis_lease_expiry(now),
            )
        )
        await self.db.flush()
        return bool(result.rowcount)

    async def complete_analysis_claim(self, content_id: int, fencing_token: str) -> bool:
        """Finalize a result iff the worker still owns the current claim."""
        result = await self.db.execute(
            update(self.model)
            .where(self.model.id == content_id)
            .where(self.model.analysis_claim_token == fencing_token)
            .values(
                status=ContentStatus.ANALYZED,
                updated_at=naive_utc_now(),
                analysis_claim_token=None,
                analysis_lease_expires_at=None,
                analysis_next_retry_at=None,
            )
        )
        await self.db.flush()
        return bool(result.rowcount)

    async def fail_analysis_claim(
        self,
        content_id: int,
        fencing_token: str,
        *,
        next_retry_at: datetime | None,
    ) -> bool:
        """Mark failure iff the worker still owns the current claim."""
        result = await self.db.execute(
            update(self.model)
            .where(self.model.id == content_id)
            .where(self.model.analysis_claim_token == fencing_token)
            .values(
                status=ContentStatus.ERROR,
                # Keep the in-session ORM value timezone-aware; SQLAlchemy
                # normalizes it for SQLite on bind while Python callers can
                # safely compare it with the original UTC timestamp.
                updated_at=datetime.now(UTC),
                analysis_next_retry_at=next_retry_at,
                analysis_claim_token=None,
                analysis_lease_expires_at=None,
            )
        )
        await self.db.flush()
        return bool(result.rowcount)

    async def release_analysis_claim(self, content_id: int, fencing_token: str) -> bool:
        """Abandon a claim iff this worker still owns its fencing token.

        Durable job cancellation and timeout recovery must use this method
        rather than the legacy ID-only bulk release, otherwise a cancelled old
        worker could release work that a newer worker already reclaimed.
        """
        result = await self.db.execute(
            update(self.model)
            .where(self.model.id == content_id)
            .where(self.model.status == ContentStatus.ANALYZING)
            .where(self.model.analysis_claim_token == fencing_token)
            .values(
                status=ContentStatus.PENDING,
                updated_at=naive_utc_now(),
                analysis_claim_token=None,
                analysis_lease_expires_at=None,
            )
        )
        await self.db.flush()
        return bool(result.rowcount)

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
        stmt = update(self.model).where(self.model.id.in_(ids)).values(status=status, updated_at=naive_utc_now())
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
            .values(
                status=ContentStatus.PENDING,
                updated_at=naive_utc_now(),
                analysis_claim_token=None,
                analysis_lease_expires_at=None,
            )
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

    async def list_all_by_topic_id(self, topic_id: int) -> Sequence[ContentItem]:
        """返回指定 topic 下的全部内容项，按 crawled_at 倒序。

        供 /topics/{id} endpoint 使用，不分页（与历史行为等价）。
        """
        stmt = (
            select(self.model)
            .where(self.model.topic_id == topic_id)
            .order_by(self.model.crawled_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

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
        return dict(result.all())

    async def count_by_category(self) -> dict[str, int]:
        """Return a breakdown of item counts per category."""
        stmt = (
            select(self.model.category, func.count())
            .where(self.model.category.isnot(None))
            .group_by(self.model.category)
        )
        result = await self.db.execute(stmt)
        return dict(result.all())

    async def delete_old_pending(self, cutoff_days: int = 90) -> int:
        """删除超过指定天数的 pending 状态内容。返回删除数量。"""
        from sqlalchemy import delete as sa_delete

        cutoff = naive_utc_now() - timedelta(days=cutoff_days)
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
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id, public_only=public_only)
        count_stmt = apply_visibility(count_stmt, self.model, visible_user_id=visible_user_id, public_only=public_only)

        stmt = apply_filters(stmt, self.model, filters)
        count_stmt = apply_filters(count_stmt, self.model, filters)

        # Enhanced full-text-ish search across content + AI analysis fields (OR)
        # Content-level: title, summary, raw_content, tags (JSON), source_name, author
        # Analysis-level: ai_analyses.summary, tags, recommendation (via EXISTS, no row dup)
        if search_query:
            from app.models.analysis import AiAnalysis

            pattern = f"%{search_query}%"
            content_search = or_(
                self.model.title.ilike(pattern),
                self.model.summary.ilike(pattern),
                self.model.raw_content.ilike(pattern),
                cast(self.model.tags, Text).ilike(pattern),
                self.model.source_name.ilike(pattern),
                self.model.author.ilike(pattern),
            )
            analysis_search = exists(
                select(1)
                .select_from(AiAnalysis)
                .where(AiAnalysis.content_id == self.model.id)
                .where(
                    or_(
                        AiAnalysis.summary.ilike(pattern),
                        cast(AiAnalysis.tags, Text).ilike(pattern),
                        AiAnalysis.recommendation.ilike(pattern),
                    )
                )
            )
            search_clause = or_(content_search, analysis_search)
            stmt = stmt.where(search_clause)
            count_stmt = count_stmt.where(search_clause)

        # Exclude ignored item IDs / source types / time range
        stmt = apply_content_scope(
            stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )
        count_stmt = apply_content_scope(
            count_stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )

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
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id, public_only=public_only)
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

        cutoff = naive_utc_now() - timedelta(hours=hours)
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
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id)
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

        口径与 today-picks / DuckDB query_today_picks 对齐：剔除事件附属内容
        与已忽略内容 (``exclude_ids``)。
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
            .where(~self._accepted_event_member_exists())
        )
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id)
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

        count_stmt = apply_filters(count_stmt, self.model, filters)
        data_stmt = apply_filters(data_stmt, self.model, filters)

        count_stmt = apply_content_scope(
            count_stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )
        data_stmt = apply_content_scope(
            data_stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )
        count_stmt = apply_visibility(count_stmt, self.model, visible_user_id=visible_user_id, public_only=public_only)
        data_stmt = apply_visibility(data_stmt, self.model, visible_user_id=visible_user_id, public_only=public_only)

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

        stmt = apply_content_scope(
            stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id)

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

        stmt = apply_content_scope(
            stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id)

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

        stmt = apply_content_scope(
            stmt, self.model,
            exclude_ids=exclude_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
        )
        stmt = apply_visibility(stmt, self.model, visible_user_id=visible_user_id)

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

    async def count_hourly_by_title_keywords(
        self,
        keywords: list[str],
        cutoff: datetime,
    ) -> list[tuple[datetime, int]]:
        """按标题关键词做小时分桶计数，供 /daily-reports/sparkline 端点使用。

        - 关键词用 ILIKE 任意命中即算（OR 匹配），保证 1-2 个核心词也能查到曲线
        - 过滤：crawled_at >= cutoff, status='analyzed'，且不是事件附属内容
        - 分桶：date_trunc('hour', crawled_at)
        - 返回：[(hour_datetime, count), ...]

        与历史行为完全等价（原 api 层直写的查询下沉到此）。
        """
        if not keywords:
            return []
        pattern_clauses = [self.model.title.ilike(f"%{kw}%") for kw in keywords]
        stmt = (
            select(
                func.date_trunc("hour", self.model.crawled_at).label("ts"),
                func.count().label("cnt"),
            )
            .where(
                self.model.crawled_at >= cutoff,
                self.model.status == "analyzed",
                ~self._accepted_event_member_exists(),
                or_(*pattern_clauses),
            )
            .group_by("ts")
        )
        result = await self.db.execute(stmt)
        return [(row.ts, int(row.cnt)) for row in result.all()]

    async def get_id_by_id(self, content_id: int) -> int | None:
        """按主键查 id 字段，存在返回 id，不存在返回 None。

        供 feedback 端点验证 content 存在性使用（只查 id 列，比 get_by_id 轻量）。
        """
        result = await self.db.execute(select(self.model.id).where(self.model.id == content_id))
        return result.scalar_one_or_none()

    async def count_today_analyzed_visible(
        self,
        *,
        cutoff: datetime,
        visible_user_id: int | None = None,
        public_only: bool = False,
    ) -> int:
        """统计滚动 24h 内 analyzed 且非重复的可见内容数。

        供 /contents/today-count 端点使用，口径与首页「今日选题」一致：
        - status='analyzed'
        - crawled_at >= cutoff
        - 非 ACTIVE 事件的 accepted member
        - 可见性：public_only=True 时只计 owner_user_id IS NULL；
          visible_user_id 非 None 时计公共池+该用户私有。
        """
        stmt = (
            select(func.count(self.model.id))
            .where(
                self.model.status == "analyzed",
                self.model.crawled_at >= cutoff,
                ~self._accepted_event_member_exists(),
            )
        )
        for clause in self._visibility_clauses(visible_user_id, public_only):
            stmt = stmt.where(clause)
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_by_ids_ordered(
        self,
        content_ids: list[int],
    ) -> list[ContentItem]:
        """按给定 id 顺序返回 ContentItem 列表。

        供 /contents/favorites/list 端点按收藏顺序展示内容使用。
        - 输入空列表返回空列表
        - 不存在的 id 会被跳过（不抛错）
        - 返回顺序与 content_ids 顺序一致
        """
        if not content_ids:
            return []
        result = await self.db.execute(
            select(self.model).where(self.model.id.in_(content_ids))
        )
        by_id = {item.id: item for item in result.scalars().all()}
        return [by_id[cid] for cid in content_ids if cid in by_id]
