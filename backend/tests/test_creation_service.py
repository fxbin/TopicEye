import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.services import creation
from app.services.llm.circuit_breaker import CircuitOpenError
from app.services.llm.provider import LlmCapacityUnavailableError


async def _session_with_analyzed_content():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="Runway 推出 MCP 服务器",
                url="https://example.com/runway-mcp",
                source_name="测试信源",
                status=ContentStatus.ANALYZED,
            )
        )
        db.add(
            AiAnalysis(
                content_id=1,
                summary="Runway 把视频生成能力接入 MCP，降低创作者工作流集成成本。",
                key_points=["MCP 接入", "视频生成", "创作者工具"],
                creator_angles=["AI 视频工作流", "工具生态"],
                tags=["AI", "MCP"],
                recommendation="适合拆成创作者工具链升级选题。",
            )
        )
        await db.commit()
    return engine, session_factory


@pytest.mark.asyncio
async def test_generate_creation_plan_attaches_meta(monkeypatch):
    async def fake_call_llm_json(messages, scene, **_kwargs):
        return {
            "titles": ["MCP 让视频工具变了", "Runway 新动作"],
            "cover_slogan": "视频创作新入口",
            "structure": {"hook": "AI 视频工具开始接入工作流。", "points": ["工具更顺手"], "cta": "你会用吗？"},
        }

    monkeypatch.setattr(creation, "call_llm_json", fake_call_llm_json)
    engine, session_factory = await _session_with_analyzed_content()

    async with session_factory() as db:
        plan = await creation.generate_creation_plan(db, 1, "xiaohongshu")

    assert plan["_meta"] == {
        "content_id": 1,
        "platform": "xiaohongshu",
        "platform_name": "小红书图文",
    }
    assert plan["titles"][0] == "MCP 让视频工具变了"
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_creation_plan_returns_timeout_error(monkeypatch):
    async def slow_call_llm_json(messages, scene, **_kwargs):
        await asyncio.sleep(1)
        return {"titles": ["too late"]}

    monkeypatch.setattr(creation, "call_llm_json", slow_call_llm_json)
    monkeypatch.setattr(creation.settings, "CREATION_PLAN_TIMEOUT_SECONDS", 0.01)
    engine, session_factory = await _session_with_analyzed_content()

    async with session_factory() as db:
        plan = await creation.generate_creation_plan(db, 1, "wechat")

    assert "error" in plan
    assert "超时" in plan["error"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_creation_plan_rejects_incomplete_llm_payload(monkeypatch):
    async def incomplete_call_llm_json(messages, scene, **_kwargs):
        return {"titles": ["缺结构"]}

    monkeypatch.setattr(creation, "call_llm_json", incomplete_call_llm_json)
    engine, session_factory = await _session_with_analyzed_content()

    async with session_factory() as db:
        plan = await creation.generate_creation_plan(db, 1, "xiaohongshu")

    assert "error" in plan
    assert "正文结构" in plan["error"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_creation_plan_hides_llm_capacity_internals(monkeypatch):
    async def unavailable_call_llm_json(messages, scene, **_kwargs):
        raise LlmCapacityUnavailableError(routing_group="default", next_available_at=None)

    monkeypatch.setattr(creation, "call_llm_json", unavailable_call_llm_json)
    engine, session_factory = await _session_with_analyzed_content()

    async with session_factory() as db:
        plan = await creation.generate_creation_plan(db, 1, "wechat")

    assert plan["error"] == "创作方案暂时排队等待可用模型渠道，请稍后重试。"
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_creation_plan_hides_circuit_breaker_internals(monkeypatch):
    async def unavailable_call_llm_json(messages, scene, **_kwargs):
        raise CircuitOpenError("LLM circuit breaker OPEN (failures=6)")

    monkeypatch.setattr(creation, "call_llm_json", unavailable_call_llm_json)
    engine, session_factory = await _session_with_analyzed_content()

    async with session_factory() as db:
        plan = await creation.generate_creation_plan(db, 1, "wechat")

    assert plan["error"] == "创作方案服务暂时不可用，系统正在自动恢复，请稍后重试。"
    await engine.dispose()
