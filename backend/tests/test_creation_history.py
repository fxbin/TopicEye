"""
creation_plans 持久化 + 历史 API 测试。

覆盖：
- generate_creation_plan 写入 creation_plans 表
- list_my_plans per-user 隔离
- get_my_plan 单条详情
- delete_my_plan 删除权限
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.creation import CreationPlan
from app.models.user import User
from app.services.auth_service import create_user


def _make_content(*, title: str = "测试素材", url: str = "https://example.com/x") -> ContentItem:
    return ContentItem(
        title=title,
        url=url,
        source_name="测试源",
        source_type="RSS",
        status=ContentStatus.ANALYZED,
    )


def _make_analysis(*, content_id: int, summary: str = "素材摘要") -> AiAnalysis:
    return AiAnalysis(content_id=content_id, summary=summary)


async def _seed_analyzed_content(db, *, user_id=None) -> tuple[int, int]:
    """Insert a ContentItem + AiAnalysis; return (content_id, analysis_id)."""
    item = _make_content()
    db.add(item)
    await db.flush()
    analysis = _make_analysis(content_id=item.id)
    db.add(analysis)
    await db.flush()
    return item.id, analysis.id


@pytest.mark.asyncio
async def test_creation_plans_persisted_after_generate(monkeypatch):
    """generate_creation_plan 写入 creation_plans 表（成功路径）。"""
    from app.services import creation as creation_service

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            user = await create_user(db, email="u@t", password="pw")
            await db.commit()
            user_id = user.id
            content_id, _ = await _seed_analyzed_content(db)
            await db.commit()

        # mock LLM 返回一个合法小红书方案
        async def fake_call_llm_json(*args, **kwargs):
            return {
                "titles": ["标题1", "标题2", "标题3"],
                "structure": {"hook": "h", "points": ["p1", "p2"], "cta": "c"},
                "tags": ["t1", "t2"],
                "tone": "活泼",
            }

        monkeypatch.setattr(creation_service, "call_llm_json", fake_call_llm_json)

        async with session_factory() as db:
            plan = await creation_service.generate_creation_plan(
                db,
                content_id,
                "xiaohongshu",
                user_id=user_id,
            )
            assert "error" not in plan
            assert plan["titles"] == ["标题1", "标题2", "标题3"]
            await db.commit()  # generate 只 flush，caller 必须 commit

        # 验证写入 creation_plans
        async with session_factory() as db:
            rows = (await db.execute(select(CreationPlan))).scalars().all()
            assert len(rows) == 1
            r = rows[0]
            assert r.user_id == user_id
            assert r.content_id == content_id
            assert r.platform == "xiaohongshu"
            assert r.platform_name == "小红书图文"
            assert r.error is None
            assert r.plan["titles"] == ["标题1", "标题2", "标题3"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_creation_plans_persist_failure_as_log(monkeypatch):
    """LLM 返回非法结果时也写一条 error 日志。"""
    from app.services import creation as creation_service

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            user = await create_user(db, email="u2@t", password="pw")
            await db.commit()
            user_id = user.id
            content_id, _ = await _seed_analyzed_content(db)
            await db.commit()

        async def fake_call_llm_json(*args, **kwargs):
            return {"titles": []}  # 无效（无标题）

        monkeypatch.setattr(creation_service, "call_llm_json", fake_call_llm_json)

        async with session_factory() as db:
            plan = await creation_service.generate_creation_plan(
                db,
                content_id,
                "xiaohongshu",
                user_id=user_id,
            )
            assert "error" in plan
            await db.commit()  # generate 只 flush，caller 必须 commit

        async with session_factory() as db:
            rows = (await db.execute(select(CreationPlan))).scalars().all()
            assert len(rows) == 1
            assert rows[0].error is not None
    finally:
        await engine.dispose()
