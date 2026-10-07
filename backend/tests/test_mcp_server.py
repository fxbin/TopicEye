"""MCP server 测试 — 认证桥接 / 工具逻辑 / HTTP 层。

三种口径：
1. ``TopicEyeTokenVerifier``：in-memory SQLite 种用户 + API token，验证
   合法 token 映射出 ``client_id``、非法 token / 数据库故障返回 None。
2. 工具逻辑：SDK ``Client`` in-process 直连 ``MCPServer``（绕过 HTTP，
   认证守卫单独验证），重服务全部 monkeypatch。
3. HTTP 层：httpx ASGITransport 打挂载后的 ``/mcp`` —— 401 认证门 +
   2026-07-28 无状态 JSON-RPC 全链路（合法 token 调 score_items）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp import Client
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    LATEST_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)

from app.mcp import auth as mcp_auth
from app.mcp.auth import TopicEyeTokenVerifier
from app.mcp.server import build_streamable_http_app, mcp_server
from app.services.auth_service import create_api_token, create_user

EXPECTED_TOOLS = {"get_today_picks", "get_daily_report", "get_trends", "score_items"}


def _fake_report(report_id: int = 7):
    """最小可校验的日报对象（DailyReportResponse 仅前四个字段必填）。"""
    return SimpleNamespace(
        id=report_id,
        owner_user_id=1,
        report_date="2026-10-07",
        weekday="周三",
        overview="测试日报综述",
        keywords=[],
        trends=[],
        top_picks=[],
        topic_count=3,
        content_count=10,
        analyzed_count=10,
    )


def _modern_stateless_request(tool: str, arguments: dict) -> dict:
    """构造 2026-07-28 无状态协议的 tools/call JSON-RPC 请求。"""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments,
            "_meta": {
                PROTOCOL_VERSION_META_KEY: LATEST_PROTOCOL_VERSION,
                CLIENT_CAPABILITIES_META_KEY: {},
                CLIENT_INFO_META_KEY: {"name": "pytest", "version": "0.0"},
            },
        },
    }


# ── 1. TokenVerifier 桥接 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_verifier_accepts_api_token(test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        alice = await create_user(db, email="mcp-alice@t", password="pw")
        await db.commit()
        raw_token, _record = await create_api_token(db, user_id=alice.id, name="mcp test")
        await db.commit()
        alice_id = alice.id

    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)

    verifier = TopicEyeTokenVerifier()
    access = await verifier.verify_token(raw_token)
    assert access is not None
    assert access.client_id == str(alice_id)
    assert access.token == raw_token


@pytest.mark.asyncio
async def test_token_verifier_rejects_bad_token(test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        await create_user(db, email="mcp-bob@t", password="pw")
        await db.commit()

    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)
    assert await TopicEyeTokenVerifier().verify_token("totally-wrong-token") is None


@pytest.mark.asyncio
async def test_token_verifier_db_failure_returns_none(monkeypatch):
    """验证器不向调用方抛异常——数据库故障按「未认证」处理（401）。"""

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mcp_auth, "async_session", _boom)
    assert await TopicEyeTokenVerifier().verify_token("any") is None


# ── 2. 工具逻辑（in-memory Client 直连） ────────────────────────────────


@pytest.mark.asyncio
async def test_tools_listed(monkeypatch):
    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 1)
    async with Client(mcp_server) as client:
        result = await client.list_tools()
    assert {t.name for t in result.tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_tool_requires_authenticated_caller():
    """in-process 连接没有 HTTP bearer 层——工具自身的认证守卫必须拦下。"""
    async with Client(mcp_server) as client:
        # 用合法参数（content_id 为 int），确保 is_error 只能来自认证守卫而非参数校验
        result = await client.call_tool("score_items", {"items": [{"content_id": 1}]})
    assert result.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_today_picks", {"hours": 0}),  # hours ge=1
        ("get_today_picks", {"limit": 101}),  # limit le=100
        ("get_trends", {"days": 31}),  # days le=30
        ("get_trends", {"limit": 9}),  # limit ge=10
        ("score_items", {"items": []}),  # min_length=1
        (
            "score_items",
            {"items": [{"content_id": i} for i in range(51)]},  # max_length=50
        ),
    ],
)
async def test_tool_input_bounds_enforced(monkeypatch, tool, args):
    """工具入参边界与 REST 端点一致——越界参数按工具错误返回（不应执行到业务层）。"""
    calls = []

    async def _fake_build(db, **kwargs):
        calls.append(kwargs)
        return {"items": [], "total": 0, "event_members_hidden": 0, "topics": [], "page": 1, "page_size": 20}

    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 1)
    monkeypatch.setattr("app.mcp.server.build_today_picks", _fake_build)
    async with Client(mcp_server) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error is True
    assert calls == []  # 业务层未被触达


@pytest.mark.asyncio
async def test_score_items_sorted(monkeypatch):
    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 1)
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "score_items",
            {
                "items": [
                    {"content_id": 1, "title": "平淡消息", "info_density": 20},
                    {
                        "content_id": 2,
                        "title": "MCP 实操教程：五步接入选题雷达",
                        "info_density": 85,
                        "actionability": 80,
                    },
                ]
            },
        )
    assert result.is_error is False
    data = result.structured_content
    assert data["count"] == 2
    scores = [r["score"]["final_score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True)
    assert data["results"][0]["content_id"] == 2


@pytest.mark.asyncio
async def test_get_today_picks_passthrough(monkeypatch):
    async def fake_build(db, *, category=None, content_type=None, hours=48, limit=None, owner_user_id=None):
        assert hours == 24 and limit == 5
        return {
            "items": [{"id": 1, "title": "t", "adjusted_curation_score": 88.0}],
            "total": 1,
            "event_members_hidden": 0,
            "topics": [],
            "page": 1,
            "page_size": limit or 20,
        }

    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 1)
    monkeypatch.setattr("app.mcp.server.build_today_picks", fake_build)
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_today_picks", {"hours": 24, "limit": 5})
    assert result.is_error is False
    assert result.structured_content["total"] == 1
    assert result.structured_content["items"][0]["adjusted_curation_score"] == 88.0


@pytest.mark.asyncio
async def test_get_daily_report_by_date_not_found(monkeypatch):
    class _Repo:
        def __init__(self, db):
            pass

        async def get_by_date(self, date, owner_user_id=None):
            return None

    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 42)
    monkeypatch.setattr("app.mcp.server.DailyReportRepository", _Repo)
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_daily_report", {"date": "2020-01-01"})
    assert result.is_error is True


@pytest.mark.asyncio
async def test_get_daily_report_latest(monkeypatch):
    async def fake_latest(db, *, owner_user_id=None):
        assert owner_user_id == 42
        return _fake_report()

    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 42)
    monkeypatch.setattr("app.mcp.server.get_latest_today_report", fake_latest)
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_daily_report", {})
    assert result.is_error is False
    assert result.structured_content["overview"] == "测试日报综述"


@pytest.mark.asyncio
async def test_get_trends_duckdb_unavailable(monkeypatch):
    async def _fail(query):
        raise RuntimeError("duckdb down")

    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 1)
    monkeypatch.setattr("app.mcp.server.duckdb_service.run_query", _fail)
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_trends", {"days": 7})
    assert result.is_error is True


@pytest.mark.asyncio
async def test_get_trends_passthrough(monkeypatch):
    """days/limit 透传到 DuckDB 查询（经 run_query 调用 lambda 的形式捕获）。"""
    captured: dict[str, list[dict]] = {}

    def _trend_topics(days=7):
        captured.setdefault("topics_calls", []).append({"days": days})
        return [{"name": "MCP", "best_score": 88.0}]

    def _keyword_cloud(days=7, limit=50):
        captured.setdefault("keywords_calls", []).append({"days": days, "limit": limit})
        return [{"keyword": "MCP", "count": 9}]

    async def _run(query):
        return query()

    monkeypatch.setattr("app.mcp.server._caller_user_id", lambda: 1)
    monkeypatch.setattr("app.mcp.server.duckdb_service.run_query", _run)
    monkeypatch.setattr("app.mcp.server.duckdb_service.query_trend_topics", _trend_topics)
    monkeypatch.setattr("app.mcp.server.duckdb_service.query_keyword_cloud", _keyword_cloud)
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_trends", {"days": 3, "limit": 30})
    assert result.is_error is False
    assert captured["topics_calls"] == [{"days": 3}]
    assert captured["keywords_calls"] == [{"days": 3, "limit": 30}]
    assert result.structured_content["days"] == 3


# ── 3. HTTP 层（挂载后的 /mcp） ────────────────────────────────────────


def _mounted_app() -> FastAPI:
    app = FastAPI()
    app.mount("/mcp", build_streamable_http_app())
    return app


@pytest.mark.asyncio
async def test_http_mcp_rejects_missing_token():
    transport = ASGITransport(app=_mounted_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp/", json=_modern_stateless_request("score_items", {"items": []}))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_http_mcp_rejects_invalid_token(test_session_factory, monkeypatch):
    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)
    transport = ASGITransport(app=_mounted_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/mcp/",
            json=_modern_stateless_request("score_items", {"items": [{"content_id": "c1"}]}),
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_http_mcp_stateless_roundtrip(test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        alice = await create_user(db, email="mcp-http@t", password="pw")
        await db.commit()
        raw_token, _record = await create_api_token(db, user_id=alice.id, name="mcp http test")
        await db.commit()

    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)

    transport = ASGITransport(app=_mounted_app())
    async with (
        mcp_server.session_manager.run(),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        resp = await client.post(
            "/mcp/",
            json=_modern_stateless_request(
                "score_items",
                {
                    "items": [
                        {
                            "content_id": 101,
                            "title": "Runway 推出 MCP 服务器",
                            "info_density": 70,
                            "actionability": 65,
                        }
                    ]
                },
            ),
            headers={"Authorization": f"Bearer {raw_token}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["count"] == 1
    assert result["structuredContent"]["results"][0]["content_id"] == 101
