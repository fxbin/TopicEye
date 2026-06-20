"""
Unified HTTP client builder for scrapers.

所有 scraper 通过这个 helper 拿到 ``httpx.AsyncClient``，共享配置：
- 30s 超时 + 跟随重定向
- ``trust_env=False``（避免被环境代理污染抓取请求）
- loopback URL 排除代理
- 通用 ``User-Agent`` / ``Accept`` / ``Accept-Encoding``（提升与公开 RSS/Atom
  服务的兼容性，部分服务拒绝 default Python-httpx UA）
- 条件请求头（``If-None-Match`` / ``If-Modified-Since``）—— 启用后 RFC 7232
  304 路径自动生效

Scraper 侧不变：仍写 ``async with httpx.AsyncClient(**kwargs) as client: client.get(self.url)``。
``client.headers`` 会被应用到所有 ``client.get()`` 调用。
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

# 浏览器-like UA 提升与公开 RSS/Atom 服务的兼容性（部分服务拒绝 default
# Python-httpx UA，返回 403/406）
_DEFAULT_USER_AGENT = "TopicEye/1.0 (+https://topiceye.example.com) Python-httpx"


def is_loopback_url(url: str) -> bool:
    """Return True if the URL points at a loopback host (proxy must be skipped)."""
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.startswith("127.")


def build_scraper_client_kwargs(
    source_url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> dict[str, Any]:
    """Build kwargs for ``httpx.AsyncClient`` used by all scrapers.

    Returns a dict suitable for ``httpx.AsyncClient(**kwargs)``.

    Parameters
    ----------
    source_url
        URL the scraper is about to fetch. Used for loopback-proxy detection.
    etag, last_modified
        Last-seen response validators. When provided they are sent as
        ``If-None-Match`` / ``If-Modified-Since`` so the server can return
        304 and skip body transfer.
    """
    client_kwargs: dict[str, Any] = {
        # 单次 fetch 超时。原硬编码 30s 偏长,Wired 等慢站会拖到 sync 整体
        # 120s 超时,堵塞 worker。改为可配(默认 15s),给慢站快速 fail 路径。
        # 真正慢但内容重要的 source 可在 DB source 表的 settings 里覆写。
        "timeout": float(os.environ.get("RSS_SCRAPER_TIMEOUT_SECONDS", "15")),
        "follow_redirects": True,
        "trust_env": False,
        "headers": {
            "User-Agent": _DEFAULT_USER_AGENT,
            "Accept": ("application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"),
            "Accept-Encoding": "gzip, deflate",
        },
    }
    proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy_url and not is_loopback_url(source_url):
        client_kwargs["proxy"] = proxy_url

    if etag:
        client_kwargs["headers"]["If-None-Match"] = etag
    if last_modified:
        client_kwargs["headers"]["If-Modified-Since"] = last_modified
    return client_kwargs
