"""Evidence effect-stat cohorts and profile coverage regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.content import ContentItem
from app.models.content_evidence import ContentEvidenceMark
from app.models.evidence_interaction import EvidenceInteraction
from app.models.source import Source
from app.models.source_evidence_profile import SourceEvidenceProfile
from app.repositories.evidence_repo import EvidenceRepository


def _content(content_id: int, *, created_at: datetime) -> ContentItem:
    return ContentItem(
        id=content_id,
        title=f"content-{content_id}",
        url=f"https://example.test/content-{content_id}",
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_effect_stats_uses_one_content_cohort_and_includes_none_marks(db):
    now = datetime.now(UTC)
    db.add_all(
        [
            _content(1, created_at=now),  # marked
            _content(2, created_at=now),  # explicit "none" mark -> unmarked
            _content(3, created_at=now),  # no mark -> unmarked
            _content(4, created_at=now - timedelta(days=8)),  # outside cohort
        ]
    )
    db.add_all(
        [
            ContentEvidenceMark(content_id=1, owner_user_id=None, cross_source_level="cross_source"),
            ContentEvidenceMark(content_id=2, owner_user_id=None, cross_source_level="none"),
            ContentEvidenceMark(content_id=4, owner_user_id=None, cross_source_level="cross_source"),
            EvidenceInteraction(content_id=1, interaction_type="click", created_at=now),
            EvidenceInteraction(content_id=2, interaction_type="click", created_at=now),
            EvidenceInteraction(content_id=3, interaction_type="favorite", created_at=now),
            EvidenceInteraction(content_id=4, interaction_type="click", created_at=now),
        ]
    )
    await db.flush()

    stats = await EvidenceRepository(db).get_effect_stats(days=7)

    assert stats["marked"] == {
        "total_content": 1,
        "interactions_by_type": {"click": 1},
        "total_interactions": 1,
        "interaction_rate": 1.0,
    }
    assert stats["unmarked"] == {
        "total_content": 2,
        "interactions_by_type": {"click": 1, "favorite": 1},
        "total_interactions": 2,
        "interaction_rate": 1.0,
    }


@pytest.mark.asyncio
async def test_upsert_mark_refreshes_computed_at_and_profile_stats_are_system_scoped(db):
    now = datetime.now(UTC)
    db.add(_content(1, created_at=now))
    db.add_all(
        [
            Source(id=1, name="system", url="https://system.test", scope="system"),
            Source(id=2, name="private", url="https://private.test", scope="private"),
        ]
    )
    db.add_all(
        [
            SourceEvidenceProfile(source_id=1, publisher_identity="system", publisher_family="system", platform="web"),
            SourceEvidenceProfile(source_id=2, publisher_identity="private", publisher_family="private", platform="web"),
            ContentEvidenceMark(
                content_id=1,
                owner_user_id=None,
                cross_source_level="none",
                computed_at=now - timedelta(days=30),
            ),
        ]
    )
    await db.flush()

    repo = EvidenceRepository(db)
    updated = await repo.upsert_mark(
        content_id=1,
        owner_user_id=None,
        cross_source_level="cross_source",
        platform_count=2,
        platforms=["a", "b"],
        evidence_count=1,
        independent_publisher_count=2,
    )
    stats = await repo.get_stats()

    assert updated.computed_at > now - timedelta(minutes=1)
    assert stats["profiles"] == {
        "total_system_sources": 1,
        "profiled_sources": 1,
        "unprofiled_sources": 0,
        "by_kind": {"unknown": 1},
    }
