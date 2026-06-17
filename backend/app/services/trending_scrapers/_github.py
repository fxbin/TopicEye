"""GitHub Trending — https://github.com/trending"""

from __future__ import annotations

import logging
import re
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry
import contextlib

logger = logging.getLogger(__name__)

# ── 正则 ──────────────────────────────────────────────────────────
# 每个 trending 仓库是一个 <article class="Box-row">...</article>
_ARTICLE = re.compile(r'<article[^>]*class="Box-row"[^>]*>(.*?)</article>', re.DOTALL)

# h2 内的 a 标签 href，如 <a href="/owner/repo">
_H2_A = re.compile(r'<h2[^>]*>.*?<a\s+href="(/[^"]+)"[^>]*>\s*(.*?)\s*</a>', re.DOTALL)

# 描述 p 标签
_DESC_P = re.compile(r'<p\s+class="[^"]*col-9[^"]*"[^>]*>\s*(.*?)\s*</p>', re.DOTALL)

# stars，如 "1,234" — 匹配 Link--muted 的 <a> 内含 SVG + 数字
_STARS_A = re.compile(
    r'<a\s+href="/[^/]+/[^/]+/stargazers"[^>]*>.*?(?:</svg>|<svg[^>]*>.*?</svg>)\s*([\d,]+)\s*</a>',
    re.DOTALL,
)


@register_trending("github")
class GitHubTrending(BaseTrendingScraper):
    SOURCE = "github"
    CATEGORY = "tech"

    _UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://github.com/trending"
        headers = {
            "User-Agent": self._UA,
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.warning("github trending fetch failed: %s", e)
            return []

        results: list[TrendingEntry] = []
        for idx, article in enumerate(_ARTICLE.finditer(html), start=1):
            block = article.group(1)

            # ── 仓库名 + href ──
            m_h2 = _H2_A.search(block)
            if not m_h2:
                continue
            href = m_h2.group(1).strip()
            # 清理仓库名中的换行/空白
            repo_raw = m_h2.group(2).strip()
            repo_name = re.sub(r"\s+", "", repo_raw)  # e.g. "owner / repo" → "owner/repo"
            repo_name = repo_name.lstrip("/")  # safety

            # ── 描述 ──
            m_desc = _DESC_P.search(block)
            desc = ""
            if m_desc:
                desc = re.sub(r"<[^>]+>", "", m_desc.group(1)).strip()

            # ── stars ──
            hot_val = 0
            hot_raw = ""
            m_stars = _STARS_A.search(block)
            if m_stars:
                hot_raw = m_stars.group(1).strip()
                with contextlib.suppress(ValueError, TypeError):
                    hot_val = int(hot_raw.replace(",", ""))

            title = desc if desc else repo_name

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": f"https://github.com{href}",
                    "hot_value": hot_val,
                    "hot_value_raw": hot_raw,
                    "trend": "up" if idx <= 10 else "stable",
                    "extra": {
                        "repo": repo_name,
                        "description": desc,
                    },
                }
            )

        logger.info("github trending: fetched %d items", len(results))
        return results
