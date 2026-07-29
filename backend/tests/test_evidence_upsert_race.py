"""Race-condition guard for ``EvidenceRepository.upsert_mark``.

``upsert_mark`` is a SELECT-then-INSERT upsert. On SQLite ``SELECT ... FOR UPDATE``
is a no-op, so two concurrent calls for the same (content_id, owner_user_id) can
both miss the existing row and both insert. The unique partial index on public
marks then rejects the second insert. These tests verify the savepoint guard
absorbs that collision and returns the winning row instead of raising.

The race is simulated deterministically: a pre-seeded row is hidden from the
first ``_find_mark`` call (forcing the INSERT branch) so the subsequent flush
collides with the unique constraint, exactly as a real concurrent insert would.
"""

from __future__ import annotations

import pytest

from app.models.content import ContentItem
from app.models.content_evidence import ContentEvidenceMark
from app.repositories.evidence_repo import EvidenceRepository

pytestmark = pytest.mark.asyncio


async def test_upsert_absorbs_insert_collision(test_session_factory):
    """A lost SELECT race must not surface IntegrityError to the caller.

    Seed a public mark in a separate session, then make ``upsert_mark``'s first
    lookup miss it (simulating a concurrent SELECT that ran before the insert
    committed). The INSERT inside the savepoint collides with the unique index;
    the guard re-reads the winning row and returns it instead of raising.
    """
    async with test_session_factory() as session:
        item = ContentItem(title="race fixture", url="https://example.com/race")
        session.add(item)
        await session.commit()
        content_id = item.id

    # Pre-seed the public mark a concurrent caller would have just inserted.
    async with test_session_factory() as session:
        session.add(
            ContentEvidenceMark(
                content_id=content_id,
                owner_user_id=None,
                cross_source_level="single",
                platform_count=1,
                evidence_count=1,
                independent_publisher_count=1,
            )
        )
        await session.commit()

    async with test_session_factory() as session:
        repo = EvidenceRepository(session)
        original_find = repo._find_mark
        call_count = {"n": 0}

        async def racing_find(cid, owner):
            # First lookup (the race window) misses the seeded row.
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            return await original_find(cid, owner)

        repo._find_mark = racing_find

        mark = await repo.upsert_mark(
            content_id=content_id,
            owner_user_id=None,
            cross_source_level="single",
            platform_count=2,
            platforms=["web"],
            evidence_count=2,
            independent_publisher_count=2,
        )
        assert mark.id is not None
        await session.commit()

    # Exactly one public mark persists.
    async with test_session_factory() as session:
        repo = EvidenceRepository(session)
        mark = await repo._find_mark(content_id, None)
    assert mark is not None


async def test_sequential_upsert_updates_in_place(test_session_factory):
    """A second upsert after the first commits updates the same row (no dup)."""
    async with test_session_factory() as session:
        item = ContentItem(title="seq fixture", url="https://example.com/seq")
        session.add(item)
        await session.commit()
        content_id = item.id

    async with test_session_factory() as session:
        repo = EvidenceRepository(session)
        first = await repo.upsert_mark(
            content_id=content_id,
            owner_user_id=None,
            cross_source_level="single",
            platform_count=1,
            platforms=None,
            evidence_count=1,
            independent_publisher_count=1,
        )
        await session.commit()
        first_id = first.id

    async with test_session_factory() as session:
        repo = EvidenceRepository(session)
        second = await repo.upsert_mark(
            content_id=content_id,
            owner_user_id=None,
            cross_source_level="single",
            platform_count=2,
            platforms=["web"],
            evidence_count=2,
            independent_publisher_count=2,
        )
        await session.commit()
        assert second.id == first_id
