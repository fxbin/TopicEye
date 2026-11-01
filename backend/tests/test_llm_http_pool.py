"""LLM 传输共享 HTTP 连接池（issue #206）的测试。

验证三件事：同一事件循环内复用同一个客户端、换循环不踩「Event loop is
closed」、超时仍按请求生效。适配器层「两次调用只建一个客户端」也在这里断言。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

import app.services.llm.adapters.http_pool as http_pool
from app.services.llm.adapters.base import AdapterResponse
from app.services.llm.adapters.openai_compat import OpenAICompatAdapter


def _ok_body() -> dict:
    return {
        "model": "provider-reported",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _model_config() -> SimpleNamespace:
    return SimpleNamespace(
        provider="custom", model_id="minicpm5-2b", api_base="https://gw.example.com/v1", extra_params=None
    )


@pytest.fixture(autouse=True)
def _fresh_pool():
    http_pool.reset_pooled_client()
    yield
    http_pool.reset_pooled_client()


@pytest.mark.asyncio
async def test_same_loop_reuses_one_client():
    """同一事件循环里取两次，拿到的是同一个客户端对象。"""
    client = http_pool.get_pooled_client()
    assert http_pool.get_pooled_client() is client


@pytest.mark.asyncio
async def test_pool_limits_follow_settings(monkeypatch):
    """连接上限与保活时长从配置读入客户端。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_HTTP_POOL_CONNECTIONS", 7)
    monkeypatch.setattr(settings, "LLM_HTTP_KEEPALIVE_SECONDS", 12.5)

    captured: dict = {}
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    http_pool.get_pooled_client()

    limits = captured["limits"]
    assert limits.max_connections == 7
    assert limits.max_keepalive_connections == 7
    assert limits.keepalive_expiry == 12.5


def test_reset_and_close_create_a_new_client():
    async def scenario():
        first = http_pool.get_pooled_client()
        await http_pool.close_pooled_client()
        assert first.is_closed
        assert http_pool.get_pooled_client() is not first

    asyncio.run(scenario())


def test_client_from_a_dead_loop_is_replaced_not_reused():
    """换事件循环后不复用旧客户端——直接复用会在已关闭的循环上发请求。"""
    holder: dict[str, int] = {}

    async def run_once(label: str) -> None:
        client = http_pool.get_pooled_client()
        holder[label] = id(client)

    asyncio.run(run_once("first"))
    asyncio.run(run_once("second"))
    assert holder["first"] != holder["second"]


@pytest.mark.asyncio
async def test_two_adapter_calls_share_one_client(monkeypatch):
    """两次 complete 只创建一个 httpx.AsyncClient（连接真正被复用的前提）。"""
    created: list[httpx.AsyncClient] = []
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json=_ok_body()))
        client = original(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    from app.services.llm.adapters.registry import build_native_request

    adapter = OpenAICompatAdapter()
    for _ in range(2):
        request = build_native_request(
            _model_config(),
            messages=[{"role": "user", "content": "hi"}],
            api_key="k",
            api_base="https://gw.example.com/v1",
            temperature=0.3,
            max_tokens=8,
            response_format=None,
            timeout=5.0,
        )
        response = await adapter.complete(request)
        assert isinstance(response, AdapterResponse)

    assert len(created) == 1


@pytest.mark.asyncio
async def test_per_request_timeout_reaches_transport(monkeypatch):
    """超时按请求传到传输层：request.timeout 写进 httpx 的请求 extensions。

    MockTransport 不做超时强制（那是真网络层的行为），所以这里验证的是
    「超时值确实随请求下发」，不伪造计时行为。
    """
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = dict(request.extensions.get("timeout") or {})
        return httpx.Response(200, json=_ok_body())

    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    from app.services.llm.adapters.registry import build_native_request

    adapter = OpenAICompatAdapter()
    request = build_native_request(
        _model_config(),
        messages=[{"role": "user", "content": "hi"}],
        api_key="k",
        api_base="https://gw.example.com/v1",
        temperature=0.3,
        max_tokens=8,
        response_format=None,
        timeout=12.5,
    )
    await adapter.complete(request)

    assert captured["timeout"]
    assert set(captured["timeout"]) == {"connect", "read", "write", "pool"}
    assert all(value == 12.5 for value in captured["timeout"].values())
