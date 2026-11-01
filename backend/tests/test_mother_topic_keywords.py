"""自然语言兴趣描述提取母题关键词（POST /mother-topics/extract-keywords）行为测试。

LLM 一律 mock，不调真实模型。沿用 test_content_event_angles.py 的
monkeypatch + TestClient 模式，与 test_mother_topics_permissions.py 的
sqlite 内存库 + ASGITransport 模式。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, mother_topics as mother_topics_api
from app.api.v1.auth import get_current_user
from app.core.database import Base
from app.models.mother_topic import MotherTopic
from app.services import mother_topic_keywords
from app.services.auth_service import create_session, create_user
from app.services.llm.budget_guard import LlmBudgetExceededError
from app.services.llm.circuit_breaker import CircuitOpenError
from app.services.llm.provider import LlmCapacityUnavailableError, LlmContextWindowExceededError
from app.services.mother_topic_keywords import KeywordExtractionError, extract_keywords_from_description


def _install_llm(monkeypatch, *, result=None, error=None):
    """替换 service 模块内的 LLM 调用，返回捕获到的调用参数。"""

    captured: dict = {}

    async def fake_llm(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(mother_topic_keywords, "call_llm_json", fake_llm)
    return captured


# ── service 层 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_cleans_dedupes_splits_and_drops(monkeypatch):
    captured = _install_llm(
        monkeypatch,
        result={
            "keywords": [
                "AI工具",
                "ai工具",  # 不分大小写去重
                "新能源车, 充电桩",  # 英文逗号拆分
                "比亚迪；特斯拉",  # 中文分号拆分
                "  #ChatGPT# ",  # 去掉空白/井号
                "“固态电池”",  # 剥掉引号
                "",  # 空串丢弃
                "这是一个超过二十个字的长句子会被整个丢掉哦",  # 21 字 > 20，整项丢弃
            ]
        },
    )

    keywords = await extract_keywords_from_description("我想看 AI 工具和新能源车相关的内容")

    assert keywords == ["AI工具", "新能源车", "充电桩", "比亚迪", "特斯拉", "ChatGPT", "固态电池"]
    # LLM 调用参数契约：低温 + 小输出 + 专用 scene
    assert captured["kwargs"] == {"temperature": 0.2, "max_tokens": 600, "scene": "mother_topic_keywords"}
    assert captured["messages"][0]["content"] == mother_topic_keywords.SYSTEM_PROMPT
    assert "我想看 AI 工具和新能源车相关的内容" in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_service_accepts_top_level_list(monkeypatch):
    _install_llm(monkeypatch, result=["固态电池", "换电站", "固态电池"])

    keywords = await extract_keywords_from_description("新能源车")

    assert keywords == ["固态电池", "换电站"]


@pytest.mark.asyncio
async def test_service_truncates_to_fifteen(monkeypatch):
    _install_llm(monkeypatch, result={"keywords": [f"关键词{idx:02d}" for idx in range(20)]})

    keywords = await extract_keywords_from_description("泛描述")

    assert len(keywords) == 15
    assert keywords[0] == "关键词00"
    assert keywords[-1] == "关键词14"


@pytest.mark.asyncio
async def test_service_unparsable_results_raise(monkeypatch):
    for bad in ({"raw_response": "not json"}, {"unrelated": 1}, {"keywords": "不是列表"}, 42):
        _install_llm(monkeypatch, result=bad)
        with pytest.raises(KeywordExtractionError):
            await extract_keywords_from_description("描述")


@pytest.mark.asyncio
async def test_service_empty_after_clean_raises(monkeypatch):
    for bad in ({"keywords": []}, {"keywords": ["", "   ", "#"]}, {"keywords": ["超长句子" * 10]}):
        _install_llm(monkeypatch, result=bad)
        with pytest.raises(KeywordExtractionError):
            await extract_keywords_from_description("描述")


@pytest.mark.asyncio
async def test_service_llm_chain_exception_propagates_uncollapsed(monkeypatch):
    _install_llm(monkeypatch, error=CircuitOpenError("circuit open"))

    # 不捕获不折叠：LLM 链路异常原样上抛（禁止安静失败）
    with pytest.raises(CircuitOpenError):
        await extract_keywords_from_description("描述")


# ── API 层（已登录，DB 不参与）───────────────────────────────────────────


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mother_topics_api.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42)
    return TestClient(app)


def test_endpoint_success_dedupes_and_bounds_count(monkeypatch):
    # 8 个词带 1 个重复 → 去重后 7 个，落在 5-15 区间
    _install_llm(
        monkeypatch,
        result={"keywords": ["AI工具", "新能源车", "ai工具", "充电桩", "比亚迪", "特斯拉", "ChatGPT", "固态电池"]},
    )

    response = _client().post(
        "/mother-topics/extract-keywords",
        json={"description": "我想看 AI 工具和新能源车相关的内容"},
    )

    assert response.status_code == 200, response.text
    keywords = response.json()["keywords"]
    assert 5 <= len(keywords) <= 15
    assert len(keywords) == len({k.lower() for k in keywords})  # 不分大小写去重
    assert keywords[0] == "AI工具"


@pytest.mark.parametrize("description", ["", "   \n\t  ", "x" * 501])
def test_endpoint_rejects_blank_or_overlong_description(description):
    response = _client().post("/mother-topics/extract-keywords", json={"description": description})

    assert response.status_code == 422
    assert "keywords" not in response.json()


@pytest.mark.parametrize(
    ("error", "expected_fragment"),
    [
        (CircuitOpenError("open"), "模型链路熔断中"),
        (LlmCapacityUnavailableError(routing_group="g", next_available_at=None), "模型服务暂不可用"),
        (LlmBudgetExceededError("no budget"), "模型预算已耗尽"),
        (LlmContextWindowExceededError("too long"), "超出模型上下文"),
        (KeywordExtractionError("bad shape"), "模型返回的关键词不可用"),
        (RuntimeError("unexpected"), "关键词提取失败"),
    ],
)
def test_endpoint_maps_llm_failures_to_explicit_502(monkeypatch, error, expected_fragment):
    async def failing_service(description):
        raise error

    monkeypatch.setattr(mother_topics_api, "extract_keywords_from_description", failing_service)
    response = _client().post("/mother-topics/extract-keywords", json={"description": "我想看 AI 工具"})

    # 显式失败而非 200 假成功；不返回空列表；文案给手动填词的出路
    assert response.status_code == 502
    body = response.json()
    assert "keywords" not in body
    assert expected_fragment in body["detail"]
    assert "可直接手动填写关键词" in body["detail"]


# ── 限流规则 ─────────────────────────────────────────────────────────────


def test_extract_keywords_rate_rule_matches_creation_tier():
    from app.middleware.rate_limit import _match_rule

    rule = _match_rule("/api/v1/mother-topics/extract-keywords")
    assert rule is not None
    assert (rule[1], rule[2]) == (30, 60)
    # 其他 mother-topics 端点仍走 /api/v1 兜底规则
    fallback = _match_rule("/api/v1/mother-topics")
    assert fallback is not None
    assert (fallback[1], fallback[2]) == (200, 60)


# ── 只读不写库 + 写入后打分与手工填词一致 ────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_writes_nothing_and_scores_identically_after_put(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="kw-user@example.com", password="Password123", role="user")
        token, _ = await create_session(db, user)
        db.add_all(
            [
                MotherTopic(name="提取落库", keywords=["占位"], is_active=True, owner_user_id=user.id),
                MotherTopic(name="手工填词", keywords=["占位"], is_active=True, owner_user_id=user.id),
            ]
        )
        await db.commit()

    app = FastAPI()
    app.include_router(mother_topics_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[mother_topics_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:

        async def count_topics() -> int:
            async with session_factory() as db:
                return (await db.execute(select(func.count()).select_from(MotherTopic))).scalar_one()

        before = await count_topics()

        # 1. 匿名 401（真实 get_current_user：无凭证命中 401）
        anon = await client.post("/mother-topics/extract-keywords", json={"description": "我想看 AI 工具"})
        assert anon.status_code == 401

        # 2. 提取接口只读：调用前后 mother_topics 行数不变
        _install_llm(
            monkeypatch,
            result={"keywords": ["AI工具", "新能源车", "充电桩", "比亚迪", "特斯拉", "ChatGPT"]},
        )
        headers = {"Authorization": f"Bearer {token}"}
        extracted = await client.post(
            "/mother-topics/extract-keywords",
            headers=headers,
            json={"description": "我想看 AI 工具和新能源车相关的内容"},
        )
        assert extracted.status_code == 200, extracted.text
        keywords = extracted.json()["keywords"]
        assert keywords == ["AI工具", "新能源车", "充电桩", "比亚迪", "特斯拉", "ChatGPT"]
        assert await count_topics() == before

        # 3. 提取结果经既有 PUT 写入母题 X；母题 Y 手工填同一组词
        topics = await client.get("/mother-topics", headers=headers)
        assert topics.status_code == 200
        by_name = {item["name"]: item for item in topics.json()}
        topic_x, topic_y = by_name["提取落库"], by_name["手工填词"]

        put_x = await client.put(
            f"/mother-topics/{topic_x['id']}",
            headers=headers,
            json={"keywords": keywords},
        )
        put_y = await client.put(
            f"/mother-topics/{topic_y['id']}",
            headers=headers,
            json={"keywords": list(keywords)},  # 手工填同一组词（复制一份模拟手输）
        )
        assert put_x.status_code == 200, put_x.text
        assert put_y.status_code == 200, put_y.text

        # 4. score-batch：同一标题下两个母题的 keyword_score 完全一致
        title = "ChatGPT 新玩法：AI工具帮你挑新能源车和充电桩"
        scored = await client.post(
            "/mother-topics/score-batch",
            headers=headers,
            json={"items": [{"title": title, "summary": ""}]},
        )
        assert scored.status_code == 200
        scores = {s["name"]: s["keyword_score"] for s in scored.json()["results"][0]["topic_scores"]}
        assert scores["提取落库"] == scores["手工填词"]
        assert scores["提取落库"] > 0  # 关键词确实命中了标题

    await engine.dispose()
