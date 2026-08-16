"""微博热搜 — https://s.weibo.com/top/summary

微博的反爬机制是 Sina Visitor System：直接访问 s.weibo.com 会返回一个
JS 验证页面，该 JS 会调用 passport.weibo.com 获取临时游客 cookie（SUB），
拿到后再跳转回热搜页。

本 scraper 模拟该流程，无需手动配置 cookie：
  1. POST passport.weibo.com/visitor/genvisitor → 获取临时 tid
  2. GET  passport.weibo.com/visitor/visitor?a=incarnate → 获取 SUB cookie
  3. 用 SUB cookie 访问 s.weibo.com/top/summary → 获取热搜 HTML

如果游客系统不可用（IP 被风控等），可退回手动配置的 WEIBO_SUB_COOKIE。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re

import httpx

from . import BaseTrendingScraper, TrendingEntry, register_trending

logger = logging.getLogger(__name__)

# 正则匹配 <a href="/weibo?q=..."> 标题 </a> 后跟 <span> 热度 </span>
_PAT = re.compile(
    r'<a\s+href="/weibo\?q=([^"&]+)[^"]*band_rank=(\d+)[^"]*"[^>]*>'
    r"\s*([^<]+?)\s*</a>"
    r"\s*(?:<span>\s*(\d[\d,]*)\s*</span>)?",
    re.DOTALL,
)


async def _get_visitor_cookie(client: httpx.AsyncClient) -> str:
    """模拟 Sina Visitor System 获取临时游客 SUB cookie。

    Returns:
        形如 "SUB=xxx; SUBP=yyy" 的 cookie 字符串，失败返回空字符串。
    """
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

    # Step 1: 生成游客 tid
    gen_url = "https://passport.weibo.com/visitor/genvisitor"
    post_body = "a=incarnate&cb=gen_callback&fp=%7B%22os%22%3A%221%22%2C%22browser%22%3A%22Chrome131%22%7D"
    try:
        resp = await client.post(
            gen_url,
            headers={"User-Agent": ua, "Content-Type": "application/x-www-form-urlencoded"},
            content=post_body,
        )
        match = re.search(r"gen_callback\((.*)\)", resp.text)
        if not match:
            logger.debug("weibo visitor: genvisitor no callback match")
            return ""
        result = json.loads(match.group(1))
        tid = result.get("data", {}).get("tid", "")
        if not tid:
            logger.debug("weibo visitor: genvisitor returned empty tid")
            return ""
    except Exception as exc:
        logger.debug("weibo visitor: genvisitor failed: %s", exc)
        return ""

    # Step 2: 用 tid 换取 SUB cookie
    incarnate_url = (
        f"https://passport.weibo.com/visitor/visitor"
        f"?a=incarnate&t={tid}&w=2&c=100&gc=&cb=crossdomain&from=weibo&_rand=0.123"
    )
    try:
        await client.get(incarnate_url, headers={"User-Agent": ua})
    except Exception as exc:
        logger.debug("weibo visitor: incarnate failed: %s", exc)
        return ""

    # 从 cookie jar 提取 SUB
    sub = client.cookies.get("SUB", "")
    if not sub:
        logger.debug("weibo visitor: no SUB in cookie jar after incarnate")
        return ""
    # 拼接所有游客 cookie
    parts = []
    for name in ("SUB", "SUBP", "SVB", "SRT", "SRF"):
        val = client.cookies.get(name, "")
        if val:
            parts.append(f"{name}={val}")
    return "; ".join(parts)


@register_trending("weibo")
class WeiboTrending(BaseTrendingScraper):
    SOURCE = "weibo"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        cookie = os.environ.get("WEIBO_SUB_COOKIE", "")

        # 无手动配置 cookie 时，自动获取游客 cookie
        if not cookie:
            cookie = await _get_visitor_cookie(client)
            if cookie:
                logger.debug("weibo trending: using visitor cookie")
            else:
                logger.warning(
                    "weibo trending: visitor cookie unavailable, skipping (set WEIBO_SUB_COOKIE to override)"
                )
                return []

        url = "https://s.weibo.com/top/summary?cate=realtimehot"
        headers = self._build_headers(
            Referer="https://s.weibo.com/",
            Cookie=cookie,
            Accept="text/html,application/xhtml+xml",
        )
        html = await self._fetch_text(client, url, headers=headers)
        if html is None:
            return []

        # 如果拿到的还是验证页面，说明游客 cookie 也没生效
        if "Sina Visitor System" in html:
            logger.warning("weibo trending: visitor cookie did not pass, skipping")
            return []

        results: list[TrendingEntry] = []
        seen = set()
        for match in _PAT.finditer(html):
            query_encoded, rank_str, title, hot_str = match.groups()
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)

            try:
                rank = int(rank_str)
            except (ValueError, TypeError):
                rank = len(results) + 1

            hot_val = 0
            if hot_str:
                with contextlib.suppress(ValueError, TypeError):
                    hot_val = int(hot_str.replace(",", ""))

            decoded_query = query_encoded
            results.append(
                {
                    "title": title,
                    "rank": rank,
                    "url": f"https://s.weibo.com/weibo?q={decoded_query}",
                    "hot_value": hot_val,
                    "hot_value_raw": hot_str or "",
                    "trend": "up" if rank <= 5 else "stable",
                }
            )

        # 如果正则匹配不够，按 td-02 + a href 备用匹配
        if len(results) < 5:
            alt_pat = re.compile(
                r'<a\s+href="(/weibo\?q=[^"]+)"[^>]*target="_blank">([^<]+)</a>',
                re.DOTALL,
            )
            for match in alt_pat.finditer(html):
                href, title = match.groups()
                title = title.strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                results.append(
                    {
                        "title": title,
                        "rank": len(results) + 1,
                        "url": f"https://s.weibo.com{href}",
                        "hot_value": 0,
                        "hot_value_raw": "",
                        "trend": "stable",
                    }
                )
                if len(results) >= 50:
                    break

        logger.info("weibo trending: fetched %d items", len(results))
        return results
