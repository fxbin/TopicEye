"""共享 HTTP 连接池（issue #206）。

三个传输适配器原来每次请求新建 ``httpx.AsyncClient``——每次 LLM 调用都多一次
TCP + TLS 握手。这里换成共享客户端：httpx 的连接池按（协议, 主机, 端口）分池，
一个客户端可以同时服务多个厂商端点，不需要每个 provider 一个。

**按事件循环隔离**：pytest-asyncio 每个用例一个新循环，在已关闭的循环上复用
客户端会报 ``Event loop is closed``。所以客户端按「当前运行循环」惰性创建，
换循环就丢弃旧引用（在已关闭的循环上 ``await aclose()`` 本身会抛错，只能交给
GC；生产进程只有一个循环，这条路径只对测试有意义）。循环 id 会被复用，因此
同时持有循环的弱引用做校验。

超时**按请求**传（``client.post(..., timeout=...)``）：每个模型的超时不一样，
不能做进共享客户端的默认值。
"""

from __future__ import annotations

import asyncio
import logging
import weakref

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_client_loop: weakref.ReferenceType[asyncio.AbstractEventLoop] | None = None


def get_pooled_client() -> httpx.AsyncClient:
    """取当前事件循环的共享客户端；没有或属于别的循环就新建一个。"""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is not None and _client_loop is not None and _client_loop() is loop:
        return _client
    _client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.LLM_HTTP_POOL_CONNECTIONS,
            max_keepalive_connections=settings.LLM_HTTP_POOL_CONNECTIONS,
            keepalive_expiry=settings.LLM_HTTP_KEEPALIVE_SECONDS,
        ),
    )
    _client_loop = weakref.ref(loop)
    return _client


async def close_pooled_client() -> None:
    """关闭共享客户端（应用停机时调用；对不上的循环会静默跳过）。"""
    global _client, _client_loop
    client = _client
    _client = None
    _client_loop = None
    if client is None:
        return
    try:
        await client.aclose()
        logger.info("Shared LLM HTTP client closed")
    except Exception:  # noqa: BLE001 — 关闭失败不阻塞停机
        logger.warning("Shared LLM HTTP client close failed", exc_info=True)


def reset_pooled_client() -> None:
    """测试用：丢弃当前引用（不做任何关闭动作）。"""
    global _client, _client_loop
    _client = None
    _client_loop = None
