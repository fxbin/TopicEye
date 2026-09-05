"""LLM 路由监控与回落的回归测试。

覆盖 2026-09-05 修复：
- metrics_alerting 只检查 default 组熔断器，非默认组 OPEN 不告警；
- get_route_models 对空路由组静默回落到全部模型，无任何日志。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.services.llm._model_cache import ModelConfigCache
from app.services.llm.circuit_breaker import (
    get_llm_circuit_breaker,
    iter_llm_circuit_breakers,
    reset_llm_circuit_breakers,
)


@pytest.fixture(autouse=True)
def _isolated_breakers():
    reset_llm_circuit_breakers()
    yield
    reset_llm_circuit_breakers()


def test_iter_llm_circuit_breakers_covers_all_routing_groups():
    """告警遍历入口必须能看到非 default 组的熔断器。"""
    default = get_llm_circuit_breaker("default")
    analysis = get_llm_circuit_breaker("analysis")

    live = iter_llm_circuit_breakers()
    assert live["default"] is default
    assert live["analysis"] is analysis


@pytest.mark.asyncio
async def test_empty_routing_group_fallback_logs_warning(caplog):
    """空路由组回落到全部模型时必须留 warning，便于发现配置漂移。"""
    import time

    cache = ModelConfigCache()
    cache._route_models = [
        SimpleNamespace(routing_group="default", routing_priority=10),
        SimpleNamespace(routing_group="report", routing_priority=20),
    ]
    cache._last_refresh = time.monotonic()  # 跳过 refresh，直接走回落分支

    with caplog.at_level(logging.WARNING, logger="app.services.llm._model_cache"):
        models = await cache.get_route_models("typo_group")

    assert len(models) == 2
    assert any("typo_group" in r.message for r in caplog.records), "静默回落必须留痕"


@pytest.mark.asyncio
async def test_known_routing_group_no_warning(caplog):
    import time

    cache = ModelConfigCache()
    cache._route_models = [SimpleNamespace(routing_group="analysis", routing_priority=10)]
    cache._last_refresh = time.monotonic()

    with caplog.at_level(logging.WARNING, logger="app.services.llm._model_cache"):
        models = await cache.get_route_models("analysis")

    assert len(models) == 1
    assert not caplog.records
