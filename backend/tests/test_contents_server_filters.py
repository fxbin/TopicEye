"""内容列表服务端筛选（recommend_level / tag）与 tag-facets 回归测试。

走 PostgreSQL：等级/标签筛选使用 JSONB 语义（@>），SQLite 不支持；
PG fixture 依赖 conftest 的 schema 初始化与逐用例清表。
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
from app.models.source import Source
from app.services.auth_service import create_session, create_user
from app.services.recommendation_level import classify_recommendation_level


@pytest_asyncio.fixture
async def filter_setup() -> AsyncGenerator[tuple[httpx.AsyncClient, str, dict[str, int]], None]:
    """PG 库 + 普通用户 + 3 条不同等级/标签的内容。

    - item 1: 强烈建议写，content.tags=["AI"]（旧数据大小写形态）
    - item 2: 信号不足，分析 tags=["ai安全, 联合国"]（旧数据复合形态）
    - item 3: 不建议追（风险 95）
    """
    from app.services.content_read_cache import invalidate_content_read_caches
    from app.services.json_cache import invalidate_json_cache

    invalidate_content_read_caches()
    invalidate_json_cache("contents:tag-facets:")

    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="filter@example.com", password="Password123", role="user")
        token, _ = await create_session(db, user)
        source = Source(name="Test", url="https://example.com", source_type="RSS", status="active")
        db.add(source)
        await db.flush()
        ids: dict[str, int] = {}
        for i in (1, 2, 3):
            item = ContentItem(
                title=f"Article {i}",
                url=f"https://example.com/article-{i}",
                source_id=source.id,
                source_name="Test",
                source_type="RSS",
                status="crawled",
                content_hash=f"hash-{i}",
                # content 侧存规范键（对应回填后的形态）
                tags=["ai"] if i == 1 else None,
            )
            db.add(item)
            await db.flush()
            ids[f"item{i}"] = item.id
        db.add(
            AiAnalysis(
                content_id=ids["item1"],
                tags=["AI"],
                summary="高质量选题",
                quality_score=60,
                hot_score=60,
                freshness_score=60,
                creator_score=90,
                viral_score=60,
                risk_score=20,
                curation_score=70,
                recommend_level=classify_recommendation_level(
                    quality_score=60,
                    hot_score=60,
                    freshness_score=60,
                    creator_score=90,
                    viral_score=60,
                    risk_score=20,
                    curation_score=70,
                    has_text_signal=True,
                ),
            )
        )
        db.add(
            AiAnalysis(
                content_id=ids["item2"],
                tags=["ai安全, 联合国"],
                summary="默认档",
                quality_score=50,
                hot_score=50,
                freshness_score=50,
                creator_score=50,
                viral_score=50,
                risk_score=50,
                curation_score=0,
                recommend_level="信号不足",
            )
        )
        db.add(
            AiAnalysis(
                content_id=ids["item3"],
                tags=["热点"],
                summary="高风险",
                quality_score=60,
                hot_score=90,
                freshness_score=60,
                creator_score=60,
                viral_score=60,
                risk_score=95,
                curation_score=60,
                recommend_level="不建议追",
            )
        )
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
        yield client, token, ids

    await engine.dispose()


def _ids(resp: httpx.Response) -> set[int]:
    return {item["id"] for item in resp.json()["items"]}


@pytest.mark.asyncio
async def test_recommend_level_filter_uses_persisted_level(filter_setup):
    client, token, ids = filter_setup
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/contents?recommend_level=强烈建议写", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert _ids(resp) == {ids["item1"]}

    resp = await client.get("/contents?recommend_level=不建议追", headers=headers)
    assert resp.status_code == 200
    assert _ids(resp) == {ids["item3"]}


@pytest.mark.asyncio
async def test_recommend_level_invalid_value_rejected(filter_setup):
    client, token, _ids_map = filter_setup
    resp = await client.get(
        "/contents?recommend_level=不存在等级",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tag_filter_matches_normalized_keys(filter_setup):
    """参数侧归一化：?tag=AI 与存储规范键 ai 匹配。

    JSONB @> 对存储值大小写敏感，因此筛选匹配依赖写入规范化与存量
    回填（scripts/normalize_tags.py）；未回填的复合元素不会被查询期
    拆分——这是已知边界，由回填解决。
    """
    client, token, ids = filter_setup
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/contents?tag=AI", headers=headers)
    assert resp.status_code == 200
    assert _ids(resp) == {ids["item1"]}

    # item2 的分析 tags 存的是未回填的复合元素 "ai安全, 联合国"（整体），
    # 整键精确匹配可以命中：
    resp = await client.get("/contents?tag=ai安全, 联合国", headers=headers)
    assert resp.status_code == 200
    assert _ids(resp) == {ids["item2"]}

    resp = await client.get("/contents?tag=不存在", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_level_and_tag_filters_rejected_for_scoring_sort(filter_setup):
    client, token, _ids_map = filter_setup
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/contents?recommend_level=信号不足&sort_by=curation_score", headers=headers)
    assert resp.status_code == 400

    resp = await client.get("/contents?sort_by=low_follower_viral", headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tag_facets_counts_whole_scope_with_normalized_keys(filter_setup):
    """facets 覆盖口径内全部内容，键做规范化合并（ai/AI 同键）。"""
    client, token, _ids_map = filter_setup
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/contents/tag-facets?limit=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    tags = {entry["tag"]: entry["count"] for entry in data["tags"]}

    # item1 content.tags=["ai"] 与分析 tags=["AI"] 归一为同键且按内容去重
    assert tags.get("ai") == 1
    # item2 复合元素在读侧归一化后拆成两个键（facets 不依赖回填）
    assert tags.get("ai安全") == 1
    assert tags.get("联合国") == 1
    assert tags.get("热点") == 1
    assert data["total_contents"] == 3
    assert data["truncated"] is False


@pytest.mark.asyncio
async def test_list_analysis_payload_carries_recommend_level(filter_setup):
    """列表返回的 analysis 带持久化等级，前端可直接使用。"""
    client, token, ids = filter_setup
    resp = await client.get("/contents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    levels = {item["id"]: (item.get("analysis") or {}).get("recommend_level") for item in resp.json()["items"]}
    assert levels.get(ids["item1"]) == "强烈建议写"
    assert levels.get(ids["item3"]) == "不建议追"
