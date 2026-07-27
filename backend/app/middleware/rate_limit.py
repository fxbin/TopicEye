"""
轻量级内存 rate limiter（单进程）。

按 (client_ip, path_prefix) 分桶，滑动窗口计数。
适合单实例部署；多实例需换 Redis 实现。

默认限制：
- /api/v1/auth/*      : 20 req/min（登录/注册防爆破）
- /api/v1/creation/*  : 30 req/min（LLM 调用昂贵）
- 其他 /api/v1/*      : 200 req/min（常规 API）
- /health, /metrics   : 不限（监控 scrape）
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.request_utils import client_ip

# 路径前缀 → (max_requests, window_seconds)
_RATE_RULES: list[tuple[str, int, int]] = [
    ("/api/v1/auth", 20, 60),
    ("/api/v1/creation", 30, 60),
    ("/api/v1", 200, 60),
]

# 豁免路径（不限流）
_EXEMPT_PREFIXES = ("/health", "/metrics", "/docs", "/openapi.json", "/redoc")

# 内存桶: {(ip, rule_idx): [(timestamp, ...)]}
_buckets: dict[tuple[str, int], list[float]] = defaultdict(list)


def _match_rule(path: str) -> tuple[int, int, int] | None:
    """Return (rule_idx, max_requests, window_seconds) or None."""
    for idx, (prefix, max_req, window) in enumerate(_RATE_RULES):
        if path.startswith(prefix):
            return idx, max_req, window
    return None


def _cleanup_bucket(key: tuple[str, int], window: int, now: float) -> None:
    bucket = _buckets[key]
    cutoff = now - window
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 豁免
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        rule = _match_rule(path)
        if rule is None:
            return await call_next(request)

        rule_idx, max_req, window = rule
        ip = client_ip(request)
        bucket_key = (ip, rule_idx)
        now = time.monotonic()

        _cleanup_bucket(bucket_key, window, now)
        bucket = _buckets[bucket_key]

        if len(bucket) >= max_req:
            retry_after = int(window - (now - bucket[0]))
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "retry_after": retry_after},
                headers={
                    "Retry-After": str(max(retry_after, 1)),
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Window": f"{window}s",
                },
            )

        bucket.append(now)
        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(max_req - len(bucket))
        return response
