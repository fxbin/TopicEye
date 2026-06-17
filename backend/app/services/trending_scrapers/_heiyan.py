"""黑岩书城榜单 — https://h5.zhangwenpindu.cn/

源: 黑岩网（掌文品读）H5 书城的公开 CDN API。
- 接口域名: biz.zhangwenpindu.cn
- 鉴权: 无（自定义客户端头是 UA 指纹，httpx 直发即可）
- 暴露端点:
    GET /book/cdn/home?pageId=1663471786814947329     # 书城首页 (4 个 shelves, 27 本)
    GET /book/cdn/shelf/page?shelfId=...&pageNo=...   # 单榜单分页 (5th shelf「好书共赏」)
    GET /search/new/all?page=N&pageSize=20         # 书库全量 (10 页, 183 本, sortName 现言/古言/...
                                                  #   ★ page 是 Spring Data 0-indexed, 不是 pageNo)
- 失败模式:
    * 反爬: 自定义头缺失 → code=90001「业务渠道不存在」(实测)
    * WAF: 偶尔返回 405 / 🖕🖕🖕🖕, 走 3 次退避重试, 仍失败则降级只抓 home.
    * 列表类目: shelfId 是硬编码常量 (artemis_heiyan_recommendation_*),
      平台改版后失效, 届时 fail-fast 即可, 不要默默写空盘.
    * 详情/章节: 需 udid, 这里**不抓** (plan 范围外).
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Set

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("heiyan")
class HeiyanTrending(BaseTrendingScraper):
    SOURCE = "heiyan"
    CATEGORY = "webnovel"

    BASE = "https://biz.zhangwenpindu.cn"
    HOME_PAGE_ID = "1663471786814947329"
    THROTTLE_SECONDS = 0.2

    HEADERS = {
        "referer": "https://h5.zhangwenpindu.cn/",
        "app-name": "3",
        "client-platform": "2",
        "lang": "zh_CN",
        "app-version": "1.2.9",
        "package-time": "1736152412573",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
    }

    # 注: 第 5 个 shelf「好书共赏」(artemis_heiyan_recommendation_good)
    # 实测不在 home 返回列表里, /shelf/page 也返空, 暂不抓.

    # ── Entry point ────────────────────────────────────────────────
    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        results: List[TrendingEntry] = []
        seen: Set[str] = set()

        # 1) 4 个首页 shelves (27 本)
        home_payload = await self._fetch_home(client)
        if home_payload:
            home_shelves = (home_payload.get("data") or {}).get("shelves") or []
            for shelf in home_shelves:
                shelf_id = shelf.get("id", "")
                shelf_label = shelf.get("name", "书城榜单")
                for record in shelf.get("content") or []:
                    entry = self._build_entry(record, shelf_label, shelf_id)
                    if entry and entry["extra"]["book_id"] not in seen:
                        seen.add(entry["extra"]["book_id"])
                        results.append(entry)
            logger.info("heiyan home: %d unique books from %d shelves", len(results), len(home_shelves))

        # 2) 书库全量 (search/new/all, 10 页, 183 本, sortName 分类)
        search_all = await self._fetch_search_all_pages(client, seen)
        results.extend(search_all)

        logger.info("heiyan trending: fetched %d unique books total", len(results))
        return results

    # ── Home API ───────────────────────────────────────────────────
    async def _fetch_home(self, client: httpx.AsyncClient) -> Optional[dict]:
        url = f"{self.BASE}/book/cdn/home?pageId={self.HOME_PAGE_ID}"
        payload = await self._safe_get_json(client, url, context="home")
        if payload is None:
            return None
        return payload

    # ── Search/all API (分页) ─────────────────────────────────────
    async def _fetch_search_all_pages(
        self,
        client: httpx.AsyncClient,
        seen: Set[str],
        max_pages: int = 12,
        page_size: int = 20,
    ) -> List[TrendingEntry]:
        """抓 /search/new/all 全量分页. 失败/0 records 立即停, 防御性 12 页上限.

        API quirks (实测):
        * 分页参数是 `page` (Spring Data 0-indexed), **不是** `pageNo`.
          之前误用 pageNo 导致所有页返回相同第 1 页, 只抓到 20 本.
        * `page=0` 与 `page=1` 实测返回相同内容 (后端兼容 quirk).
          用 seen: Set[book_id] 全局去重, 重复页自动跳过.
        * totalPages=10 时 page=0..9 有效, page=10 仍返回 3 条 (边界 quirk),
          page=11 返空 → break.

        终止靠 content 空 + max_pages 上限, 不依赖 totalPages (该字段在边界 quirk 下不可靠).

        WAF/异常走 3 次退避重试; 全失败则降级返回空 list, 不 throw.
        """
        entries: List[TrendingEntry] = []
        rank_pos = 0

        for page in range(0, max_pages):
            url = f"{self.BASE}/search/new/all?page={page}&pageSize={page_size}"
            payload = await self._safe_get_json(client, url, context=f"search/all p{page}")
            if payload is None:
                logger.warning("heiyan search/all: aborting at page %d after retries", page)
                break
            data = payload.get("data") or {}
            content = data.get("content") or []
            if not content:
                break

            for book in content:
                entry = self._build_search_entry(book, rank_pos + 1)
                if entry and entry["extra"]["book_id"] not in seen:
                    seen.add(entry["extra"]["book_id"])
                    rank_pos += 1
                    entry["rank"] = rank_pos
                    entries.append(entry)

            await asyncio.sleep(self.THROTTLE_SECONDS)

        if entries:
            logger.info("heiyan search/all: %d unique books fetched", len(entries))
        return entries

    # ── Safe JSON GET with retry ───────────────────────────────────
    async def _safe_get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        context: str = "",
        attempts: int = 3,
    ) -> Optional[dict]:
        for i in range(attempts):
            try:
                resp = await client.get(url, headers=self.HEADERS, timeout=20)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                logger.warning("heiyan %s attempt %d failed: %s", context, i + 1, exc)
                await asyncio.sleep(0.3 * (i + 1))
                continue
            if not (payload.get("success") and payload.get("code") == 1):
                logger.warning("heiyan %s: code=%s msg=%s", context, payload.get("code"), payload.get("message"))
                await asyncio.sleep(0.3 * (i + 1))
                continue
            return payload
        return None

    # ── Entry builder ─────────────────────────────────────────────
    def _build_entry(
        self,
        record: dict,
        shelf_label: str,
        shelf_id: str,
    ) -> Optional[TrendingEntry]:
        book = record.get("book") or {}
        book_id = str(book.get("id") or "").strip()
        if not book_id:
            return None
        name = (book.get("name") or "").strip()
        if not name:
            return None

        author_obj = book.get("author") or {}
        intro = book.get("introduce") or ""
        if len(intro) > 200:
            intro = intro[:200] + "…"

        tags_raw = book.get("tags") or ""
        if isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw if t]
        else:
            tags = [t.strip() for t in str(tags_raw).replace("，", ",").split(",") if t.strip()]

        # home 来的直接用 record.sequence
        rank = record.get("sequence") or 0

        return {
            "title": name,
            "rank": rank,
            "hot_value": max(1, 1000 - rank),
            "url": f"https://h5.zhangwenpindu.cn/#/book/{book_id}",
            "hot_value_raw": shelf_label,
            "trend": "stable",
            "cover_url": book.get("iconUrlMedium") or book.get("iconUrl") or "",
            "extra": {
                "platform": "heiyan",
                "book_id": book_id,
                "author_id": str(author_obj.get("id") or ""),
                "author": author_obj.get("name", ""),
                "author_avatar": author_obj.get("iconUrlSmall", ""),
                "intro": intro,
                "words": book.get("words"),
                "words_str": book.get("wordsStr", ""),
                "tags": tags,
                "finished": bool(book.get("finished")),
                "free": bool(book.get("free")),
                "open": bool(book.get("open")),
                "type": book.get("type"),  # 1=短篇 3=长篇 (实测)
                "wx_book_id": book.get("wxBookId", ""),
                "tk_book_id": book.get("tkBookId", ""),
                "shelf": shelf_label,
                "shelf_id": shelf_id,
            },
        }

    # ── Entry builder for /search/new/all (字段命名不同) ─────────
    def _build_search_entry(
        self,
        book: dict,
        rank: int,
    ) -> Optional[TrendingEntry]:
        """解析 /search/new/all 响应 (扁平结构, 与 home 嵌套 record.book 不同).

        字段差异: id/name/introduce/tags/sortName/booktype/wxbookid/tkbookid
        """
        book_id = str(book.get("id") or "").strip()
        if not book_id:
            return None
        name = (book.get("name") or "").strip()
        if not name:
            return None

        intro = (book.get("introduce") or "").strip()
        if len(intro) > 200:
            intro = intro[:200] + "…"

        # tags 这里是 CSV 字符串, 但 home 形态是 list, 兼容两种
        tags_raw = book.get("tags") or ""
        if isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw if t]
        else:
            tags = [t.strip() for t in str(tags_raw).replace("，", ",").split(",") if t.strip()]

        sort_name = (book.get("sortName") or "").strip()

        return {
            "title": name,
            "rank": rank,
            "hot_value": max(1, 1000 - rank),
            "url": f"https://h5.zhangwenpindu.cn/#/book/{book_id}",
            "hot_value_raw": "书库全量",
            "trend": "stable",
            "cover_url": book.get("iconUrlLarge") or book.get("iconUrlSmall") or "",
            "extra": {
                "platform": "heiyan",
                "book_id": book_id,
                "author_id": str(book.get("authorid") or ""),
                "author": book.get("authorname") or "",
                "intro": intro,
                "words": book.get("words"),
                "words_str": book.get("wordsStr", ""),
                "tags": tags,
                "sortName": sort_name,  # 现言/古言/世情/...
                "type": book.get("booktype"),  # 1=短篇 3=长篇
                "wx_book_id": book.get("wxbookid", ""),
                "tk_book_id": book.get("tkbookid", ""),
                "finished": bool(book.get("finished")),
                "shelf": "书库全量",
                "shelf_id": "search_new_all",
            },
        }
