"""
HTTP 请求指标采集中间件。

拦截每个 HTTP 请求，记录：
- 请求总数（按 method / path 模板 / status code 分维）
- 请求延迟（Prometheus histogram bucket）
- 在途请求数（gauge）
- 限流命中次数（当 RateLimitMiddleware 返回 429 时计数）
- 5xx 错误数

与 RateLimitMiddleware 并列，挂在外层。限流命中的 429 响应也会被记录。

注意：该中间件必须在 RateLimitMiddleware 之内（后注册），
这样 429 响应会流经本中间件被正确计数。
但为了捕获所有请求（包括被 CORS / rate limit 拦截的），
它应该是最外层中间件。
"""

from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.request_metrics import get_collector

# 不记录指标的路径前缀（避免 /metrics 自身抓取产生噪音 + 健康检查刷量）
_EXEMPT_PREFIXES = (
    "/metrics",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/.well-known",
    "/dashboard",
)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """采集 HTTP 请求级指标，写入全局 RequestMetricsCollector。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 豁免路径不采集（避免 /metrics 自身抓取递归 + 健康检查刷量）
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        collector = get_collector()
        collector.request_started()

        start = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # 未捕获异常 → general_exception_handler 会处理，但中间件层先记录 500
            status_code = 500
            raise
        finally:
            duration = time.perf_counter() - start
            collector.request_completed(
                method=request.method,
                path=path,
                status=status_code,
                duration_seconds=duration,
            )
            # 429 = 限流命中（RateLimitMiddleware 返回的）
            if status_code == 429:
                collector.rate_limit_hit(path)
