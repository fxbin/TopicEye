"""批量个性化加成分计算（compute_personalization_boosts_for_rows）PG 测试。"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.core.database import Base
from app.repositories.interest_vector_repo import InterestVectorRepository
from app.services.auth_service import create_user
from app.services.interest_vector_service import (
    BOOST_MAX,
    compute_personalization_boosts_for_rows,
)


@pytest_asyncio.fixture
async def boost_env() -> AsyncGenerator[tuple[async_sessionmaker[AsyncSession], int], None]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as db:
        user = await create_user(db, email="boost@example.com", password="Password123")
        await db.commit()
        user_id = user.id
    yield session_factory, user_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_boosts_computed_from_user_vector(boost_env):
    session_factory, user_id = boost_env

    async with session_factory() as db:
        repo = InterestVectorRepository(db)
        await repo.upsert_tag(user_id, "ai", 10.0, "favorite")
        await repo.upsert_tag(user_id, "agent", 5.0, "like")
        await db.commit()

        boosts = await compute_personalization_boosts_for_rows(
            db,
            user_id,
            [
                (1, ["ai", "agent"], None),  # 双标签命中 → 正 boost
                (2, ["blockchain"], None),  # 无命中 → 不出现在结果
                (3, ["ai"], None),  # 单标签命中
            ],
        )

    assert set(boosts) == {1, 3}
    assert 0 < boosts[1] <= BOOST_MAX
    assert 0 < boosts[3] <= BOOST_MAX
    assert boosts[1] > boosts[3] or boosts[1] == boosts[3]  # 权重差异不改变正负，只影响幅度


@pytest.mark.asyncio
async def test_boosts_empty_for_user_without_vector(boost_env):
    session_factory, _user_id = boost_env

    async with session_factory() as db:
        other = await create_user(db, email="boost-novector@example.com", password="Password123")
        await db.commit()
        boosts = await compute_personalization_boosts_for_rows(db, other.id, [(1, ["ai"], None)])
    assert boosts == {}


@pytest.mark.asyncio
async def test_boosts_empty_for_anonymous(boost_env):
    session_factory, _user_id = boost_env
    async with session_factory() as db:
        boosts = await compute_personalization_boosts_for_rows(db, None, [(1, ["ai"], None)])
    assert boosts == {}
