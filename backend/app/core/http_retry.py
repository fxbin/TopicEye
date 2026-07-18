"""HTTP retry helper for scraper-style GET requests.

Scraper modules (qimao, zhihu, heiyan, …) each had their own retry loop
with linear backoff.  This module provides a single ``retry_http_get``
that handles the loop, logging, and backoff, returning the ``httpx.Response``
on success or ``None`` on exhaustion.

Callers that need custom success validation (e.g. payload["code"] == 1)
can inspect the response and re-raise to trigger a retry.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    context: str = "",
) -> T | None:
    """Retry an async operation with linear backoff.

    - ``operation`` must raise on failure (non-success) to trigger a retry.
    - Returns the operation result on first success.
    - Returns ``None`` if all attempts fail.
    - ``context`` is logged with each failure for debugging.
    """
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as exc:
            if context:
                logger.warning("%s attempt %d failed: %s", context, attempt + 1, exc)
            if attempt < attempts - 1:
                await asyncio.sleep(base_delay * (attempt + 1))
    return None


async def retry_http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 20.0,
    attempts: int = 3,
    base_delay: float = 0.5,
    context: str = "",
) -> httpx.Response | None:
    """GET with retry + linear backoff. Returns Response on success, None on exhaustion.

    Raises ``httpx.HTTPStatusError`` on non-2xx (via ``raise_for_status()``)
    which triggers a retry.  Callers that need softer status handling
    should use ``retry_async`` directly.
    """
    async def _do_get() -> httpx.Response:
        resp = await client.get(url, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp

    return await retry_async(
        _do_get,
        attempts=attempts,
        base_delay=base_delay,
        context=context,
    )
