from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.content import ContentItem, ContentStatus
from app.models.favorite import FavoriteStatus, FavoriteTargetType
from app.repositories.favorite_repo import FavoriteRepo
from app.schemas.favorite import FavoriteCreate, FavoriteUpdate


@pytest.mark.asyncio
async def test_content_favorite_upsert_builds_snapshot_and_dedupes():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="测试选题",
                url="https://example.com/topic",
                source_name="测试源",
                source_type="RSS",
                category="AI",
                status=ContentStatus.ANALYZED,
                crawled_at=datetime.now(UTC),
            )
        )
        await db.flush()

        repo = FavoriteRepo(db, 1)
        first = await repo.upsert(FavoriteCreate(target_type=FavoriteTargetType.CONTENT, target_id=1))
        second = await repo.upsert(FavoriteCreate(target_type=FavoriteTargetType.CONTENT, target_id=1, note="研究一下"))

        assert second.id == first.id
        assert second.title == "测试选题"
        assert second.target_key == "1"
        assert second.note == "研究一下"
        assert second.snapshot["category"] == "AI"

        items, total = await repo.list_paginated(target_type=FavoriteTargetType.CONTENT)
        assert total == 1
        assert items[0].id == first.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_deleting_content_favorite_syncs_legacy_content_flag():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=2,
                title="待取消收藏",
                url="https://example.com/remove",
                source_name="测试源",
                source_type="RSS",
                category="AI",
                status=ContentStatus.ANALYZED,
                is_favorited=True,
                crawled_at=datetime.now(UTC),
            )
        )
        await db.flush()

        repo = FavoriteRepo(db, 1)
        favorite = await repo.upsert(FavoriteCreate(target_type=FavoriteTargetType.CONTENT, target_id=2))
        await repo.delete(favorite.id)
        content = await db.get(ContentItem, 2)

        assert content is not None
        assert content.is_favorited is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_deleting_content_favorites_syncs_legacy_content_flags():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=3,
                    title="批量取消收藏一",
                    url="https://example.com/remove-bulk-1",
                    source_name="测试源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    is_favorited=True,
                    crawled_at=datetime.now(UTC),
                ),
                ContentItem(
                    id=4,
                    title="批量取消收藏二",
                    url="https://example.com/remove-bulk-2",
                    source_name="测试源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    is_favorited=True,
                    crawled_at=datetime.now(UTC),
                ),
            ]
        )
        await db.flush()

        repo = FavoriteRepo(db, 1)
        first = await repo.upsert(FavoriteCreate(target_type=FavoriteTargetType.CONTENT, target_id=3))
        second = await repo.upsert(FavoriteCreate(target_type=FavoriteTargetType.CONTENT, target_id=4))
        deleted = await repo.bulk_delete([first.id, second.id])
        first_content = await db.get(ContentItem, 3)
        second_content = await db.get(ContentItem, 4)

        assert deleted == 2
        assert first_content is not None
        assert first_content.is_favorited is False
        assert second_content is not None
        assert second_content.is_favorited is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_external_favorite_requires_title_when_target_not_resolved():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = FavoriteRepo(db, 1)
        with pytest.raises(ValueError):
            await repo.upsert(FavoriteCreate(target_type=FavoriteTargetType.BOOK, target_key="fanqie:1"))

        item = await repo.upsert(
            FavoriteCreate(
                target_type=FavoriteTargetType.BOOK,
                target_key="fanqie:1",
                title="番茄测试书",
                url="https://example.com/book",
            )
        )
        assert item.target_type == FavoriteTargetType.BOOK
        assert item.target_key == "fanqie:1"

    await engine.dispose()


@pytest.mark.asyncio
async def test_same_target_can_be_favorited_by_different_users_independently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        first_repo = FavoriteRepo(db, 1)
        second_repo = FavoriteRepo(db, 2)

        first = await first_repo.upsert(
            FavoriteCreate(target_type=FavoriteTargetType.BOOK, target_key="book:shared", title="共同目标")
        )
        second = await second_repo.upsert(
            FavoriteCreate(target_type=FavoriteTargetType.BOOK, target_key="book:shared", title="共同目标")
        )

        first_state = await first_repo.state_for_targets(FavoriteTargetType.BOOK, target_keys=["book:shared"])
        second_state = await second_repo.state_for_targets(FavoriteTargetType.BOOK, target_keys=["book:shared"])

        assert first.id != second.id
        assert first.user_id == 1
        assert second.user_id == 2
        assert first_state[0]["favorite_id"] == first.id
        assert second_state[0]["favorite_id"] == second.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_reorder_status_updates_positions_and_status():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = FavoriteRepo(db, 1)
        first = await repo.upsert(
            FavoriteCreate(target_type=FavoriteTargetType.BOOK, target_key="book:1", title="第一本")
        )
        second = await repo.upsert(
            FavoriteCreate(target_type=FavoriteTargetType.BOOK, target_key="book:2", title="第二本")
        )
        third = await repo.upsert(
            FavoriteCreate(target_type=FavoriteTargetType.SOURCE, target_key="source:1", title="信源")
        )

        ordered = await repo.reorder_status(
            status=FavoriteStatus.RESEARCHING,
            ordered_ids=[second.id, third.id, first.id],
        )

        assert [item.id for item in ordered] == [second.id, third.id, first.id]
        assert [item.position for item in ordered] == [1000, 2000, 3000]
        assert {item.status for item in ordered} == {FavoriteStatus.RESEARCHING}

        items, _ = await repo.list_paginated(status=FavoriteStatus.RESEARCHING)
        assert [item.id for item in items] == [second.id, third.id, first.id]

    await engine.dispose()


@pytest.mark.asyncio
async def test_update_favorite_can_persist_creation_plan_snapshot():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = FavoriteRepo(db, 1)
        item = await repo.upsert(
            FavoriteCreate(
                target_type=FavoriteTargetType.BOOK,
                target_key="book:creation-plan",
                title="创作方案测试",
                snapshot={"source": "fanqie"},
            )
        )

        updated = await repo.update(
            item.id,
            FavoriteUpdate(
                snapshot={
                    "source": "fanqie",
                    "creation_plans": {
                        "wechat": {
                            "titles": ["测试标题"],
                            "_meta": {"platform": "wechat"},
                        }
                    },
                }
            ),
        )

        assert updated is not None
        assert updated.snapshot["source"] == "fanqie"
        assert updated.snapshot["creation_plans"]["wechat"]["titles"] == ["测试标题"]

    await engine.dispose()
