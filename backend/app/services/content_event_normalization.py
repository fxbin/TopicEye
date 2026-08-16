"""Bounded, leased incremental normalization of content into canonical events.

The claim is committed through a short metadata session before any LLM call.
Event mutations, the final audit record, and lease release are then flushed in
the caller's transaction, so the API/scheduler commit makes them visible
atomically. A failed caller commit therefore cannot leave a false SUCCESS run.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.content import ContentItem
from app.models.content_event import EventRelationType, EventReviewStatus
from app.models.content_event_run import (
    ContentEventNormalizationRun,
    EventNormalizationMode,
    EventNormalizationRunStatus,
)
from app.repositories.content_event_normalization_repo import (
    ContentEventNormalizationRepository,
)
from app.services.content_event_service import (
    ContentEventConflictError,
    ContentEventService,
)
from app.services.llm import call_llm_json

CLASSIFIER_VERSION = "event-normalizer-v1"
_VALID_RELATIONS = {
    EventRelationType.DUPLICATE.value,
    EventRelationType.CORROBORATION.value,
    EventRelationType.UPDATE.value,
}
_UPDATE_MARKERS = frozenset(
    {
        "更新",
        "进展",
        "后续",
        "升级",
        "新增",
        "回应",
        "update",
        "updated",
        "followup",
        "follow-up",
    }
)
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")


@dataclass(frozen=True)
class _Limits:
    max_items: int
    max_candidates: int
    max_llm_calls: int
    concurrency: int
    lease_seconds: int
    lookback_days: int
    auto_accept_confidence: float
    audit_max_bytes: int
    routing_group: str


@dataclass(frozen=True)
class _Claim:
    run_id: int
    scope_key: str
    lease_token: str
    fencing_token: int
    mode: str
    replay_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ContentSnapshot:
    id: int
    title: str
    summary: str
    source_id: int | None
    source_name: str | None
    platform: str | None
    tags: Any
    owner_user_id: int | None
    published_at: datetime | None
    crawled_at: datetime
    created_at: datetime


@dataclass
class _Candidate:
    event_id: int | None
    canonical: _ContentSnapshot
    score: float = 0.0
    same_publisher: bool = False


@dataclass
class _Prediction:
    content_id: int
    decision: str
    relation_type: str | None
    confidence: float
    match_method: str
    reason: str
    target_event_id: int | None = None
    target_content_id: int | None = None
    review_status: str | None = None
    llm_used: bool = False
    llm_failed: bool = False
    llm_error: str | None = None

    def audit_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "decision": self.decision,
            "relation_type": self.relation_type,
            "confidence": round(self.confidence, 4),
            "match_method": self.match_method,
            "reason": self.reason[:500],
            "target_event_id": self.target_event_id,
            "target_content_id": self.target_content_id,
            "review_status": self.review_status,
            "llm_used": self.llm_used,
            "llm_failed": self.llm_failed,
            "llm_error": self.llm_error,
        }


def _bounded_int(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(1, value), maximum)


def _limits() -> _Limits:
    try:
        confidence = float(getattr(settings, "EVENT_NORMALIZATION_AUTO_ACCEPT_CONFIDENCE", 0.88))
    except (TypeError, ValueError):
        confidence = 0.88
    return _Limits(
        max_items=_bounded_int("EVENT_NORMALIZATION_MAX_ITEMS", 50, maximum=500),
        max_candidates=_bounded_int(
            "EVENT_NORMALIZATION_MAX_CANDIDATES",
            8,
            maximum=50,
        ),
        max_llm_calls=_bounded_int(
            "EVENT_NORMALIZATION_MAX_BOUNDARY_LLM_CALLS",
            10,
            maximum=100,
        ),
        concurrency=_bounded_int(
            "EVENT_NORMALIZATION_WORKER_CONCURRENCY",
            2,
            maximum=16,
        ),
        lease_seconds=_bounded_int(
            "EVENT_NORMALIZATION_LEASE_SECONDS",
            900,
            maximum=7200,
        ),
        lookback_days=_bounded_int(
            "EVENT_NORMALIZATION_LOOKBACK_DAYS",
            180,
            maximum=3650,
        ),
        auto_accept_confidence=min(max(confidence, 0.5), 1.0),
        audit_max_bytes=max(
            2,
            _bounded_int(
                "EVENT_NORMALIZATION_PREDICTION_AUDIT_MAX_BYTES",
                65_536,
                maximum=1_000_000,
            ),
        ),
        routing_group=(
            str(
                getattr(
                    settings,
                    "EVENT_NORMALIZATION_ROUTING_GROUP",
                    "event_normalization",
                )
            ).strip()
            or "event_normalization"
        )[:100],
    )


def _scope_key(owner_user_id: int | None) -> str:
    return "public" if owner_user_id is None else f"user:{int(owner_user_id)}"


def _snapshot(content: ContentItem) -> _ContentSnapshot:
    return _ContentSnapshot(
        id=int(content.id),
        title=content.title or "",
        summary=content.summary or "",
        source_id=content.source_id,
        source_name=content.source_name,
        platform=content.platform,
        tags=content.tags,
        owner_user_id=content.owner_user_id,
        published_at=content.published_at,
        crawled_at=content.crawled_at,
        created_at=content.created_at,
    )


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _title_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = set(_ASCII_TOKEN_RE.findall(normalized))
    for segment in _CJK_RE.findall(normalized):
        if len(segment) == 1:
            tokens.add(segment)
        else:
            tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return tokens


def _tag_tokens(value: Any) -> set[str]:
    if isinstance(value, dict):
        raw_values = [*value.keys(), *value.values()]
    elif isinstance(value, list | tuple | set):
        raw_values = list(value)
    elif isinstance(value, str):
        raw_values = [value]
    else:
        return set()
    tokens: set[str] = set()
    for raw in raw_values:
        if isinstance(raw, str):
            tokens.update(_title_tokens(raw))
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _publisher_key(content: _ContentSnapshot) -> tuple[str, str]:
    if content.source_id is not None:
        return "source", str(content.source_id)
    name = _normalize_title(content.source_name or "")
    if name:
        return "name", name
    return "platform", _normalize_title(content.platform or "")


def _similarity(left: _ContentSnapshot, right: _ContentSnapshot) -> float:
    left_normalized = _normalize_title(left.title)
    right_normalized = _normalize_title(right.title)
    if left_normalized and left_normalized == right_normalized:
        return 1.0
    title_score = _jaccard(_title_tokens(left.title), _title_tokens(right.title))
    tag_score = _jaccard(_tag_tokens(left.tags), _tag_tokens(right.tags))
    return min(1.0, title_score * 0.9 + tag_score * 0.1)


def _looks_like_update(content: _ContentSnapshot) -> bool:
    normalized = unicodedata.normalize("NFKC", content.title).casefold()
    return any(marker in normalized for marker in _UPDATE_MARKERS)


def _best_candidates(
    content: _ContentSnapshot,
    candidates: list[_Candidate],
    *,
    limit: int,
) -> list[_Candidate]:
    scored = [
        _Candidate(
            event_id=candidate.event_id,
            canonical=candidate.canonical,
            score=_similarity(content, candidate.canonical),
            same_publisher=(_publisher_key(content) == _publisher_key(candidate.canonical)),
        )
        for candidate in candidates
        if candidate.canonical.id != content.id
    ]
    scored.sort(
        key=lambda candidate: (
            candidate.score,
            candidate.canonical.created_at,
            candidate.canonical.id,
        ),
        reverse=True,
    )
    return scored[:limit]


def _local_prediction(
    content: _ContentSnapshot,
    candidates: list[_Candidate],
) -> tuple[_Prediction | None, _Candidate | None]:
    if not candidates or candidates[0].score < 0.62:
        return (
            _Prediction(
                content_id=content.id,
                decision="standalone",
                relation_type=None,
                confidence=1.0,
                match_method="local-no-candidate",
                reason="no sufficiently similar canonical in the bounded recall set",
            ),
            None,
        )

    best = candidates[0]
    exact_title = _normalize_title(content.title) == _normalize_title(best.canonical.title)
    if exact_title and best.same_publisher:
        return (
            _Prediction(
                content_id=content.id,
                decision=EventRelationType.DUPLICATE.value,
                relation_type=EventRelationType.DUPLICATE.value,
                confidence=0.99,
                match_method="local-exact-title-publisher",
                reason="normalized titles and publisher family are identical",
                target_event_id=best.event_id,
                target_content_id=best.canonical.id,
                review_status=EventReviewStatus.AUTO.value,
            ),
            best,
        )

    if best.same_publisher and best.score >= 0.92:
        relation = EventRelationType.UPDATE.value if _looks_like_update(content) else EventRelationType.DUPLICATE.value
        return (
            _Prediction(
                content_id=content.id,
                decision=relation,
                relation_type=relation,
                confidence=0.94 if relation == EventRelationType.DUPLICATE else 0.9,
                match_method="local-title-similarity",
                reason="high title/tag similarity within the same publisher family",
                target_event_id=best.event_id,
                target_content_id=best.canonical.id,
                review_status=EventReviewStatus.AUTO.value,
            ),
            best,
        )

    # Cross-publisher title equality is deliberately not treated as independent
    # corroboration. It is a boundary sample until facts are checked by the LLM
    # or a reviewer.
    if (
        exact_title
        or best.score >= 0.72
        or (best.same_publisher and _looks_like_update(content) and best.score >= 0.62)
    ):
        return None, best

    return (
        _Prediction(
            content_id=content.id,
            decision="standalone",
            relation_type=None,
            confidence=0.9,
            match_method="local-low-similarity",
            reason="candidate similarity is below the event-membership boundary",
        ),
        None,
    )


async def _classify_boundary(
    content: _ContentSnapshot,
    candidate: _Candidate,
    *,
    limits: _Limits,
    semaphore: asyncio.Semaphore,
) -> _Prediction:
    messages = [
        {
            "role": "system",
            "content": (
                "Classify whether two headlines describe the same real-world event. "
                "Return JSON with decision (duplicate|corroboration|update|standalone|pending), "
                "confidence 0..1, and a concise reason. Different publishers alone do not "
                "prove independent corroboration. Never return related."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "incoming": {
                        "title": content.title,
                        "summary": content.summary[:1000],
                        "source": content.source_name,
                        "published_at": (content.published_at.isoformat() if content.published_at else None),
                    },
                    "canonical": {
                        "title": candidate.canonical.title,
                        "summary": candidate.canonical.summary[:1000],
                        "source": candidate.canonical.source_name,
                        "published_at": (
                            candidate.canonical.published_at.isoformat() if candidate.canonical.published_at else None
                        ),
                    },
                    "local_similarity": round(candidate.score, 4),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        async with semaphore:
            result = await call_llm_json(
                messages,
                temperature=0.0,
                max_tokens=300,
                scene="event_normalization",
                routing_group=limits.routing_group,
            )
        if not isinstance(result, dict):
            raise ValueError("LLM result must be an object")
        decision = str(result.get("decision", "")).strip().lower()
        if decision == "related":
            decision = "pending"
        if decision not in {*_VALID_RELATIONS, "standalone", "pending"}:
            raise ValueError("invalid event decision")
        confidence = float(result.get("confidence", 0))
        if not math.isfinite(confidence):
            raise ValueError("confidence must be finite")
        confidence = min(max(confidence, 0.0), 1.0)
        reason = str(result.get("reason", "")).strip()[:500]
        if not reason:
            raise ValueError("reason is required")

        if decision == "standalone":
            return _Prediction(
                content_id=content.id,
                decision=decision,
                relation_type=None,
                confidence=confidence,
                match_method="llm-boundary",
                reason=reason,
                llm_used=True,
            )
        relation = decision if decision in _VALID_RELATIONS else EventRelationType.DUPLICATE.value
        review_status = (
            EventReviewStatus.AUTO.value
            if decision in _VALID_RELATIONS and confidence >= limits.auto_accept_confidence
            else EventReviewStatus.PENDING.value
        )
        return _Prediction(
            content_id=content.id,
            decision=decision,
            relation_type=relation,
            confidence=confidence,
            match_method="llm-boundary",
            reason=reason,
            target_event_id=candidate.event_id,
            target_content_id=candidate.canonical.id,
            review_status=review_status,
            llm_used=True,
        )
    except Exception as exc:
        return _Prediction(
            content_id=content.id,
            decision="pending",
            relation_type=EventRelationType.DUPLICATE.value,
            confidence=min(candidate.score, limits.auto_accept_confidence - 0.01),
            match_method="llm-boundary-fallback",
            reason=f"boundary classification unavailable: {type(exc).__name__}",
            target_event_id=candidate.event_id,
            target_content_id=candidate.canonical.id,
            review_status=EventReviewStatus.PENDING.value,
            llm_used=True,
            llm_failed=True,
            llm_error=f"{type(exc).__name__}: {str(exc)}"[:500],
        )


def _truncate_predictions(
    predictions: list[dict[str, Any]],
    *,
    max_bytes: int,
) -> list[dict[str, Any]]:
    # SQLAlchemy's default JSON serializer is ``json.dumps``. The guard must
    # use that same ensure_ascii/separator behavior because non-ASCII text
    # expands during persistence.
    effective_max_bytes = max(2, int(max_bytes))
    kept = list(predictions)
    omitted = 0
    while kept:
        marker = [{"truncated": True, "omitted_count": omitted}] if omitted else []
        encoded = json.dumps([*kept, *marker]).encode("utf-8")
        if len(encoded) <= effective_max_bytes:
            return [*kept, *marker]
        kept.pop()
        omitted += 1
    marker = [{"truncated": True, "omitted_count": len(predictions)}]
    if len(json.dumps(marker).encode("utf-8")) <= effective_max_bytes:
        return marker
    return []


def _run_result(run: ContentEventNormalizationRun) -> dict[str, Any]:
    result = dict(run.result or {})
    result["run_id"] = run.id
    result["status"] = run.status.value if hasattr(run.status, "value") else run.status
    result["replayed"] = True
    return result


async def _claim_run(
    *,
    owner_user_id: int | None,
    idempotency_key: str,
    mode: str,
    hours: int,
    limits: _Limits,
) -> _Claim:
    scope_key = _scope_key(owner_user_id)
    now = datetime.now(UTC)
    lease_token = uuid.uuid4().hex
    expires_at = now + timedelta(seconds=limits.lease_seconds)

    try:
        async with async_session() as metadata_db:
            repo = ContentEventNormalizationRepository(metadata_db)
            await repo.begin_claim_transaction()
            existing = await repo.get_run(
                scope_key=scope_key,
                idempotency_key=idempotency_key,
                for_update=True,
            )
            if existing is not None:
                existing_mode = existing.mode.value if hasattr(existing.mode, "value") else str(existing.mode)
                if existing_mode != mode or existing.window_hours != hours:
                    await metadata_db.rollback()
                    raise ContentEventConflictError("Idempotency-Key was already used with different mode or hours")
            if existing is not None and existing.status == EventNormalizationRunStatus.SUCCEEDED:
                result = _run_result(existing)
                run_id = int(existing.id)
                existing_lease_token = existing.lease_token
                existing_fencing_token = int(existing.fencing_token)
                await metadata_db.rollback()
                return _Claim(
                    run_id=run_id,
                    scope_key=scope_key,
                    lease_token=existing_lease_token,
                    fencing_token=existing_fencing_token,
                    mode=mode,
                    replay_result=result,
                )

            fencing_token = await repo.claim_lease(
                scope_key=scope_key,
                lease_token=lease_token,
                now=now,
                expires_at=expires_at,
            )
            if fencing_token is None:
                await metadata_db.rollback()
                raise ContentEventConflictError(f"normalization lease is active for {scope_key}")

            if existing is None:
                run = await repo.create_run(
                    scope_key=scope_key,
                    owner_user_id=owner_user_id,
                    idempotency_key=idempotency_key,
                    mode=mode,
                    status=EventNormalizationRunStatus.RUNNING,
                    fencing_token=fencing_token,
                    lease_token=lease_token,
                    window_hours=hours,
                    classifier_version=CLASSIFIER_VERSION,
                    started_at=now,
                )
            else:
                await repo.reclaim_run(
                    existing,
                    mode=mode,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                    started_at=now,
                    window_hours=hours,
                )
                run = existing
            await metadata_db.commit()
            return _Claim(
                run_id=run.id,
                scope_key=scope_key,
                lease_token=lease_token,
                fencing_token=fencing_token,
                mode=mode,
            )
    except IntegrityError as exc:
        raise ContentEventConflictError(f"normalization lease is active for {scope_key}") from exc


async def _renew_claim(claim: _Claim, limits: _Limits) -> None:
    now = datetime.now(UTC)
    async with async_session() as metadata_db:
        repo = ContentEventNormalizationRepository(metadata_db)
        renewed = await repo.renew_lease(
            scope_key=claim.scope_key,
            lease_token=claim.lease_token,
            fencing_token=claim.fencing_token,
            expires_at=now + timedelta(seconds=limits.lease_seconds),
            now=now,
        )
        if not renewed:
            await metadata_db.rollback()
            raise ContentEventConflictError("normalization fencing token is stale")
        await metadata_db.commit()


async def _fail_claim(claim: _Claim, error: BaseException) -> None:
    now = datetime.now(UTC)
    async with async_session() as metadata_db:
        repo = ContentEventNormalizationRepository(metadata_db)
        run = await repo.get_run_by_id(claim.run_id, for_update=True)
        if run is None or run.lease_token != claim.lease_token or run.fencing_token != claim.fencing_token:
            await metadata_db.rollback()
            return
        current = await repo.lock_current_lease(
            scope_key=claim.scope_key,
            lease_token=claim.lease_token,
            fencing_token=claim.fencing_token,
            now=now,
        )
        if not current:
            await metadata_db.rollback()
            return
        run.status = EventNormalizationRunStatus.FAILED
        run.error_message = f"{type(error).__name__}: {str(error)}"[:4000]
        run.finished_at = now
        await repo.release_lease(
            scope_key=claim.scope_key,
            lease_token=claim.lease_token,
            fencing_token=claim.fencing_token,
            now=now,
        )
        await metadata_db.commit()


async def _finish_in_business_transaction(
    db: AsyncSession,
    *,
    claim: _Claim,
    result: dict[str, Any],
    predictions: list[dict[str, Any]],
    model_routes: list[dict[str, Any]],
    started_monotonic: float,
    limits: _Limits,
) -> None:
    repo = ContentEventNormalizationRepository(db)
    now = datetime.now(UTC)
    run = await repo.get_run_by_id(claim.run_id, for_update=True)
    if run is None or run.lease_token != claim.lease_token or run.fencing_token != claim.fencing_token:
        raise ContentEventConflictError("normalization fencing token is stale")
    current = await repo.lock_current_lease(
        scope_key=claim.scope_key,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        now=now,
    )
    if not current:
        raise ContentEventConflictError("normalization fencing token is stale")

    run.status = EventNormalizationRunStatus.SUCCEEDED
    run.scanned_count = int(result["scanned"])
    run.matched_count = int(result["matched"])
    run.pending_count = int(result["pending"])
    run.standalone_count = int(result["standalone"])
    run.created_event_count = int(result["created_events"])
    run.created_member_count = int(result["created_members"])
    run.llm_call_count = int(result["llm_calls"])
    run.latency_ms = int((time.monotonic() - started_monotonic) * 1000)
    run.predictions = _truncate_predictions(
        predictions,
        max_bytes=limits.audit_max_bytes,
    )
    run.model_routes = model_routes[: limits.max_llm_calls]
    run.result = result
    run.error_message = None
    run.finished_at = now
    released = await repo.release_lease(
        scope_key=claim.scope_key,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        now=now,
    )
    if not released:
        raise ContentEventConflictError("normalization fencing token is stale")
    await db.flush()


async def normalize_recent_events_with_lease(
    db: AsyncSession,
    *,
    hours: int = 24,
    mode: str = EventNormalizationMode.SHADOW,
    owner_user_id: int | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    """Run one bounded normalization pass with durable idempotency and fencing."""

    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "off":
        return {
            "status": "off",
            "replayed": False,
            "scanned": 0,
            "matched": 0,
            "pending": 0,
            "standalone": 0,
            "created_events": 0,
            "created_members": 0,
            "llm_calls": 0,
        }
    if normalized_mode not in {
        EventNormalizationMode.SHADOW.value,
        EventNormalizationMode.WRITE.value,
    }:
        raise ValueError("mode must be off, shadow, or write")
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 200:
        raise ValueError("idempotency_key must contain 1..200 characters")
    bounded_hours = min(max(int(hours), 1), 720)
    limits = _limits()
    started_monotonic = time.monotonic()
    claim = await _claim_run(
        owner_user_id=owner_user_id,
        idempotency_key=normalized_key,
        mode=normalized_mode,
        hours=bounded_hours,
        limits=limits,
    )
    if claim.replay_result is not None:
        return claim.replay_result

    model_routes: list[dict[str, Any]] = []
    llm_calls = 0
    created_events = 0
    created_members = 0
    try:
        now = datetime.now(UTC)
        read_repo = ContentEventNormalizationRepository(db)
        recent_rows = await read_repo.list_recent_unassigned(
            owner_user_id=owner_user_id,
            since=now - timedelta(hours=bounded_hours),
            limit=limits.max_items,
        )
        history_limit = min(
            limits.max_items * limits.max_candidates * 4,
            4000,
        )
        historical_rows = await read_repo.list_historical_canonicals(
            owner_user_id=owner_user_id,
            since=now - timedelta(days=limits.lookback_days),
            limit=max(limits.max_candidates, history_limit),
        )
        recent = [_snapshot(content) for content in recent_rows]
        candidates = [
            _Candidate(
                event_id=row.event_group.id,
                canonical=_snapshot(row.content),
            )
            for row in historical_rows
        ]
        # Do not hold a read transaction while waiting on the model pool.
        await db.rollback()

        semaphore = asyncio.Semaphore(limits.concurrency)
        write_enabled = normalized_mode == EventNormalizationMode.WRITE.value

        predictions_by_index: dict[int, _Prediction] = {}
        boundary_batch: list[tuple[int, _ContentSnapshot, _Candidate]] = []

        async def flush_boundary_batch() -> None:
            if not boundary_batch:
                return
            batch = list(boundary_batch)
            boundary_batch.clear()
            classified = await asyncio.gather(
                *[
                    _classify_boundary(
                        content,
                        boundary,
                        limits=limits,
                        semaphore=semaphore,
                    )
                    for _index, content, boundary in batch
                ]
            )
            for (index, content, _boundary), prediction in zip(
                batch,
                classified,
                strict=True,
            ):
                predictions_by_index[index] = prediction
                model_routes.append(
                    {
                        "scene": "event_normalization",
                        "routing_group": limits.routing_group,
                        "model": None,
                        "status": ("failed" if prediction.llm_failed else "completed"),
                        "error": prediction.llm_error,
                    }
                )
                if prediction.decision == "standalone":
                    prediction.target_content_id = content.id
                    candidates.append(_Candidate(event_id=None, canonical=content))

        for index, content in enumerate(recent):
            ranked = _best_candidates(
                content,
                candidates,
                limit=limits.max_candidates,
            )
            prediction, boundary = _local_prediction(content, ranked)
            if prediction is None and boundary is not None:
                if llm_calls < limits.max_llm_calls:
                    llm_calls += 1
                    boundary_batch.append((index, content, boundary))
                    if len(boundary_batch) >= limits.concurrency:
                        await flush_boundary_batch()
                    continue
                else:
                    prediction = _Prediction(
                        content_id=content.id,
                        decision="pending",
                        relation_type=EventRelationType.DUPLICATE.value,
                        confidence=min(
                            boundary.score,
                            limits.auto_accept_confidence - 0.01,
                        ),
                        match_method="llm-cap-fallback",
                        reason="boundary sample deferred because the per-run LLM cap was reached",
                        target_event_id=boundary.event_id,
                        target_content_id=boundary.canonical.id,
                        review_status=EventReviewStatus.PENDING.value,
                    )

            assert prediction is not None
            if prediction.decision == "standalone":
                prediction.target_content_id = content.id
                # A provisional canonical participates in later items from this
                # run before any business write begins.
                candidates.append(
                    _Candidate(
                        event_id=None,
                        canonical=content,
                    )
                )
            predictions_by_index[index] = prediction

        await flush_boundary_batch()
        predictions = [predictions_by_index[index] for index in range(len(recent))]
        standalone = sum(prediction.decision == "standalone" for prediction in predictions)
        pending = sum(
            prediction.decision != "standalone" and prediction.review_status == EventReviewStatus.PENDING.value
            for prediction in predictions
        )
        matched = len(predictions) - standalone - pending

        # All LLM work is complete. Renew the committed metadata lease before
        # opening the short business write transaction.
        await _renew_claim(claim, limits)
        if write_enabled:
            event_service = ContentEventService(db)
            provisional_events: dict[int, int] = {}
            for prediction in predictions:
                if prediction.decision == "standalone":
                    group = await event_service.create_event(
                        [prediction.content_id],
                        owner_user_id=owner_user_id,
                        classifier_version=CLASSIFIER_VERSION,
                    )
                    provisional_events[prediction.content_id] = group.id
                    prediction.target_event_id = group.id
                    created_events += 1
                    continue

                target_event_id = prediction.target_event_id
                if target_event_id is None and prediction.target_content_id is not None:
                    target_event_id = provisional_events.get(prediction.target_content_id)
                if target_event_id is not None:
                    await event_service.add_member(
                        target_event_id,
                        prediction.content_id,
                        relation_type=(prediction.relation_type or EventRelationType.DUPLICATE.value),
                        confidence=prediction.confidence,
                        match_method=prediction.match_method,
                        detector_version=CLASSIFIER_VERSION,
                        reason=prediction.reason,
                        review_status=(prediction.review_status or EventReviewStatus.PENDING.value),
                    )
                    prediction.target_event_id = target_event_id
                    created_members += 1

        result = {
            "run_id": claim.run_id,
            "status": EventNormalizationRunStatus.SUCCEEDED.value,
            "mode": normalized_mode,
            "scope": claim.scope_key,
            "replayed": False,
            "scanned": len(recent),
            "matched": matched,
            "pending": pending,
            "standalone": standalone,
            "created_events": created_events,
            "created_members": created_members,
            "llm_calls": llm_calls,
        }
        await _finish_in_business_transaction(
            db,
            claim=claim,
            result=result,
            predictions=[prediction.audit_dict() for prediction in predictions],
            model_routes=model_routes,
            started_monotonic=started_monotonic,
            limits=limits,
        )
        return result
    except Exception as exc:
        await db.rollback()
        await _fail_claim(claim, exc)
        raise
