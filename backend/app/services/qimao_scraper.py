"""
七猫小说爬虫 - httpx + mini-racer 执行 window.__NUXT__ IIFE 提取 listData.

架构变迁:
- 旧版: Playwright + Chromium (镜像 +500MB, 启动慢)
- 新版: httpx 拿 HTML + mini-racer (轻量 V8, +15MB) 执行 IIFE 拿 listData

为什么需要 JS 引擎:
- window.__NUXT__ 是个 IIFE: (function(a,b,c,...){return {...}})(arg1, arg2, ...)
- 数据里有变量引用: `is_sign:c`, `category1_name:k` 这些 c/k 是函数参数
- 不能用正则/JSON 解析, 必须用 JS 引擎执行整个函数

依赖说明:
- PyPI 包名: `mini-racer` (新版, 0.6.0 之后从 `py_mini_racer` 改名)
- import 路径: `from py_mini_racer import MiniRacer` (内部目录名仍为 py_mini_racer)
- 0.14+ 返回 JSObject 而非原生 dict, 用 JSON.stringify 桥接转换

接口签名 (保持兼容, qimao_service 不用改):
- fetch_list_data(channel, rank_type) -> Optional[list[dict]]
- fetch_all_ranks() -> dict[tuple[str, str], list[dict]]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

import httpx
from py_mini_racer import MiniRacer

from app.core.http_retry import retry_http_get

logger = logging.getLogger(__name__)

BASE_URL = "https://www.qimao.com/paihang"

# Proxy from environment
PROXY_URL = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# channel + rank_type 配置（七猫榜单的唯一来源，qimao_service 不再保留副本）
RANK_CONFIGS = [
    ("boy", "hot"),
    ("boy", "new"),
    ("boy", "over"),
    ("boy", "collect"),
    ("boy", "update"),
    ("girl", "hot"),
    ("girl", "new"),
    ("girl", "over"),
    ("girl", "collect"),
    ("girl", "update"),
]


def _extract_nuxt_iife(html: str) -> str | None:
    """从 HTML 中提取 window.__NUXT__=(function(...){...})(...) 完整片段.

    返回不带 `window.__NUXT__=` 前缀的纯 IIFE 表达式, 供 JS 引擎执行.
    """
    # 定位起点
    start_marker = "window.__NUXT__="
    start = html.find(start_marker)
    if start < 0:
        return None
    # 找到所在 <script>...</script> 的结束
    end = html.find("</script>", start)
    if end < 0:
        return None
    raw = html[start + len(start_marker) : end].rstrip().rstrip(";").strip()
    if not raw.startswith("(function"):
        return None
    return raw


def _parse_list_data_from_html(html: str) -> list[dict] | None:
    """执行 NUXT IIFE 拿到 listData (单个页面).

    用 JSON.stringify 桥接: JS 端把 listData 序列化成字符串, Python 端 json.loads.
    这样能稳定拿到原生 dict, 避免 0.14+ 的 JSObject 转换问题.
    """
    iife = _extract_nuxt_iife(html)
    if not iife:
        logger.warning("七猫: 未在 HTML 中找到 window.__NUXT__ IIFE")
        return None
    try:
        ctx = MiniRacer()
        # 执行 IIFE 赋值
        ctx.eval(f"var __n = {iife};")
        # JS 端 stringify listData
        list_json = ctx.eval(
            "(function(){"
            "  var fetch = __n && __n.fetch;"
            "  if (!fetch) return '[]';"
            "  var firstKey = Object.keys(fetch)[0];"
            "  if (!firstKey) return '[]';"
            "  var listData = fetch[firstKey] && fetch[firstKey].listData;"
            "  return JSON.stringify(listData || []);"
            "})()"
        )
        list_data = json.loads(list_json)
        return list_data if isinstance(list_data, list) else None
    except Exception as e:
        logger.error(f"七猫: mini-racer 执行 IIFE 失败: {e}")
        return None


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    """带 3 次重试的 GET HTML."""
    resp = await retry_http_get(
        client, url, headers=HEADERS, timeout=20, attempts=3, base_delay=0.5, context=f"七猫 GET {url}",
    )
    return resp.text if resp else None


async def fetch_list_data(channel: str, rank_type: str) -> list[dict] | None:
    """抓单个榜单: httpx GET + py_mini_racer 解析."""
    url = f"{BASE_URL}/{channel}/{rank_type}/"
    proxy = {"all://": PROXY_URL} if PROXY_URL else None
    # 强制 IPv4: 容器内 happy eyeballs 走 IPv6 会失败 (DNS 返 IPv6 但应用层不通)
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", proxy=proxy)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        html = await _fetch_html(client, url)
        if not html:
            return None
        return _parse_list_data_from_html(html)


async def fetch_all_ranks() -> dict[tuple[str, str], list[dict]]:
    """一次性抓全部 10 个榜单, 复用 httpx client."""
    results: dict[tuple[str, str], list[dict]] = {}
    proxy = {"all://": PROXY_URL} if PROXY_URL else None
    # 强制 IPv4: 容器内 happy eyeballs 走 IPv6 会失败
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", proxy=proxy)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        for idx, (channel, rank_type) in enumerate(RANK_CONFIGS):
            if idx > 0:
                await asyncio.sleep(1.5)  # 保持原有限流行为

            url = f"{BASE_URL}/{channel}/{rank_type}/"
            html = await _fetch_html(client, url)
            if not html:
                results[(channel, rank_type)] = []
                logger.error(f"七猫 {channel}/{rank_type} HTML 获取失败")
                continue

            list_data = _parse_list_data_from_html(html)
            if list_data:
                results[(channel, rank_type)] = list_data
                logger.info(f"七猫 {channel}/{rank_type} 获取 {len(list_data)} 本")
            else:
                results[(channel, rank_type)] = []
                logger.warning(f"七猫 {channel}/{rank_type} 无 listData")

    return results
