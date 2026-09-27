"""路由级健康端点语义回归（#71 / D-8）。

钉死 /health/live 与 /health/ready 的四态契约（DEPLOYMENT.md §3.1 / §1.4）：
- 正常：ready 200；
- 调度器禁用：仍 ready（scheduler.running=false 是受支持形态）；
- DuckDB 降级：仍 ready（duckdb.available=false 是受支持形态）；
- OLTP 不可达：not_ready + 503。
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import app.main as app_main
from app.services import duckdb_service

# 健康端点直连 app 级 async_session（全局引擎连接池）；pytest-asyncio 默认每测试
# 换事件循环会让池内连接跨循环复用而炸（InterfaceError），本文件共用一个 loop。
pytestmark = pytest.mark.asyncio(loop_scope="module")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_main.app),
        base_url="http://testserver",
    )


def _duckdb_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(duckdb_service, "get_analytics", lambda: SimpleNamespace(status="fake"))

    async def _run_query(_):
        return {"status": "ok", "available": True}

    monkeypatch.setattr(duckdb_service, "run_query", _run_query)


def _duckdb_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise():
        raise RuntimeError("duckdb attach failed")

    monkeypatch.setattr(duckdb_service, "get_analytics", _raise)


def _oltp_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """stub OLTP 探测为成功。

    conftest 的 autouse clean_tables 每测试前 pg_terminate_backend 会杀掉
    app 级连接池里的存量连接，同模块多个用例连续使用真实池必然随机踩到
    被杀连接（InterfaceError → 503）。探测的异常路径由
    test_ready_oltp_unreachable_returns_503 覆盖，真实池路径由首位的
    test_live_ok 覆盖，故此处 stub。
    """

    class _ProbeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, _stmt):
            return None

    monkeypatch.setattr(app_main, "async_session", lambda: _ProbeSession())


def _oltp_down(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise ConnectionError("oltp unreachable")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(app_main, "async_session", _BrokenSessionFactory())


async def test_live_ok_returns_alive():
    async with _client() as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


async def test_live_unhealthy_when_oltp_down(monkeypatch):
    _oltp_down(monkeypatch)
    async with _client() as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"


async def test_ready_ok(monkeypatch):
    _duckdb_ok(monkeypatch)
    _oltp_ok(monkeypatch)
    async with _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ready"
    assert payload["database"]["duckdb"]["available"] is True
    assert "scheduler" in payload


async def test_ready_scheduler_disabled_still_ready(monkeypatch):
    """SCHEDULER_ENABLED=false 是受支持形态：调度器不在跑不影响就绪。

    测试进程从不 start_scheduler，scheduler.running 天然为 False——
    该属性是只读 property，无需（也不能）monkeypatch。
    """
    _duckdb_ok(monkeypatch)
    _oltp_ok(monkeypatch)
    async with _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ready"
    assert payload["scheduler"]["running"] is False


async def test_ready_duckdb_degraded_still_ready(monkeypatch):
    """DuckDB 降级（生产默认形态）不影响就绪，但必须如实上报不可用。"""
    _duckdb_down(monkeypatch)
    _oltp_ok(monkeypatch)
    async with _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ready"
    assert payload["database"]["duckdb"]["available"] is False
    assert payload["database"]["duckdb"]["status"] == "error"


async def test_ready_oltp_unreachable_returns_503(monkeypatch):
    """核心回归（#71）：OLTP 不可达必须 not_ready + 503，而非恒 ready。"""
    _duckdb_ok(monkeypatch)
    _oltp_down(monkeypatch)
    async with _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 503
    payload = resp.json()
    assert payload["status"] == "not_ready"
    assert payload["database"]["oltp_error"] == "ConnectionError"


async def test_health_alias_matches_ready(monkeypatch):
    _duckdb_ok(monkeypatch)
    _oltp_ok(monkeypatch)
    async with _client() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
