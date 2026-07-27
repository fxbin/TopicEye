"""
知乎盐选专栏爬取服务。

数据来源：
- 分类：https://www.zhihu.com/xen/market/vip/remix-album（HTML 嵌入）
- 榜单：https://api.zhihu.com/market/categories/all（无需登录）
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import async_session, database_profile
from app.core.http_retry import retry_async
from app.models.zhihu import ZhihuAlbum, ZhihuCategory
from app.services.stats_cache import invalidate_novel_platform_stats_cache

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.zhihu.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

BASE_URL = "https://www.zhihu.com/xen/market/vip/remix-album"
API_BASE = "https://api.zhihu.com/market/categories/all"

# 三种排序
SORT_TYPES = ["hottest", "newest", "monthly_hottest"]
SORT_LABELS = {
    "hottest": "最热",
    "newest": "最新",
    "monthly_hottest": "月热",
}

# 故事分类下的 9 个子分类 ID
STORY_CATEGORY_ID = "1512"
STORY_ALL_LABEL = "故事全部"
STORY_SUBCATS = [
    ("故事", "1513", "爱情"),
    ("故事", "1514", "科幻"),
    ("故事", "1515", "历史"),
    ("故事", "1516", "漫画"),
    ("故事", "1517", "脑洞"),
    ("故事", "1518", "奇闻"),
    ("故事", "1519", "亲历"),
    ("故事", "1520", "校园"),
    ("故事", "1521", "悬疑"),
]

STORY_SUBCAT_IDS = {name: cat_id for _, cat_id, name in STORY_SUBCATS}


def _backend_insert(model):
    if database_profile.is_sqlite:
        return sqlite_insert(model)
    if database_profile.is_postgresql:
        return postgresql_insert(model)
    raise RuntimeError(f"Unsupported database backend for Zhihu upsert: {database_profile.backend}")


def _upsert_zhihu_category_statement(rec: dict):
    stmt = _backend_insert(ZhihuCategory).values(rec)
    return stmt.on_conflict_do_update(
        index_elements=["zhihu_id"],
        set_=dict(
            name=stmt.excluded.name,
            name_en=stmt.excluded.name_en,
            level=stmt.excluded.level,
            parent_id=stmt.excluded.parent_id,
            sort=stmt.excluded.sort,
            artwork=stmt.excluded.artwork,
        ),
    )


def _upsert_zhihu_album_statement(rec: dict):
    stmt = _backend_insert(ZhihuAlbum).values(rec)
    return stmt.on_conflict_do_update(
        index_elements=["business_id", "sort_type"],
        set_=dict(
            title=stmt.excluded.title,
            author=stmt.excluded.author,
            author_desc=stmt.excluded.author_desc,
            abstract=stmt.excluded.abstract,
            thumb_url=stmt.excluded.thumb_url,
            price=stmt.excluded.price,
            original_price=stmt.excluded.original_price,
            is_exclusive=stmt.excluded.is_exclusive,
            is_svip=stmt.excluded.is_svip,
            is_purchased=stmt.excluded.is_purchased,
            online_time=stmt.excluded.online_time,
            online_time_text=stmt.excluded.online_time_text,
            tag=stmt.excluded.tag,
            subscription_name=stmt.excluded.subscription_name,
            media_type=stmt.excluded.media_type,
            subcategory=stmt.excluded.subcategory,
            business_line=stmt.excluded.business_line,
            chapter_text=stmt.excluded.chapter_text,
            category1_name=stmt.excluded.category1_name,
            category2_name=stmt.excluded.category2_name,
            position=stmt.excluded.position,
            rank_pos_diff=stmt.excluded.rank_pos_diff,
            updated_at=stmt.excluded.updated_at,
        ),
    )


def storage_sort_type(sort_type: str, category_id: str) -> str:
    """Scope ranking rows by category while keeping the public sort_type unchanged."""
    return f"{sort_type}__{category_id}"


# 每个分类 + 排序的组合
# 故事默认热门用 HTML 嵌入数据（无需额外请求）
ALL_COMBOS = [
    # 故事 9 个子分类 × 3 种排序 = 27 组
    *[(cat, cat_id, sort) for cat, cat_id, _ in STORY_SUBCATS for sort in SORT_TYPES],
]


def _price_yuan(price) -> str:
    if not price:
        return "免费"
    try:
        v = float(price)
        if v == 0:
            return "免费"
        return f"{v:.2f}元"
    except (TypeError, ValueError):
        return "免费"


def parse_album_item(item: dict) -> dict:
    """将 item 字典映射为数据库字段（不含 @property）。"""
    rights = item.get("resource_rights", []) or []
    sub_right = rights[0] if rights else {}
    price_val = item.get("price", 0) or 0
    return {
        "business_id": str(item.get("business_id", "")),
        "title": item.get("title", "") or "",
        "author": (item.get("author") or [""])[0] if item.get("author") else "",
        "author_desc": item.get("author_desc"),
        "abstract": item.get("description") or item.get("summary", ""),
        "thumb_url": (item.get("image") or [None])[0] or item.get("artwork"),
        "chapter_text": item.get("chapter_text"),
        "price": int(price_val),
        "original_price": int(item.get("original_price", price_val) or price_val),
        "is_exclusive": item.get("tag_before_title") == "独家",
        "is_svip": bool(item.get("svip_privileges", False)),
        "is_purchased": bool(item.get("is_purchased", False)),
        "online_time": item.get("online_time"),
        "online_time_text": item.get("online_time_text"),
        "tag": item.get("tag_before_title"),
        "subscription_name": sub_right.get("subscription_name"),
        "media_type": item.get("media_type"),
        "subcategory": item.get("subcategory"),
        "business_line": item.get("business_line"),
    }


async def _fetch_html(url: str) -> str | None:
    """下载单个页面 HTML。强制 IPv4 (跟 _fetch_api 同根因).

    Uses the shared ``retry_async`` helper for uniform retry + logging.
    """
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")

    async def _do_get() -> str:
        async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Referer": "https://www.zhihu.com/",
                    "Accept": "text/html",
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text

    return await retry_async(
        _do_get, attempts=3, base_delay=0.5,
        context=f"Zhihu HTML {url}",
    )


async def _fetch_api(sort_type: str, limit=20, offset=0, category_id: str | None = None) -> list:
    """调用知乎榜单 API。返回 album item 列表。

    容器内 IPv6 走不通 (happy eyeballs 失败), 强制 IPv4.
    加 3 次重试, 避免单次抽风漏抓某个组合 (历史问题: 1515+monthly_hottest 曾因此缺失).
    """
    params = {
        "study_type": "album",
        "sort_type": sort_type,
        "limit": limit,
        "offset": offset,
        "dataType": "new",
        "level": "2",
    }
    if category_id:
        params["category_id"] = category_id

    # 强制 IPv4: 容器内 happy eyeballs 走 IPv6 会失败 (跟 qimao scraper 同根因)
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")

    async def _fetch() -> list:
        async with httpx.AsyncClient(transport=transport, timeout=12.0) as client:
            resp = await client.get(API_BASE, params=params, headers=HEADERS)
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp,
                )
            d = resp.json()
            return d.get("data", []) or []

    result = await retry_async(
        _fetch, attempts=3, base_delay=0.5,
        context=f"Zhihu API sort={sort_type} cat={category_id}",
    )
    if result is None:
        logger.error(f"Zhihu API 给 up sort={sort_type} cat={category_id} 全部失败")
        return []
    return result


def _extract_array(html: str, key: str) -> list:
    """从 HTML 中提取 "key": [...] 数组。"""
    pat = f'"{key}":'
    idx = html.find(pat)
    if idx < 0:
        return []
    arr_start = html.find("[", idx)
    if arr_start < 0:
        return []
    depth = 0
    end = arr_start
    for i in range(arr_start, len(html)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    try:
        return json.loads(html[arr_start : end + 1])
    except json.JSONDecodeError:
        return []


def _extract_object(html: str, key: str) -> dict:
    """从 HTML 中提取 "key": {...} 对象。"""
    pat = f'"{key}":'
    idx = html.find(pat)
    if idx < 0:
        return {}
    obj_start = html.find("{", idx)
    if obj_start < 0:
        return {}
    depth = 0
    end = obj_start
    for i in range(obj_start, len(html)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    raw = html[obj_start : end + 1].replace("&amp;", "&").replace("&quot;", '"')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def sync_categories(html: str) -> int:
    """从 HTML 解析并保存知乎分类。"""
    cats_raw = _extract_array(html, "categories")
    if not cats_raw:
        return 0

    records = []
    for cat in cats_raw:
        records.append(
            {
                "zhihu_id": str(cat["id"]),
                "name": cat["name"],
                "name_en": cat.get("name_en"),
                "level": cat.get("level", 1),
                "parent_id": str(cat["parent_id"]) if cat.get("parent_id") else None,
                "sort": cat.get("sort", 0),
                "artwork": cat.get("artwork"),
            }
        )
        for sub in cat.get("sub_category", []):
            records.append(
                {
                    "zhihu_id": str(sub["id"]),
                    "name": sub["name"],
                    "name_en": sub.get("name_en"),
                    "level": sub.get("level", 2),
                    "parent_id": str(sub["parent_id"]),
                    "sort": sub.get("sort", 0),
                    "artwork": sub.get("artwork"),
                }
            )

    async with async_session() as db:
        for rec in records:
            await db.execute(_upsert_zhihu_category_statement(rec))
        await db.commit()

    logger.info(f"Zhihu categories saved: {len(records)}")
    return len(records)


async def _fetch_and_save_albums(
    items: list,
    sort_type: str,
    category1: str,
    category2: str,
    prev_positions: dict[str, int] | None = None,
) -> int:
    """将 album item 列表写入数据库。返回条数。

    prev_positions: 上次同步的 {business_id: position}（注意 key 需与 sort_type 同 scope），
    用于计算 rank_pos_diff = prev_pos - cur_pos（正=上升）。为空则不计算 diff。
    """
    if not items:
        return 0

    async with async_session() as db:
        for pos, item in enumerate(items, 1):
            rec = parse_album_item(item)
            rec["sort_type"] = sort_type
            rec["category1_name"] = category1
            rec["category2_name"] = category2
            rec["position"] = pos
            prev_pos = (prev_positions or {}).get(str(item.get("business_id", "")))
            if prev_pos is not None:
                rec["rank_pos_diff"] = prev_pos - pos
            else:
                rec["rank_pos_diff"] = None
            rec["updated_at"] = datetime.now(UTC)

            await db.execute(_upsert_zhihu_album_statement(rec))
        await db.commit()

    logger.info(f"Zhihu albums: {sort_type} {category1}/{category2} -> {len(items)} items")
    return len(items)


async def sync_zhihu_ranks() -> dict:
    """
    全量同步知乎榜单。

    策略：
    1. 拉取 HTML，只保存"故事"分类及其 9 个子分类
    2. 对故事分类的 9 个子分类 × 3 种排序组合分别调用 API 同步
       （每个组合 20 条，分页可扩展）
    3. 故事默认热门也需要同步（category_id=1512，sort_type=hottest）

    Returns:
        {"categories": N, "rank_groups": N, "total_albums": N, "elapsed_seconds": float}
    """
    import time

    t0 = time.time()

    # 1. 拉取 HTML 并保存分类（只保留故事相关）
    html = await _fetch_html(BASE_URL)
    if not html:
        logger.error("Zhihu: failed to fetch HTML")
        return {"categories": 0, "rank_groups": 0, "total_albums": 0, "elapsed_seconds": 0}

    cats_raw = _extract_array(html, "categories")
    story_cat = None
    for cat in cats_raw:
        if str(cat.get("id")) == "1512":
            story_cat = cat
            break

    if not story_cat:
        logger.error("Story category (1512) not found in HTML")
        return {"categories": 0, "rank_groups": 0, "total_albums": 0, "elapsed_seconds": 0}

    # 保存故事一级分类 + 9 个子分类
    records = []
    records.append(
        {
            "zhihu_id": str(story_cat["id"]),
            "name": story_cat["name"],
            "name_en": story_cat.get("name_en"),
            "level": 1,
            "parent_id": None,
            "sort": story_cat.get("sort", 0),
            "artwork": story_cat.get("artwork"),
        }
    )
    for sub in story_cat.get("sub_category", []):
        records.append(
            {
                "zhihu_id": str(sub["id"]),
                "name": sub["name"],
                "name_en": sub.get("name_en"),
                "level": 2,
                "parent_id": str(story_cat["id"]),
                "sort": sub.get("sort", 0),
                "artwork": sub.get("artwork"),
            }
        )

    async with async_session() as db:
        for rec in records:
            await db.execute(_upsert_zhihu_category_statement(rec))
        await db.commit()

    cat_count = len(records)
    logger.info(f"Zhihu story categories saved: {cat_count}")

    # 在删除旧数据前，先快照旧的 (business_id, sort_type) -> position 映射，
    # 作为本次同步计算 rank_pos_diff 的基线（正=上升，负=下降）。
    prev_positions: dict[tuple[str, str], int] = {}
    async with async_session() as db:
        rows = await db.execute(
            select(ZhihuAlbum.business_id, ZhihuAlbum.sort_type, ZhihuAlbum.position)
            .where(ZhihuAlbum.category1_name == "故事")
            .where(ZhihuAlbum.position != None)  # noqa: E711
        )
        for bid, stype, pos in rows.all():
            prev_positions[(str(bid), str(stype))] = int(pos)

    async with async_session() as db:
        await db.execute(delete(ZhihuAlbum).where(ZhihuAlbum.category1_name == "故事"))
        await db.commit()

    # 故事默认热门 + 3 种排序（category_id=1512）
    total = 0
    combos = [
        (STORY_CATEGORY_ID, STORY_ALL_LABEL, "hottest"),
        (STORY_CATEGORY_ID, STORY_ALL_LABEL, "newest"),
        (STORY_CATEGORY_ID, STORY_ALL_LABEL, "monthly_hottest"),
    ]
    for cat_id, sort_label, sort_type in combos:
        items = await _fetch_api(sort_type, limit=20, category_id=cat_id)
        storage_st = storage_sort_type(sort_type, cat_id)
        # 该 sort_type 下的旧 position 子映射
        prev_sub = {bid: pos for (bid, st), pos in prev_positions.items() if st == storage_st}
        n = await _fetch_and_save_albums(items, storage_st, "故事", sort_label, prev_positions=prev_sub)
        total += n
        await asyncio.sleep(0.8)

    # 9 个子分类 × 3 种排序
    for _, cat_id, subcat_name in STORY_SUBCATS:
        for sort_type in SORT_TYPES:
            items = await _fetch_api(sort_type, limit=20, category_id=cat_id)
            storage_st = storage_sort_type(sort_type, cat_id)
            prev_sub = {bid: pos for (bid, st), pos in prev_positions.items() if st == storage_st}
            n = await _fetch_and_save_albums(items, storage_st, "故事", subcat_name, prev_positions=prev_sub)
            total += n
            await asyncio.sleep(0.8)

    elapsed = time.time() - t0
    logger.info(f"Zhihu sync done: {cat_count} categories, {total} albums in {elapsed:.1f}s")
    invalidate_novel_platform_stats_cache()
    return {
        "categories": cat_count,
        "rank_groups": len(combos) + len(STORY_SUBCATS) * len(SORT_TYPES),
        "total_albums": total,
        "elapsed_seconds": round(elapsed, 1),
    }
