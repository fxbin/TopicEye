"""点众阅读榜单 — https://www.ishugui.com/ranking

源: 点众网（ishugui）PC 站 Next.js SSG 的公开数据端点。
- 接口域名: www.ishugui.com/_next/data/{build_id}/
- 鉴权: 无 (普通 GET, 标准浏览器 UA 即可)
- 公开端点 (实测, 全部 HTTP 200, 无鉴权):
    GET /index.json                          # 首页 (banner + seoColumnVos)
    GET /ranking/{types}.json?types={types}  # 12 个 rank (见 ALL_RANKS)
- 详情页 URL 模式 (实测): https://www.ishugui.com/book/{bookId}  ← **无 .html 后缀**
  (.html 后缀实测 404, 不要加)
- 12 个 rank (完整结构, 用户确认 [6 男频 + 6 女频]):
    男生 畅销/完本/新书/热读/好评/经典 (1-1/1-3/1-5/1-7/1-11/1-20)
    女生 畅销/完本/新书/热读/好评/经典 (2-2/2-4/2-6/2-8/2-12/2-21)
- 失败模式:
    * build_id (`dzread_20250428`) 是构建时常量, 新版会失效.
      自动从首页 HTML 探测, 失败回退到 KNOWN_BUILD_ID.
    * types 路径是数字约定, 平台改版后需重新发现.
    * 付费章节 (`isCharge=1`) 拿不到正文 —— 不强行抓.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional, Set

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)

# Next.js 把 build_id 嵌在 SSG HTML 的 self.__next_f.push([1,"...buildId\":\"<id>\"..."]) 块里.
_BUILD_ID_RE = re.compile(r'buildId["\']?\s*:\s*["\']([A-Za-z0-9_]+)["\']')


@register_trending("ishugui")
class IshuguiTrending(BaseTrendingScraper):
    SOURCE = "ishugui"
    CATEGORY = "webnovel"

    BASE_DATA = "https://www.ishugui.com/_next/data"
    INDEX_URL = "https://www.ishugui.com/"
    KNOWN_BUILD_ID = "dzread_20250428"  # 兜底值; 探测失败时使用
    THROTTLE_SECONDS = 0.2

    # 完整 12 个 rank: (types 路径段, 榜单名, 性别标签)
    # 男生 (rankType=1): 畅销/完本/新书/热读/好评/经典
    # 女生 (rankType=2): 畅销/完本/新书/热读/好评/经典
    ALL_RANKS = [
        ("1-1", "男生小说畅销榜", "male"),
        ("1-3", "男生小说完本榜", "male"),
        ("1-5", "男生小说新书榜", "male"),
        ("1-7", "男生小说热读榜", "male"),
        ("1-11", "男生小说好评榜", "male"),
        ("1-20", "男生小说经典榜", "male"),
        ("2-2", "女生小说畅销榜", "female"),
        ("2-4", "女生小说完本榜", "female"),
        ("2-6", "女生小说新书榜", "female"),
        ("2-8", "女生小说热读榜", "female"),
        ("2-12", "女生小说好评榜", "female"),
        ("2-21", "女生小说经典榜", "female"),
    ]

    HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "referer": "https://www.ishugui.com/ranking",
    }

    # ── Entry points ───────────────────────────────────────────────
    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        build_id = await self._discover_build_id(client)
        logger.info("ishugui trending: using build_id=%s", build_id)

        results: list[TrendingEntry] = []
        seen: set[str] = set()

        # 1) 首页 banner (作为 "首页 banner" shelf)
        banner_entries = await self._fetch_index_banner(client, build_id, seen)
        results.extend(banner_entries)
        await asyncio.sleep(self.THROTTLE_SECONDS)

        # 2) 12 个 rank × N 页 (每页 10 条)
        for types_path, rank_name, gender in self.ALL_RANKS:
            rank_entries = await self._fetch_rank_pages(client, build_id, types_path, rank_name, gender, seen)
            results.extend(rank_entries)
            await asyncio.sleep(self.THROTTLE_SECONDS)

        logger.info("ishugui trending: fetched %d unique books (build_id=%s, 12 ranks)", len(results), build_id)
        return results

    # ── Build ID discovery ────────────────────────────────────────
    async def _discover_build_id(self, client: httpx.AsyncClient) -> str:
        try:
            resp = await client.get(self.INDEX_URL, headers=self.HEADERS, timeout=20)
            resp.raise_for_status()
            m = _BUILD_ID_RE.search(resp.text)
            if m:
                return m.group(1)
            logger.warning("ishugui: build_id regex miss, falling back")
        except Exception as exc:
            logger.warning("ishugui: build_id discovery failed: %s", exc)
        return self.KNOWN_BUILD_ID

    # ── Index page banner ─────────────────────────────────────────
    async def _fetch_index_banner(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        seen: set[str],
    ) -> list[TrendingEntry]:
        url = f"{self.BASE_DATA}/{build_id}/index.json"
        try:
            resp = await client.get(url, headers=self.HEADERS, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("ishugui index fetch failed: %s", exc)
            return []

        page_props = payload.get("pageProps") or {}
        entries: list[TrendingEntry] = []
        global_rank = 0

        # bannerList: 头部轮播, 字段比 book 字段少
        for banner in page_props.get("bannerList", []):
            book_id = str(banner.get("bookId") or "")
            if not book_id or book_id in seen:
                continue
            global_rank += 1
            seen.add(book_id)
            entries.append(
                {
                    "title": (banner.get("name") or "").strip(),
                    "rank": global_rank,
                    "hot_value": max(1, 1000 - global_rank),
                    "url": f"https://www.ishugui.com/book/{book_id}",
                    "hot_value_raw": "首页 banner",
                    "trend": "stable",
                    "cover_url": banner.get("pcUrl") or banner.get("wapUrl") or "",
                    "extra": {
                        "platform": "ishugui",
                        "book_id": book_id,
                        "shelf": "首页 banner",
                        "shelf_id": "banner",
                    },
                }
            )
        return entries

    # ── Rank pagination ───────────────────────────────────────────
    async def _fetch_rank_pages(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        types_path: str,
        rank_name: str,
        gender: str,
        seen: set[str],
        max_pages: int = 10,  # 单榜单最多 10 页 (= 100 本), 防御性上限
    ) -> list[TrendingEntry]:
        """抓取单个 rank 全量 (分页). 失败/0 records 立即停."""
        entries: list[TrendingEntry] = []
        rank_position = 0
        gender_label = "男频" if gender == "male" else "女频"

        for page in range(1, max_pages + 1):
            # URL 模式 (实测):
            #   page 1: /ranking/{types}.json?types={types}
            #   page 2+: /ranking/{types}/{N}.json
            if page == 1:
                url = f"{self.BASE_DATA}/{build_id}/ranking/{types_path}.json?types={types_path}"
            else:
                url = f"{self.BASE_DATA}/{build_id}/ranking/{types_path}/{page}.json"
            try:
                resp = await client.get(url, headers=self.HEADERS, timeout=20)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                logger.warning("ishugui rank %s page %d fetch failed: %s", types_path, page, exc)
                return entries

            page_props = payload.get("pageProps") or {}
            records = page_props.get("rankBook") or []
            if not records:
                # page 1 是个 redirect (没有 __N_REDIRECT), 也算终止
                break

            for info in records:
                entry = self._build_entry(
                    info,
                    rank_name,
                    rank_position + 1,
                    gender_label,
                    types_path,
                )
                if entry and entry["extra"]["book_id"] not in seen:
                    seen.add(entry["extra"]["book_id"])
                    rank_position += 1
                    entry["rank"] = rank_position  # 用合并去重后的全局序号
                    entries.append(entry)

            # total_pages 在 page_props.pages
            total_pages = page_props.get("pages")
            if total_pages is not None and page >= int(total_pages):
                break

            await asyncio.sleep(self.THROTTLE_SECONDS)

        if entries:
            logger.info(
                "ishugui rank %s (%s): %d books across %d pages",
                types_path,
                rank_name,
                len(entries),
                min(max_pages, total_pages or 0),
            )
        return entries

    # ── Entry builder ─────────────────────────────────────────────
    def _build_entry(
        self,
        info: dict,
        rank_name: str,
        rank: int,
        gender_label: str,
        types_path: str,
    ) -> TrendingEntry | None:
        book_id = str(info.get("bookId") or "").strip()
        if not book_id:
            return None
        name = (info.get("bookName") or "").strip()
        if not name:
            return None

        author = (info.get("author") or "").strip()
        intro = (info.get("introduction") or "").strip()
        if len(intro) > 200:
            intro = intro[:200] + "…"

        tags = info.get("tagV3") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]

        book_type_list = info.get("bookTypeList") or []
        one_type = book_type_list[0].get("oneTypeName", "") if book_type_list else ""

        return {
            "title": name,
            "rank": rank,
            "hot_value": max(1, 1000 - rank),
            "url": f"https://www.ishugui.com/book/{book_id}",
            "hot_value_raw": rank_name,
            "trend": "stable",
            "cover_url": info.get("coverWap", ""),
            "extra": {
                "platform": "ishugui",
                "book_id": book_id,
                "author": author,
                "intro": intro,
                "cover_url": info.get("coverWap", ""),
                "total_word_size": info.get("totalWordSize", ""),
                "total_chapter_num": info.get("totalChapterNum"),
                "last_chapter_name": info.get("lastChapterName", ""),
                "last_chapter_utime": info.get("lastChapterUtime", ""),
                "click_num": info.get("clickNum", ""),
                "status": info.get("status"),
                "status_cn": info.get("statusCn", ""),
                "book_score": info.get("scoreNum") or info.get("bookScore"),
                "tag_v3": tags,
                "book_type_list": book_type_list,
                "one_type": one_type,
                "shelf": rank_name,
                "rank_name": rank_name,
                "gender": gender_label,
                "rank_types": types_path,
            },
        }
