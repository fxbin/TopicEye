"""回归测试:_init_duckdb_layer 在 DuckDB 卡住时不会冻死 event loop。

背景:main.py:227 lifespan 之前直接同步调 analytics.available(@property),
内部要执行 INSTALL/LOAD + ATTACH + 跨引擎 SELECT,全是 C 同步调用,
会永久冻死 asyncio event loop,scheduler 永远不起,content 永远不进。

修复:把 DuckDB init 抽到 _init_duckdb_layer,内部用 asyncio.to_thread +
asyncio.wait_for 兜底。即使 DuckDB 真的挂了,超时后也会放弃,
lifespan 继续,scheduler 仍能起来。

本测试不直接测 lifespan(会拉起 alembic/seeds/scheduler 太重),
而是测 _init_duckdb_layer 这个纯函数的 timeout 行为。
"""

import time

import pytest


class _SlowAnalytics:
    """Mock analytics,available 属性会阻塞 delay 秒后返回 True。"""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    @property
    def available(self) -> bool:
        time.sleep(self._delay)
        return True


class _FastAnalytics:
    @property
    def available(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_init_duckdb_layer_returns_within_timeout_when_init_hangs(monkeypatch):
    """用缩短后的测试门限验证阻塞初始化会快速降级，而不等待生产 30s。"""
    from app.main import _init_duckdb_layer

    analytics = _SlowAnalytics(delay=0.5)
    # 生产默认仍是 30s；测试只缩短同一个 wait_for 门限，保持行为路径不变。
    monkeypatch.setattr("app.main._DUCKDB_INIT_TIMEOUT_SECONDS", 0.05)
    # _init_duckdb_layer 内部 import get_analytics,要从 duckdb_service patch
    monkeypatch.setattr("app.services.duckdb_service.get_analytics", lambda: analytics)

    t0 = time.time()
    available = await _init_duckdb_layer()
    elapsed = time.time() - t0

    assert elapsed < 0.3, f"DuckDB init 应在测试门限内降级,实际等了 {elapsed:.3f}s"
    assert available is False


@pytest.mark.asyncio
async def test_init_duckdb_layer_succeeds_when_analytics_fast(monkeypatch):
    """analytics.available 快速返回,验证正常路径:available=True。"""
    from app.main import _init_duckdb_layer

    analytics = _FastAnalytics()
    monkeypatch.setattr("app.services.duckdb_service.get_analytics", lambda: analytics)

    available = await _init_duckdb_layer()
    assert available is True


@pytest.mark.asyncio
async def test_init_duckdb_layer_returns_false_on_exception(monkeypatch, caplog):
    """analytics.available 抛异常时(扩展缺失等),验证降级返回 False 而不抛。"""
    import logging

    from app.main import _init_duckdb_layer

    class _BrokenAnalytics:
        @property
        def available(self) -> bool:
            raise OSError("extension download blocked by GFW")

    monkeypatch.setattr("app.services.duckdb_service.get_analytics", lambda: _BrokenAnalytics())

    with caplog.at_level(logging.WARNING, logger="app.main"):
        available = await _init_duckdb_layer()

    assert available is False
    fallback_logs = [r for r in caplog.records if "DuckDB init skipped" in r.message]
    assert fallback_logs, "异常路径应记 warning 日志"
