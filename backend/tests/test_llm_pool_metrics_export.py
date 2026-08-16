"""LLM 模型池运行指标导出测试（MP-P0-T3）。

覆盖：
- ``_render_llm_pool_metrics``：纯函数，把 LlmPoolMetrics.snapshot() 渲染为
  Prometheus text format，含标签转义、空快照、熔断事件、scope 排序稳定性。
- ``/metrics`` 端点：导出 ``topiceye_llm_pool_*`` 与 ``topiceye_analysis_pending_total``。
- ``/metrics/snapshot`` 端点：JSON 含 ``llm_pool`` 与 ``analysis_pending`` 键。

不发起真实 LLM 请求、不触碰密钥、不依赖真实时钟。
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.v1 import metrics as metrics_api
from app.api.v1.metrics import _render_llm_pool_metrics
from app.models.content import ContentItem, ContentStatus
from app.models.user import UserRole
from app.services.llm import _rate_limit

# ── _render_llm_pool_metrics（纯函数单元测试）──


class TestRenderLlmPoolMetrics:
    def test_empty_snapshot_returns_nothing(self):
        assert _render_llm_pool_metrics({}) == []

    def test_renders_all_core_metrics(self):
        snapshot = {
            "route:default|channel:official|scene:daily_report": {
                "active": 2,
                "max_active": 3,
                "admitted": 10,
                "queue_wait_seconds": 1.5,
                "rate_limit_wait_seconds": 0.25,
            }
        }
        text = "\n".join(_render_llm_pool_metrics(snapshot))
        assert "# HELP topiceye_llm_pool_inflight" in text
        assert "# TYPE topiceye_llm_pool_inflight gauge" in text
        assert "# HELP topiceye_llm_pool_admitted_total" in text
        assert "# TYPE topiceye_llm_pool_admitted_total counter" in text
        assert "# HELP topiceye_llm_pool_queue_wait_seconds_total" in text
        assert "# HELP topiceye_llm_pool_rate_limit_wait_seconds_total" in text
        assert "# HELP topiceye_llm_pool_max_active" in text
        # 实际数据行携带 scope 标签
        assert 'topiceye_llm_pool_inflight{scope="route:default|channel:official|scene:daily_report"} 2' in text
        assert 'topiceye_llm_pool_admitted_total{scope="route:default|channel:official|scene:daily_report"} 10' in text

    def test_renders_circuit_events(self):
        snapshot = {
            "route:default|channel:official|scene:classification": {
                "active": 0,
                "circuit_open_total": 1,
                "circuit_half_open_total": 2,
            }
        }
        text = "\n".join(_render_llm_pool_metrics(snapshot))
        assert (
            'topiceye_llm_pool_circuit_events_total{scope="route:default|channel:official|scene:classification",event="open"} 1'
            in text
        )
        assert (
            'topiceye_llm_pool_circuit_events_total{scope="route:default|channel:official|scene:classification",event="half_open"} 2'
            in text
        )

    def test_scope_label_escaping(self):
        # scope 含双引号 / 反斜杠 / 换行时必须转义，避免破坏 Prometheus 行。
        snapshot = {
            'route:a"|b\\c\nd': {"active": 1},
        }
        text = "\n".join(_render_llm_pool_metrics(snapshot))
        # 转义后应为 route:a\"|b\\c\nd
        assert 'scope="route:a\\"|b\\\\c\\nd"' in text

    def test_scope_sorting_is_stable(self):
        snapshot = {
            "route:zzz|channel:b|scene:s": {"active": 1},
            "route:aaa|channel:a|scene:s": {"active": 2},
        }
        lines = _render_llm_pool_metrics(snapshot)
        # 第一个数据行（HELP/TYPE 之后的样本行）应来自 aaa scope
        sample_lines = [line for line in lines if line.startswith("topiceye_llm_pool_inflight{")]
        assert "route:aaa" in sample_lines[0]


# ── /metrics 与 /metrics/snapshot 端点级测试 ──


@pytest.fixture
def _pool_metrics_with_data(monkeypatch):
    """注入一组确定性的池指标，避免依赖运行时调用。"""
    snapshot = {
        "route:default|channel:official|scene:content_analysis": {
            "active": 1,
            "max_active": 2,
            "admitted": 5,
            "queue_wait_seconds": 0.4,
            "rate_limit_wait_seconds": 0.1,
        }
    }
    # /metrics 与 /snapshot 均在函数体内 inline import get_llm_pool_metrics，
    # 因此 patch 模块属性即可在调用时生效。
    monkeypatch.setattr(_rate_limit, "get_llm_pool_metrics", lambda: snapshot)
    return snapshot


async def _admin_bearer_token(session_factory) -> str:
    """种一个管理员账号并返回 Bearer token（metrics 端点要求管理员鉴权）。"""
    from app.services.auth_service import create_session, create_user

    async with session_factory() as session:
        user = await create_user(
            session,
            email="metrics-audit@test.local",
            password="MetricsAuditPass42!",
            role=UserRole.ADMIN.value,
        )
        token, _ = await create_session(session, user)
        await session.commit()
        return token


@pytest_asyncio.fixture
async def _export_env(monkeypatch):
    """(app, session_factory)：隔离的 SQLite factory + 鉴权依赖覆盖。

    metrics 端点内部直接 ``async with async_session()``；沿用项目先例
    （test_analysis_recovery 的 event-loop 隔离修复）按测试替换，避免
    复用全局 engine 的跨循环连接。鉴权依赖 get_db 同步指到同一 factory，
    保证种子账号/会话与端点查询命中同一个库。
    """
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.database import Base, get_db

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(metrics_api, "async_session", session_factory)

    app = FastAPI()
    app.include_router(metrics_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app, session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_metrics_endpoint_exports_pool_and_pending(_pool_metrics_with_data, _export_env):
    """``/metrics`` 文本含模型池指标与积压深度。"""
    app, session_factory = _export_env
    # 种一条 PENDING 内容 → 积压深度 >= 1。
    async with session_factory() as session:
        session.add(ContentItem(status=ContentStatus.PENDING, title="t", url="http://x/1"))
        await session.commit()

    token = await _admin_bearer_token(session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    text = resp.text
    assert "topiceye_llm_pool_inflight" in text
    assert "topiceye_llm_pool_admitted_total" in text
    assert "topiceye_analysis_pending_total" in text
    # 积压行有非零计数值
    assert any(
        line.startswith("topiceye_analysis_pending_total ") and not line.endswith(" 0") for line in text.splitlines()
    )


@pytest.mark.asyncio
async def test_metrics_snapshot_includes_pool_and_pending(_pool_metrics_with_data, _export_env):
    """``/metrics/snapshot`` JSON 含 llm_pool 与 analysis_pending 键。"""
    app, session_factory = _export_env
    token = await _admin_bearer_token(session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/metrics/snapshot", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert "llm_pool" in body
    assert "analysis_pending" in body
    assert isinstance(body["analysis_pending"], int)
    pool = body["llm_pool"]
    assert "route:default|channel:official|scene:content_analysis" in pool
    assert pool["route:default|channel:official|scene:content_analysis"]["admitted"] == 5
