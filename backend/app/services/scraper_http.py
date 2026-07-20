"""
统一的 HTTP client 构造工厂,服务于 content scraper 与 trending scraper。

所有 scraper 通过本模块拿到 ``httpx.AsyncClient`` 的 kwargs,共享配置:
- timeout / follow_redirects / trust_env
- loopback URL 排除代理 (本地开发环境不被代理拦截)
- 通用 User-Agent / Accept / Accept-Encoding (提升与公开 RSS/Atom 服务的兼容性,
  部分服务拒绝 default Python-httpx UA 返回 403/406)
- 条件请求头 (If-None-Match / If-Modified-Since) —— 启用后 RFC 7232 304 路径自动生效

设计原则:
- 配置项统一走 ``settings`` (core/config.py),避免 10+ 处硬编码 UA 漂移
- proxy 单一来源 ``get_proxy_url()``,优先 settings.HTTP_PROXY_URL,
  回退环境变量 https_proxy / HTTPS_PROXY (向后兼容现有部署)
- content scraper 用 ``build_scraper_client_kwargs`` (品牌 UA)
- trending scraper 用 ``build_browser_client_kwargs`` (浏览器 UA)

Scraper 侧不变: 仍写 ``async with httpx.AsyncClient(**kwargs) as client: client.get(url)``。
``client.headers`` 会被应用到所有 ``client.get()`` 调用。

@since 2026-07-20
@author fxbin
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings


def is_loopback_url(url: str) -> bool:
    """判断 URL 是否指向 loopback 主机 (本地回环), loopback 主机必须跳过代理。

    Args:
        url: 待检查的 URL 字符串。

    Returns:
        True 表示 URL 主机是 loopback (localhost / 127.0.0.1 / 0.0.0.0 / ::1 / 127.*),
        False 表示是公网或局域网地址。
    """
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.startswith("127.")


def get_proxy_url() -> str | None:
    """返回抓取层应当使用的 proxy URL, 单一来源。

    优先级:
    1. ``settings.HTTP_PROXY_URL`` (显式配置, 部署时统一指定)
    2. 环境变量 ``https_proxy`` / ``HTTPS_PROXY`` (向后兼容现有部署)

    Returns:
        proxy URL 字符串, 未配置则返回 None。
    """
    if settings.HTTP_PROXY_URL:
        return settings.HTTP_PROXY_URL
    return os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")


def build_scraper_client_kwargs(
    source_url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    user_agent: str | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
) -> dict[str, Any]:
    """构造 content scraper 使用的 ``httpx.AsyncClient`` kwargs。

    Args:
        source_url: scraper 即将抓取的 URL, 用于 loopback-proxy 检测
            (本地开发环境不被代理拦截)。
        etag: 上次响应的 ETag 值, 提供后会作为 If-None-Match 发送,
            服务器可返回 304 跳过 body 传输。
        last_modified: 上次响应的 Last-Modified 值, 提供后会作为
            If-Modified-Since 发送。
        user_agent: 自定义 UA, None 时用 ``settings.HTTP_SCRAPER_USER_AGENT``
            (品牌 UA, 走礼貌爬虫语义)。
        timeout: 单次 fetch 超时 (秒), None 时用
            ``settings.RSS_SCRAPER_TIMEOUT_SECONDS`` (默认 15s)。
        follow_redirects: 是否跟随 3xx 重定向, 默认 True。

    Returns:
        适合 ``httpx.AsyncClient(**kwargs)`` 的关键字参数字典。
    """
    client_kwargs: dict[str, Any] = {
        "timeout": timeout if timeout is not None else settings.RSS_SCRAPER_TIMEOUT_SECONDS,
        "follow_redirects": follow_redirects,
        "trust_env": False,
        "headers": {
            "User-Agent": user_agent or settings.HTTP_SCRAPER_USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
    }
    proxy_url = get_proxy_url()
    if proxy_url and not is_loopback_url(source_url):
        client_kwargs["proxy"] = proxy_url

    if etag:
        client_kwargs["headers"]["If-None-Match"] = etag
    if last_modified:
        client_kwargs["headers"]["If-Modified-Since"] = last_modified
    return client_kwargs


def build_browser_client_kwargs(
    source_url: str | None = None,
    *,
    user_agent: str | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
    accept: str = "application/json, text/plain, */*",
) -> dict[str, Any]:
    """构造 trending scraper 使用的 ``httpx.AsyncClient`` kwargs。

    与 ``build_scraper_client_kwargs`` 的差异:
    - 默认 UA 是 ``settings.HTTP_BROWSER_USER_AGENT`` (浏览器伪装, 应对反爬)
    - 默认 timeout 是 ``settings.HTTP_TRENDING_TIMEOUT_SECONDS`` (30s, 比 RSS 宽松)
    - Accept 默认 application/json (trending 多为 JSON API)
    - ``source_url`` 可选 None, None 时跳过 loopback 检查 (trending scraper
      在 fetch 阶段才决定具体 URL, pipeline 层不知道目标域名)

    Args:
        source_url: 即将抓取的 URL, 用于 loopback 检测。None 时跳过检测。
        user_agent: 自定义 UA, None 时用 ``settings.HTTP_BROWSER_USER_AGENT``。
        timeout: 单次 fetch 超时 (秒), None 时用
            ``settings.HTTP_TRENDING_TIMEOUT_SECONDS`` (默认 30s)。
        follow_redirects: 是否跟随 3xx 重定向, 默认 True。
        accept: Accept 头默认值, trending 场景默认 JSON。

    Returns:
        适合 ``httpx.AsyncClient(**kwargs)`` 的关键字参数字典。
    """
    client_kwargs: dict[str, Any] = {
        "timeout": timeout if timeout is not None else settings.HTTP_TRENDING_TIMEOUT_SECONDS,
        "follow_redirects": follow_redirects,
        "trust_env": False,
        "headers": {
            "User-Agent": user_agent or settings.HTTP_BROWSER_USER_AGENT,
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
        },
    }
    proxy_url = get_proxy_url()
    if proxy_url and (source_url is None or not is_loopback_url(source_url)):
        client_kwargs["proxy"] = proxy_url
    return client_kwargs
