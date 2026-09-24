"""忽略记录按用户隔离的回归测试。

背景：IgnoredItem 此前没有 user_id，任何登录用户的「不感兴趣」都会
全局影响所有用户（列表全局排除、他人兴趣向量也被拉低）。

覆盖：
- 个人忽略只影响当前用户的列表与兴趣向量，不影响其他用户与匿名访问；
- 管理员 ``scope=global`` 才产生全局屏蔽，对所有人生效；
- 普通用户请求全局屏蔽返回 403；
- 个人取消忽略只撤销自己的记录；
- 迁移前的存量行（user_id=NULL）沿用全局屏蔽口径。

列表/鉴权用例走内存 SQLite（快）；兴趣向量用例必须走 PostgreSQL——
InterestVectorRepository 的 upsert 依赖 PG 命名约束（ON CONFLICT (uq_...)）。
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, contents as contents_api
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.ignored import IgnoredItem
from app.models.source import Source
from app.models.user import User
from app.services.auth_service import create_session, create_user

Setup = tuple[httpx.AsyncClient, dict[str, str], async_sessionmaker[AsyncSession], dict[str, int]]


def _clear_process_caches() -> None:
    from app.services.content_read_cache import invalidate_content_read_caches

    # 列表/精选缓存是进程级的，且按 user_id 作为缓存键；不同用例的内存库
    # 里 user id 会重叠，先清一次避免读到别的用例的缓存。
    invalidate_content_read_caches()


async def _make_setup(url_or_engine) -> AsyncGenerator[Setup, None]:
    """内存库 + 三个账号（管理员 / 用户A / 用户B）+ 两条带分析标签的内容。"""
    _clear_process_caches()

    engine = create_async_engine(url_or_engine) if isinstance(url_or_engine, str) else url_or_engine
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tokens: dict[str, str] = {}
    async with session_factory() as db:
        for name, role in (("admin", "admin"), ("alice", "user"), ("bob", "user")):
            user = await create_user(db, email=f"{name}@example.com", password="Password123", role=role)
            token, _ = await create_session(db, user)
            tokens[name] = token

        source = Source(name="Test", url="https://example.com", source_type="RSS", status="active")
        db.add(source)
        await db.flush()
        content_ids: dict[str, int] = {}
        for i in (1, 2):
            item = ContentItem(
                title=f"Article {i}",
                url=f"https://example.com/article-{i}",
                source_id=source.id,
                source_name="Test",
                source_type="RSS",
                status="crawled",
                content_hash=f"hash-{i}",
            )
            db.add(item)
            await db.flush()
            content_ids[f"item{i}"] = item.id
            db.add(AiAnalysis(content_id=item.id, tags=["python" if i == 1 else "rust"], curation_score=80))
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(contents_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tokens, session_factory, content_ids

    await engine.dispose()


@pytest_asyncio.fixture
async def isolation_setup() -> AsyncGenerator[Setup, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async for setup in _make_setup(engine):
        yield setup


@pytest_asyncio.fixture
async def isolation_setup_pg() -> AsyncGenerator[Setup, None]:
    """兴趣向量等依赖 PG 约束的用例；conftest 已在该库建 schema 并清表。"""
    async for setup in _make_setup(os.environ["DATABASE_URL"]):
        yield setup


def _ids(resp: httpx.Response) -> set[int]:
    return {item["id"] for item in resp.json()["items"]}


@pytest.mark.asyncio
async def test_personal_ignore_only_affects_own_list(isolation_setup: Setup):
    """A 的个人忽略：A 看不到，B 与匿名访问仍能看到。"""
    client, tokens, _, ids = isolation_setup
    item1 = ids["item1"]

    resp = await client.post(
        f"/contents/{item1}/ignore",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "personal"

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['alice']}"})
    assert resp.status_code == 200
    assert item1 not in _ids(resp)

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['bob']}"})
    assert resp.status_code == 200
    assert item1 in _ids(resp), "B 不应受 A 的个人忽略影响"

    resp = await client.get("/contents")
    assert resp.status_code == 200
    assert item1 in _ids(resp), "匿名访问只受全局屏蔽影响，不应受个人忽略影响"


@pytest.mark.asyncio
async def test_admin_global_ignore_blocks_everyone(isolation_setup: Setup):
    """管理员 scope=global 的屏蔽对所有人（含匿名）生效。"""
    client, tokens, _, ids = isolation_setup
    item2 = ids["item2"]

    resp = await client.post(
        f"/contents/{item2}/ignore?scope=global",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "global"

    for headers in (
        {"Authorization": f"Bearer {tokens['alice']}"},
        {"Authorization": f"Bearer {tokens['bob']}"},
        None,
    ):
        resp = await client.get("/contents", headers=headers)
        assert resp.status_code == 200
        assert item2 not in _ids(resp), "全局屏蔽应对所有访问者生效"


@pytest.mark.asyncio
async def test_non_admin_global_ignore_forbidden(isolation_setup: Setup):
    client, tokens, _, ids = isolation_setup
    resp = await client.post(
        f"/contents/{ids['item1']}/ignore?scope=global",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_personal_unignore_only_removes_own_record(isolation_setup: Setup):
    """A、B 各自忽略同一内容：A 取消后，B 的排除仍然保留。"""
    client, tokens, _, ids = isolation_setup
    item1 = ids["item1"]

    for name in ("alice", "bob"):
        resp = await client.post(
            f"/contents/{item1}/ignore",
            headers={"Authorization": f"Bearer {tokens[name]}"},
        )
        assert resp.status_code == 200

    resp = await client.delete(
        f"/contents/{item1}/ignore",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["removed"] is True

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['alice']}"})
    assert item1 in _ids(resp), "A 已取消忽略，应重新可见"

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['bob']}"})
    assert item1 not in _ids(resp), "B 的忽略记录不应被 A 的取消操作删除"


@pytest.mark.asyncio
async def test_personal_ignore_does_not_pollute_other_users_interest_vector(
    isolation_setup_pg: Setup,
):
    """A 忽略 python 内容：A 的兴趣向量出现负权重，B 的不受影响。"""
    from sqlalchemy import select

    from app.services.interest_vector_service import rebuild_user_vector

    client, tokens, session_factory, ids = isolation_setup_pg

    resp = await client.post(
        f"/contents/{ids['item1']}/ignore",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 200

    async with session_factory() as db:
        user_ids = dict((await db.execute(select(User.email, User.id))).all())
        alice_vector = await rebuild_user_vector(db, user_ids["alice@example.com"])
        bob_vector = await rebuild_user_vector(db, user_ids["bob@example.com"])

    assert alice_vector.get("python", 0) < 0, "A 自己的忽略应进入自己的兴趣向量（负信号）"
    assert "python" not in bob_vector, "A 的忽略不应拉低 B 的兴趣向量"


@pytest.mark.asyncio
async def test_legacy_global_rows_still_block_without_user(isolation_setup: Setup):
    """迁移前的存量行（user_id=NULL）沿用全局屏蔽口径。"""
    client, tokens, session_factory, ids = isolation_setup
    item1 = ids["item1"]

    async with session_factory() as db:
        db.add(IgnoredItem(content_id=item1, user_id=None, reason="not_interested"))
        await db.commit()

    for headers in (
        {"Authorization": f"Bearer {tokens['alice']}"},
        None,
    ):
        resp = await client.get("/contents", headers=headers)
        assert resp.status_code == 200
        assert item1 not in _ids(resp)
