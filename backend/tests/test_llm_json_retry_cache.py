"""JSON 层重试与响应缓存交互的回归测试。

覆盖 2026-09-05 修复：
- 同参数重试曾直接命中响应缓存，原样拿回第一次解析失败的文本（重试形同虚设）；
- 解析失败的响应曾留在缓存 24h，后续同参调用持续命中坏文本。
"""

from __future__ import annotations

import pytest

from app.services.llm import provider
from app.services.llm.circuit_breaker import reset_llm_circuit_breakers
from app.services.llm.response_cache import get_llm_cache


@pytest.fixture(autouse=True)
def _isolate_route_state():
    provider._failover.reset()
    reset_llm_circuit_breakers()
    get_llm_cache().clear()
    yield
    provider._failover.reset()
    reset_llm_circuit_breakers()
    get_llm_cache().clear()


@pytest.mark.asyncio
async def test_json_retry_reaches_model_after_unparseable_response(monkeypatch):
    """第一次返回不可解析文本时，重试必须真正再次调用模型并拿到好结果。"""
    calls: list[list] = []

    async def fake_inner(messages, temperature, max_tokens, scene, routing_group, response_format=None):
        calls.append(messages)
        if len(calls) == 1:
            return "not-json{", {"model": "m1"}
        return '{"ok": true}', {"model": "m1"}

    monkeypatch.setattr(provider, "_call_llm_with_metadata_inner", fake_inner)

    result, _meta = await provider.call_llm_json_with_metadata(
        [{"role": "user", "content": "给我 JSON"}],
        temperature=0.2,
        max_tokens=64,
        scene="topic_clustering",
        routing_group="test_json_retry",
    )

    assert result == {"ok": True}
    assert len(calls) == 2, "重试应再次打到模型，而不是命中缓存拿回坏文本"


@pytest.mark.asyncio
async def test_unparseable_response_not_left_in_cache(monkeypatch):
    """所有重试都失败后，坏响应应被驱逐，后续调用重新打到模型。"""
    calls: list[list] = []

    async def fake_inner(messages, temperature, max_tokens, scene, routing_group, response_format=None):
        calls.append(messages)
        return "still-not-json", {"model": "m1"}

    monkeypatch.setattr(provider, "_call_llm_with_metadata_inner", fake_inner)
    messages = [{"role": "user", "content": "坏响应场景"}]

    result, _meta = await provider.call_llm_json_with_metadata(
        messages,
        temperature=0.2,
        max_tokens=64,
        scene="topic_clustering",
        routing_group="test_json_retry",
    )
    assert result == {"raw_response": "still-not-json"}

    # 重新调用：缓存已被驱逐，应再次调用模型
    await provider.call_llm_json_with_metadata(
        messages,
        temperature=0.2,
        max_tokens=64,
        scene="topic_clustering",
        routing_group="test_json_retry",
    )
    assert len(calls) == 4, "驱逐后每次调用都应打到模型（2 次调用 × 各 2 次尝试）"


@pytest.mark.asyncio
async def test_cache_evict_drops_exact_key_only():
    cache = get_llm_cache()
    msgs = [{"role": "user", "content": "evict-me"}]
    cache.set(msgs, 0.2, 64, model="scope-a", raw_response="bad{")
    other = [{"role": "user", "content": "keep-me"}]
    cache.set(other, 0.2, 64, model="scope-a", raw_response='{"ok":1}')

    assert cache.evict(msgs, 0.2, 64, model="scope-a") is True
    assert cache.get(msgs, 0.2, 64, model="scope-a") is None
    assert cache.get(other, 0.2, 64, model="scope-a") == '{"ok":1}'
    assert cache.evict(msgs, 0.2, 64, model="scope-a") is False
