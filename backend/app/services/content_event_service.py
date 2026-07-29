"""Domain rules for canonical content events.

This service is the source-of-truth write boundary.  It never commits: API,
jobs, and scripts own their transaction so a multi-event operation remains
atomic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventRelationType,
    EventReviewStatus,
    EventStatus,
)
from app.repositories.content_event_repo import ContentEventRepository

AUTO_ACCEPT_CONFIDENCE = 0.85


class ContentEventNotFoundError(Exception):
    """The requested content, event, or member does not exist."""


class ContentEventConflictError(Exception):
    """The requested mutation conflicts with current event state."""


class ContentEventValidationError(Exception):
    """The mutation would violate an event-domain invariant."""


@dataclass(frozen=True)
class EventMemberInput:
    content_id: int
    relation_type: str = EventRelationType.DUPLICATE
    confidence: float = 1.0
    match_method: str = "manual"
    detector_version: str | None = None
    reason: str | None = None
    review_status: str | None = None


def effective_content_time(content: ContentItem) -> datetime:
    """Return a comparable UTC effective time with deterministic fallbacks."""

    value = content.published_at or content.crawled_at or content.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _content_order_key(content: ContentItem) -> tuple[datetime, int]:
    return effective_content_time(content), int(content.id)


def _validate_relation_type(value: str) -> str:
    try:
        return EventRelationType(value).value
    except ValueError as exc:
        raise ContentEventValidationError("relation_type must be duplicate, corroboration, or update") from exc


def _validate_confidence(value: float) -> float:
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise ContentEventValidationError("confidence must be between 0 and 1")
    return confidence


def _default_review_status(confidence: float) -> str:
    if confidence >= AUTO_ACCEPT_CONFIDENCE:
        return EventReviewStatus.AUTO
    return EventReviewStatus.PENDING


def _serialize_content(content: ContentItem) -> dict[str, Any]:
    return {
        "id": content.id,
        "title": content.title,
        "url": content.url,
        "source_name": content.source_name,
        "source_type": content.source_type,
        "platform": content.platform,
        "published_at": content.published_at,
        "crawled_at": content.crawled_at,
    }


class ContentEventService:
    """Create, mutate, review, and read canonical event groups."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        repository: ContentEventRepository | None = None,
    ):
        self.db = db
        self.repo = repository or ContentEventRepository(db)

    @staticmethod
    def _ensure_expected_version(
        group: ContentEventGroup,
        expected_version: int | None,
    ) -> None:
        if expected_version is not None and group.version != expected_version:
            raise ContentEventConflictError(
                f"event version conflict: expected {expected_version}, current {group.version}"
            )

    @staticmethod
    def _ensure_owner(content: ContentItem, owner_user_id: int | None) -> None:
        if content.owner_user_id != owner_user_id:
            raise ContentEventValidationError("all event contents must belong to the same owner scope")

    async def _require_group(
        self,
        event_id: int,
        *,
        for_update: bool = True,
    ) -> ContentEventGroup:
        group = await self.repo.get_group(event_id, for_update=for_update)
        if group is None:
            raise ContentEventNotFoundError(f"content event {event_id} not found")
        return group

    async def _require_content(
        self,
        content_id: int,
        *,
        for_update: bool = True,
    ) -> ContentItem:
        content = await self.repo.get_content(content_id, for_update=for_update)
        if content is None:
            raise ContentEventNotFoundError(f"content {content_id} not found")
        return content

    async def _ensure_unassigned(
        self,
        content_id: int,
        *,
        allowed_event_id: int | None = None,
    ) -> None:
        existing = await self.repo.find_group_for_content(
            content_id,
            for_update=True,
        )
        if existing is not None and existing.id != allowed_event_id:
            raise ContentEventConflictError(f"content {content_id} already belongs to event {existing.id}")

    async def _refresh_occurrence_range(
        self,
        group: ContentEventGroup,
    ) -> None:
        canonical = await self._require_content(group.canonical_content_id)
        members = await self.repo.list_member_rows(
            group.id,
            include_unaccepted=True,
        )
        times = [effective_content_time(canonical)]
        times.extend(effective_content_time(row.content) for row in members)
        group.first_occurrence_at = min(times)
        group.last_occurrence_at = max(times)

    async def _create_member_idempotent(self, **values) -> ContentEventMember:
        """Insert a member, tolerating a lost SELECT-then-INSERT race.

        ``SELECT ... FOR UPDATE`` is a no-op on SQLite, so two concurrent
        ``add_member`` calls for the same content can both miss the existing
        member and both reach ``create_member``. The ``uq_content_event_members_content``
        constraint then rejects the second insert. We isolate that insert in a
        savepoint (nested transaction) so a collision only rolls back the
        savepoint — the caller's outer transaction state is preserved — then we
        re-read the now-present member and return it, matching the no-op
        semantics the caller already uses for the unchanged branch.
        """
        try:
            async with self.db.begin_nested():
                return await self.repo.create_member(**values)
        except IntegrityError:
            existing = await self.repo.get_member(values["content_id"])
            if existing is not None:
                return existing
            raise

    async def create_event(
        self,
        content_ids: Sequence[int],
        *,
        owner_user_id: int | None,
        members: Mapping[int, EventMemberInput] | None = None,
        canonical_content_id: int | None = None,
        canonical_locked: bool = False,
        canonical_reason: str | None = None,
        actor_user_id: int | None = None,
        status: str = EventStatus.ACTIVE,
        classifier_version: str | None = None,
    ) -> ContentEventGroup:
        """Create one event and automatically choose the earliest canonical."""

        ids = list(dict.fromkeys(int(value) for value in content_ids))
        if not ids:
            raise ContentEventValidationError("an event requires at least one content")
        contents = await self.repo.get_contents(ids, for_update=True)
        if len(contents) != len(ids):
            found = {content.id for content in contents}
            missing = sorted(set(ids) - found)
            raise ContentEventNotFoundError(f"content not found: {missing}")
        assigned_ids = await self.repo.assigned_content_ids(ids)
        if assigned_ids:
            raise ContentEventConflictError(f"contents already belong to an event: {sorted(assigned_ids)}")
        for content in contents:
            self._ensure_owner(content, owner_user_id)

        member_inputs = members or {}
        extra_member_ids = sorted(set(member_inputs) - set(ids))
        if extra_member_ids:
            raise ContentEventValidationError(f"member inputs are outside content_ids: {extra_member_ids}")
        resolved_inputs: dict[
            int,
            tuple[EventMemberInput, float, EventReviewStatus, str],
        ] = {}
        for content in contents:
            candidate = member_inputs.get(
                content.id,
                EventMemberInput(content_id=content.id),
            )
            if candidate.content_id != content.id:
                raise ContentEventValidationError("member input key must match its content_id")
            confidence = _validate_confidence(candidate.confidence)
            try:
                review_status = EventReviewStatus(candidate.review_status or _default_review_status(confidence))
            except ValueError as exc:
                raise ContentEventValidationError("invalid review_status") from exc
            resolved_inputs[content.id] = (
                candidate,
                confidence,
                review_status,
                _validate_relation_type(candidate.relation_type),
            )

        accepted_ids = {
            content_id
            for content_id, (_, _, review_status, _) in resolved_inputs.items()
            if review_status in {EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED}
        }
        accepted_contents = [content for content in contents if content.id in accepted_ids]
        if not accepted_contents:
            raise ContentEventValidationError("an event requires at least one accepted canonical candidate")
        earliest = min(accepted_contents, key=_content_order_key)
        if canonical_content_id is None:
            canonical = earliest
        else:
            canonical = next(
                (item for item in contents if item.id == canonical_content_id),
                None,
            )
            if canonical is None:
                raise ContentEventValidationError("canonical content must be included in content_ids")
            if canonical.id not in accepted_ids:
                raise ContentEventValidationError("canonical content must be an accepted candidate")
            if not canonical_locked and canonical.id != earliest.id:
                raise ContentEventValidationError("an unlocked event must use the earliest content as canonical")

        try:
            event_status = EventStatus(status)
        except ValueError as exc:
            raise ContentEventValidationError("status must be shadow, active, or archived") from exc

        reason = canonical_reason or (
            "manual canonical selection" if canonical_locked else "automatic earliest accepted effective time"
        )
        group = await self.repo.create_group(
            owner_user_id=owner_user_id,
            canonical_content_id=canonical.id,
            canonical_policy="manual" if canonical_locked else "earliest",
            canonical_reason=reason,
            canonical_locked=canonical_locked,
            canonical_locked_by_user_id=actor_user_id if canonical_locked else None,
            canonical_locked_at=datetime.now(UTC) if canonical_locked else None,
            first_occurrence_at=min(effective_content_time(item) for item in contents),
            last_occurrence_at=max(effective_content_time(item) for item in contents),
            status=event_status,
            version=1,
            classifier_version=classifier_version,
        )

        for content in contents:
            if content.id == canonical.id:
                continue
            candidate, confidence, review_status, relation_type = resolved_inputs[content.id]
            await self.repo.create_member(
                event_group_id=group.id,
                content_id=content.id,
                relation_type=relation_type,
                confidence=confidence,
                match_method=candidate.match_method,
                detector_version=candidate.detector_version,
                reason=candidate.reason,
                review_status=review_status,
            )
        return group

    async def _switch_canonical(
        self,
        group: ContentEventGroup,
        new_canonical: ContentItem,
        selected_member: ContentEventMember,
        *,
        former_canonical_relation_type: str,
        reason: str,
        locked: bool,
        actor_user_id: int | None,
    ) -> None:
        old_canonical_id = group.canonical_content_id
        if new_canonical.id == old_canonical_id:
            return
        relation_type = _validate_relation_type(former_canonical_relation_type)
        await self.repo.delete_member(selected_member)
        group.canonical_content_id = new_canonical.id
        # Database guards require the selected member removal to become
        # visible before ownership moves to that content.
        await self.db.flush()
        await self.repo.create_member(
            event_group_id=group.id,
            content_id=old_canonical_id,
            relation_type=relation_type,
            confidence=selected_member.confidence,
            match_method=selected_member.match_method,
            detector_version=selected_member.detector_version,
            reason=selected_member.reason,
            review_status=(EventReviewStatus.CONFIRMED if locked else selected_member.review_status),
        )
        group.canonical_policy = "manual" if locked else "earliest"
        group.canonical_reason = reason
        group.canonical_locked = locked
        group.canonical_locked_by_user_id = actor_user_id if locked else None
        group.canonical_locked_at = datetime.now(UTC) if locked else None

    async def add_member(
        self,
        event_id: int,
        content_id: int,
        *,
        relation_type: str = EventRelationType.DUPLICATE,
        confidence: float = 1.0,
        match_method: str = "manual",
        detector_version: str | None = None,
        reason: str | None = None,
        review_status: str | None = None,
    ) -> ContentEventGroup:
        group = await self._require_group(event_id)
        content = await self._require_content(content_id)
        self._ensure_owner(content, group.owner_user_id)
        if content.id == group.canonical_content_id:
            raise ContentEventValidationError("canonical content cannot also be an event member")
        await self._ensure_unassigned(content.id, allowed_event_id=event_id)
        existing = await self.repo.get_member(content.id, for_update=True)
        confidence = _validate_confidence(confidence)
        relation_type = _validate_relation_type(relation_type)
        desired_review = EventReviewStatus(review_status or _default_review_status(confidence))
        if existing is not None:
            changed = any(
                (
                    existing.relation_type != relation_type,
                    existing.confidence != confidence,
                    existing.match_method != match_method,
                    existing.detector_version != detector_version,
                    existing.reason != reason,
                    existing.review_status != desired_review,
                )
            )
            if not changed:
                return group
            existing.relation_type = relation_type
            existing.confidence = confidence
            existing.match_method = match_method
            existing.detector_version = detector_version
            existing.reason = reason
            existing.review_status = desired_review
            member = existing
        else:
            member = await self._create_member_idempotent(
                event_group_id=event_id,
                content_id=content.id,
                relation_type=relation_type,
                confidence=confidence,
                match_method=match_method,
                detector_version=detector_version,
                reason=reason,
                review_status=desired_review,
            )

        if not group.canonical_locked and desired_review in {
            EventReviewStatus.AUTO,
            EventReviewStatus.CONFIRMED,
        }:
            canonical = await self._require_content(group.canonical_content_id)
            if _content_order_key(content) < _content_order_key(canonical):
                await self._switch_canonical(
                    group,
                    content,
                    member,
                    former_canonical_relation_type=relation_type,
                    reason="automatic earliest effective time",
                    locked=False,
                    actor_user_id=None,
                )
        await self._refresh_occurrence_range(group)
        group.version += 1
        await self.db.flush()
        return group

    async def move_member(
        self,
        content_id: int,
        target_event_id: int,
        *,
        relation_type: str = EventRelationType.DUPLICATE,
        confidence: float = 1.0,
        match_method: str = "manual-move",
        reason: str | None = None,
    ) -> ContentEventGroup:
        member = await self.repo.get_member(content_id, for_update=True)
        if member is None:
            raise ContentEventNotFoundError(f"content {content_id} is not an event member")
        if member.event_group_id == target_event_id:
            return await self.add_member(
                target_event_id,
                content_id,
                relation_type=relation_type,
                confidence=confidence,
                match_method=match_method,
                reason=reason,
            )
        source_group = await self._require_group(member.event_group_id)
        target_group = await self._require_group(target_event_id)
        content = await self._require_content(content_id)
        self._ensure_owner(content, target_group.owner_user_id)
        await self.repo.delete_member(member)
        source_group.version += 1
        await self._refresh_occurrence_range(source_group)
        return await self.add_member(
            target_group.id,
            content.id,
            relation_type=relation_type,
            confidence=confidence,
            match_method=match_method,
            reason=reason,
        )

    async def set_canonical(
        self,
        event_id: int,
        canonical_content_id: int,
        *,
        former_canonical_relation_type: str = EventRelationType.DUPLICATE,
        reason: str,
        expected_version: int,
        actor_user_id: int | None = None,
    ) -> ContentEventGroup:
        if not reason.strip():
            raise ContentEventValidationError("canonical reason is required")
        group = await self._require_group(event_id)
        self._ensure_expected_version(group, expected_version)
        if canonical_content_id == group.canonical_content_id:
            changed = (
                not group.canonical_locked
                or group.canonical_reason != reason
                or group.canonical_locked_by_user_id != actor_user_id
            )
            if changed:
                group.canonical_locked = True
                group.canonical_policy = "manual"
                group.canonical_reason = reason
                group.canonical_locked_by_user_id = actor_user_id
                group.canonical_locked_at = datetime.now(UTC)
                group.version += 1
                await self.db.flush()
            return group
        selected_member = await self.repo.get_member(
            canonical_content_id,
            for_update=True,
        )
        if (
            selected_member is None
            or selected_member.event_group_id != group.id
            or selected_member.review_status not in {EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED}
        ):
            raise ContentEventValidationError("new canonical must be an accepted member of this event")
        new_canonical = await self._require_content(canonical_content_id)
        await self._switch_canonical(
            group,
            new_canonical,
            selected_member,
            former_canonical_relation_type=former_canonical_relation_type,
            reason=reason,
            locked=True,
            actor_user_id=actor_user_id,
        )
        group.version += 1
        await self._refresh_occurrence_range(group)
        await self.db.flush()
        return group

    async def unlock_canonical(
        self,
        event_id: int,
        *,
        reason: str,
        expected_version: int,
    ) -> ContentEventGroup:
        if not reason.strip():
            raise ContentEventValidationError("unlock reason is required")
        group = await self._require_group(event_id)
        self._ensure_expected_version(group, expected_version)
        if not group.canonical_locked:
            return group
        canonical = await self._require_content(group.canonical_content_id)
        members = await self.repo.list_member_rows(
            group.id,
            include_unaccepted=True,
            for_update=True,
        )
        eligible = [
            row for row in members if row.member.review_status in {EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED}
        ]
        earliest = min(
            [canonical, *(row.content for row in eligible)],
            key=_content_order_key,
        )
        if earliest.id != canonical.id:
            selected = next(row.member for row in eligible if row.content.id == earliest.id)
            await self._switch_canonical(
                group,
                earliest,
                selected,
                former_canonical_relation_type=selected.relation_type,
                reason=f"automatic earliest after unlock: {reason}",
                locked=False,
                actor_user_id=None,
            )
        else:
            group.canonical_locked = False
            group.canonical_policy = "earliest"
            group.canonical_reason = f"automatic earliest after unlock: {reason}"
            group.canonical_locked_by_user_id = None
            group.canonical_locked_at = None
        group.version += 1
        await self._refresh_occurrence_range(group)
        await self.db.flush()
        return group

    async def review_relation(
        self,
        member_id: int,
        *,
        decision: str,
        relation_type: str | None,
        reason: str | None,
        expected_version: int,
        reviewer_user_id: int | None = None,
    ) -> ContentEventGroup:
        del reviewer_user_id  # actor auditing is added with the dedicated audit table.
        member = await self.repo.get_member_by_id(member_id, for_update=True)
        if member is None:
            raise ContentEventNotFoundError(f"event member {member_id} not found")
        group = await self._require_group(member.event_group_id)
        self._ensure_expected_version(group, expected_version)
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"accept", "reject"}:
            raise ContentEventValidationError("decision must be accept or reject")
        if normalized_decision == "accept":
            if relation_type is None:
                raise ContentEventValidationError("relation_type is required when accepting")
            next_relation = _validate_relation_type(relation_type)
            next_status = EventReviewStatus.CONFIRMED
        else:
            next_relation = member.relation_type
            next_status = EventReviewStatus.REJECTED
        changed = (
            member.relation_type != next_relation or member.review_status != next_status or member.reason != reason
        )
        if not changed:
            return group
        member.relation_type = next_relation
        member.review_status = next_status
        member.reason = reason
        if normalized_decision == "accept" and not group.canonical_locked:
            content = await self._require_content(member.content_id)
            canonical = await self._require_content(group.canonical_content_id)
            if _content_order_key(content) < _content_order_key(canonical):
                await self._switch_canonical(
                    group,
                    content,
                    member,
                    former_canonical_relation_type=next_relation,
                    reason="automatic earliest after relation review",
                    locked=False,
                    actor_user_id=None,
                )
        group.version += 1
        await self._refresh_occurrence_range(group)
        await self.db.flush()
        return group

    async def get_event_detail(
        self,
        content_id: int,
        *,
        visible_user_id: int | None,
        member_limit: int = 20,
        member_offset: int = 0,
        include_shadow: bool = False,
    ) -> dict[str, Any] | None:
        content = await self.repo.get_content(content_id)
        if content is None or (content.owner_user_id is not None and content.owner_user_id != visible_user_id):
            raise ContentEventNotFoundError(f"content {content_id} not found")
        group = await self.repo.resolve_visible_group(
            content_id,
            visible_user_id=visible_user_id,
            include_shadow=include_shadow,
        )
        if group is None:
            return None
        bundle = await self.repo.get_event_bundle(
            group,
            member_offset=member_offset,
            member_limit=member_limit,
            include_unaccepted=include_shadow,
        )
        if bundle is None:
            return None
        serialized_members = [
            {
                **_serialize_content(row.content),
                "id": row.member.id,
                "content_id": row.content.id,
                "relation_type": row.member.relation_type,
                "confidence": row.member.confidence,
                "review_status": row.member.review_status,
            }
            for row in bundle.members
        ]
        return {
            "id": group.id,
            "canonical_id": group.canonical_content_id,
            "owner_user_id": group.owner_user_id,
            "status": group.status,
            "version": group.version,
            "canonical_locked": group.canonical_locked,
            "canonical_reason": group.canonical_reason,
            "canonical": _serialize_content(bundle.canonical),
            "member_count": bundle.member_count,
            "source_count": bundle.source_count,
            "has_more": member_offset + len(bundle.members) < bundle.member_count,
            "members": serialized_members,
        }

    async def list_reviews(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        review_status: str | None = None,
    ) -> dict[str, Any]:
        if review_status is not None:
            try:
                review_status = EventReviewStatus(review_status).value
            except ValueError as exc:
                raise ContentEventValidationError("invalid review_status") from exc
        rows, total = await self.repo.list_reviews(
            page=page,
            page_size=page_size,
            review_status=review_status,
        )
        return {
            "items": [
                {
                    "id": row.member.id,
                    "event_id": row.group.id,
                    "event_version": row.group.version,
                    "content_id": row.content.id,
                    "title": row.content.title,
                    "source_name": row.content.source_name,
                    "source_type": row.content.source_type,
                    "relation_type": row.member.relation_type,
                    "confidence": row.member.confidence,
                    "match_method": row.member.match_method,
                    "detector_version": row.member.detector_version,
                    "review_status": row.member.review_status,
                    "reason": row.member.reason,
                    "matched_at": row.member.matched_at,
                    "updated_at": row.member.updated_at,
                }
                for row in rows
            ],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, page_size),
        }
