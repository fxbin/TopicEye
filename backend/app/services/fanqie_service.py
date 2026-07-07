"""
番茄小说榜单抓取服务。
定时任务：每日凌晨1点抓取分类 + 四大榜单 + 36个分类书单。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.fanqie import FanqieBook, FanqieCategory, FanqieRankSnapshot
from app.services.fanqie_abogus import generate_a_bogus
from app.services.fanqie_text_decoder import clean_books
from app.services.stats_cache import invalidate_novel_platform_stats_cache

logger = logging.getLogger(__name__)

# ── 番茄接口地址 ───────────────────────────────────────────────
BASE_URL = "https://fanqienovel.com"
CATEGORY_URL = f"{BASE_URL}/api/config/list"
RANK_URL = f"{BASE_URL}/api/rank/category/list"
SEARCH_URL = "https://api-lf.fanqiesdk.com/api/novel/channel/homepage/search/search/v1/"

# 榜单参数
# rank_list_type: 固定传 3
# rankMold: 阅读=2, 新书=1（区分榜单类型的关键参数）
# gender: 由分类 group 决定，male=1, female=0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Accept": "application/json",
    "Referer": "https://fanqienovel.com/",
}

# 签名用的 User-Agent（参考 wengchengjian/fanqie-rank-mcp）
# 与请求头中的 iPhone UA 不同：a_bogus 签名绑定的是这个 Android UA
# 但实际请求仍用 HEADERS 里的 UA——番茄校验只关注签名本身的合法性
SIGN_UA = (
    "Dalvik/2.1.0 (Linux; U; Android 10; SM-G975F Build/QP1A.190711.020) "
    "com.ss.android.article.news/831"
)


def _build_query_string(params: dict) -> str:
    """构造 a_bogus 签名所需的查询串（与最终 URL 顺序一致，不做 URL 编码）。

    rank API 的参数值都是简单 token（数字/空字符串），无需 percent-encoding，
    保持原样拼接即可让签名和服务端校验时的解码结果一致。
    """
    return "&".join(f"{k}={v}" for k, v in params.items())


def _safe_int(value) -> int | None:
    """把番茄 API 返回的值安全转为 int。

    番茄部分字段（如 lastChapterUpdateTime、currentPos）偶尔以字符串形式返回，
    而 model 字段是 Integer，asyncpg 严格校验会拒绝 str→int 列。
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def fetch_json(url: str, params: dict, timeout: int = 30) -> dict | None:
    """发送 GET 请求并返回 JSON。

    对 rank 接口附加 a_bogus 反爬签名（番茄当前未强制，但作为前置防御：
    一旦字节重启强校验，无需紧急修复即可继续工作）。

    用 sync httpx + asyncio.to_thread 而非 httpx.AsyncClient——容器环境下
    AsyncClient 连部分域名会抛空 ConnectError（sync client 正常），换用
    sync transport 绕过此问题，to_thread 保证不阻塞事件循环。
    """
    # 仅 rank 接口需要签名；category 等接口加签名反而可能触发异常校验
    needs_sign = url == RANK_URL

    try:
        def _fetch() -> dict:
            request_params = dict(params)
            if needs_sign:
                query_str = _build_query_string(params)
                request_params["a_bogus"] = generate_a_bogus(query_str, SIGN_UA)
            with httpx.Client(timeout=timeout, headers=HEADERS) as client:
                resp = client.get(url, params=request_params)
                resp.raise_for_status()
                return resp.json()

        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"请求失败 [{url}]: {e}")
        return None


async def sync_categories() -> list[dict]:
    """同步番茄全部分类（upsert 模式，处理同一ID出现在男女频的情况）。"""
    data = await fetch_json(CATEGORY_URL, {"config_key": "serial_rank_category_list_common"})
    if not data or data.get("code") != 0:
        logger.error(f"分类接口失败: {data}")
        return []

    raw_list = data["data"]["list"]
    categories = []
    seen_ids = set()
    for idx, cat in enumerate(raw_list):
        fid = cat["id"]
        group = cat["group"][0] if cat["group"] else "unknown"

        # 科幻末世等分类同时属于男女频，去重但保留分组信息
        if fid in seen_ids:
            continue
        seen_ids.add(fid)

        categories.append(
            {
                "fanqie_id": fid,
                "name": cat["name"],
                "group": group,
                "display_order": idx,
            }
        )

    # Upsert 模式：已存在则更新分组/名称
    async with async_session() as db:
        for cat in categories:
            result = await db.execute(select(FanqieCategory).where(FanqieCategory.fanqie_id == cat["fanqie_id"]))
            existing = result.scalar_one_or_none()
            if existing:
                existing.name = cat["name"]
                existing.group = cat["group"]
                existing.display_order = cat["display_order"]
            else:
                db.add(FanqieCategory(**cat))
        await db.commit()

    logger.info(f"同步分类 {len(categories)} 个")
    return categories


async def sync_category_books(categories: list[dict]) -> None:
    """抓取每个分类下的图书列表（阅读榜+新书榜）。

    rank_list_type: 固定传 3
    rankMold: 阅读=2, 新书=1（区分榜单类型的关键参数）
    gender: 由分类 group 决定，male=1, female=0
    """
    async with async_session() as db:
        for cat in categories:
            fanqie_id = cat["fanqie_id"]
            group = cat["group"]
            is_male = group == "male"
            gender = 1 if is_male else 0

            for rank_idx, (rank_mold, rank_suffix) in enumerate(
                [
                    (2, "reading"),  # 阅读榜
                    (1, "new"),  # 新书榜
                ]
            ):
                # 不同 rank_mold 之间额外等待 1s
                if rank_idx > 0:
                    await asyncio.sleep(1)
                params = {
                    "app_id": 2503,
                    "rank_list_type": 3,  # 固定传3，通过 rankMold 区分阅读/新书
                    "offset": 0,
                    "limit": 100,
                    "category_id": fanqie_id,
                    "gender": gender,
                    "rankMold": rank_mold,
                    "rank_version": "",
                }
                url = RANK_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
                logger.info("请求: %s", url)
                data = await fetch_json(RANK_URL, params)
                if not data or data.get("code") != 0:
                    logger.warning(f"分类 {cat['name']}[{rank_suffix}] 失败: {data}")
                    continue

                book_list = data["data"]["book_list"]
                clean_books(book_list)  # 解码乱码文本
                rank_type = f"male_{rank_suffix}" if is_male else f"female_{rank_suffix}"
                await _upsert_books(
                    db,
                    book_list,
                    rank_type,
                    {
                        "category_id": fanqie_id,
                        "category_name": cat["name"],
                    },
                )
                logger.info(f"分类 {cat['name']}[{rank_type}] 抓取 {len(book_list)} 本")
                await asyncio.sleep(1.5)

        await db.commit()


async def _upsert_books(db: AsyncSession, book_list: list[dict], rank_type: str, extra: dict) -> None:
    """批量 upsert 图书数据。"""
    pos_field = f"{rank_type}_pos"

    for item in book_list:
        book_id = str(item["bookId"])

        # 检查是否已存在
        result = await db.execute(select(FanqieBook).where(FanqieBook.book_id == book_id))
        existing = result.scalar_one_or_none()

        if existing:
            # 计算排名变化：旧排名 - 新排名，正数=上升，负数=下降
            new_pos = _safe_int(item.get("currentPos"))
            old_pos = getattr(existing, pos_field, None)
            if old_pos is not None and new_pos is not None:
                existing.rank_pos_diff = old_pos - new_pos
            else:
                existing.rank_pos_diff = None  # 该榜单首次上榜

            # 更新榜单排名
            setattr(existing, pos_field, new_pos)
            existing.current_pos = new_pos or existing.current_pos
            existing.rank_type = rank_type
            _refresh_book_metadata(existing, item, extra)
            existing.crawled_at = datetime.now()
        else:
            book = FanqieBook(
                book_id=book_id,
                book_name=item.get("bookName", ""),
                author=item.get("author", ""),
                abstract=item.get("abstract", ""),
                category_id=extra.get("category_id", ""),
                category_name=extra.get("category_name", ""),
                thumb_uri=item.get("thumbUri", ""),
                read_count=str(item.get("read_count", "")),
                word_number=str(item.get("wordNumber", "")),
                last_chapter_title=item.get("lastChapterTitle", ""),
                last_chapter_update_time=_safe_int(item.get("lastChapterUpdateTime")),
                current_pos=_safe_int(item.get("currentPos")) or 0,
                rank_type=rank_type,
                rank_pos_diff=None,  # 新上榜，暂无变化
                **{pos_field: _safe_int(item.get("currentPos"))},
            )
            db.add(book)


def _refresh_book_metadata(book: FanqieBook, item: dict, extra: dict) -> None:
    """Refresh mutable metadata, including signed cover URLs that expire."""
    book.book_name = item.get("bookName", book.book_name)
    book.author = item.get("author", book.author)
    book.abstract = item.get("abstract", book.abstract)
    book.category_id = book.category_id or extra.get("category_id", "")
    book.category_name = book.category_name or extra.get("category_name", "")
    book.thumb_uri = item.get("thumbUri") or book.thumb_uri
    book.read_count = str(item.get("read_count", book.read_count or ""))
    book.word_number = str(item.get("wordNumber", book.word_number or ""))
    book.last_chapter_title = item.get("lastChapterTitle", book.last_chapter_title)
    # 番茄 API 偶尔返回字符串形式的时间戳（如 '1783420173'），强转 int 避免 asyncpg 类型校验失败
    raw_update_time = item.get("lastChapterUpdateTime")
    book.last_chapter_update_time = _safe_int(raw_update_time) if raw_update_time is not None else book.last_chapter_update_time


# ── 封面 URL 过期检测 ─────────────────────────────────────────

# 番茄封面 URL 形如:
#   https://p3-reading-sign.fqnovelpic.com/...?lk3s=..&x-expires=1781917201&x-signature=..
# x-expires 是 Unix 时间戳，URL 在该时刻后即返回 403。
# 番茄给的有效期约 7 天，这里提前 1 天判过期，留出刷新窗口。
COVER_EXPIRY_HEADROOM_SECONDS = 24 * 3600


def _cover_url_is_stale(thumb_uri: str | None, now_ts: float | None = None) -> bool:
    """判断封面 URL 是否已过期或即将过期。

    无 x-expires 参数（老格式或非签名 URL）视为不过期，避免误伤。
    """
    if not thumb_uri or "x-expires=" not in thumb_uri:
        return False
    try:
        # 不用 urllib.parse 以减少热路径开销；x-expires= 后跟纯数字
        idx = thumb_uri.index("x-expires=") + len("x-expires=")
        digits = ""
        for ch in thumb_uri[idx:]:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return False
        expires_at = int(digits)
        now = now_ts if now_ts is not None else time.time()
        return expires_at - now < COVER_EXPIRY_HEADROOM_SECONDS
    except (ValueError, IndexError):
        return False


async def refresh_stale_covers() -> dict:
    """检测并刷新已过期的封面 URL。

    策略：扫描全表找出 thumb_uri 过期的书，按 category_id 分组重新调
    rank API（阅读榜+新书榜各一次），用返回的最新 thumbUri 覆盖。

    用于 full_sync 失败时的封面兜底，也可独立调用。
    """
    from app.models.fanqie import FanqieCategory

    logger.info("=== 番茄封面兜底刷新开始 ===")
    start = datetime.now()

    async with async_session() as db:
        # 1. 找出所有封面过期的书，按 category_id 分组
        result = await db.execute(
            select(FanqieBook.book_id, FanqieBook.category_id, FanqieBook.thumb_uri).where(
                FanqieBook.thumb_uri.isnot(None)
            )
        )
        rows = result.all()

        stale_by_cat: dict[str, set[str]] = {}
        total_stale = 0
        for row in rows:
            if _cover_url_is_stale(row.thumb_uri):
                stale_by_cat.setdefault(str(row.category_id), set()).add(row.book_id)
                total_stale += 1

        if total_stale == 0:
            logger.info("无过期封面，跳过")
            return {"refreshed": 0, "stale_total": 0, "elapsed_seconds": (datetime.now() - start).total_seconds()}

        logger.info(f"发现 {total_stale} 本书的封面过期，涉及 {len(stale_by_cat)} 个分类")

        # 2. 加载分类表（需要 group 决定 gender）
        cat_result = await db.execute(select(FanqieCategory.fanqie_id, FanqieCategory.group))
        cat_group_map = {str(r.fanqie_id): r.group for r in cat_result.all()}

        # 3. 按分类重抓 rank API，刷新过期书的 thumb_uri
        refreshed = 0
        for cat_id, stale_book_ids in stale_by_cat.items():
            group = cat_group_map.get(cat_id, "male")
            is_male = group == "male"
            gender = 1 if is_male else 0

            # 阅读榜 + 新书榜各拉一次，覆盖该分类下所有榜单的书
            cat_refreshed = 0
            for rank_mold in (2, 1):  # 2=阅读榜, 1=新书榜
                if cat_refreshed >= len(stale_book_ids):
                    break  # 该分类所有过期书都已刷新
                params = {
                    "app_id": 2503,
                    "rank_list_type": 3,
                    "offset": 0,
                    "limit": 100,
                    "category_id": cat_id,
                    "gender": gender,
                    "rankMold": rank_mold,
                    "rank_version": "",
                }
                data = await fetch_json(RANK_URL, params)
                if not data or data.get("code") != 0:
                    logger.warning(f"封面兜底: 分类 {cat_id} mold={rank_mold} 拉取失败")
                    continue
                clean_books(data["data"]["book_list"])
                # 构建 book_id → thumbUri 映射
                thumb_map = {
                    str(item["bookId"]): item.get("thumbUri", "")
                    for item in data["data"]["book_list"]
                    if item.get("thumbUri")
                }
                # 更新过期书：取过期书与本批次返回书的交集
                targets = stale_book_ids & set(thumb_map.keys())
                if not targets:
                    continue
                update_result = await db.execute(
                    select(FanqieBook).where(FanqieBook.book_id.in_(list(targets)))
                )
                for book in update_result.scalars().all():
                    new_thumb = thumb_map.get(book.book_id)
                    if new_thumb and new_thumb != book.thumb_uri:
                        book.thumb_uri = new_thumb
                        book.crawled_at = datetime.now()
                        cat_refreshed += 1
                await asyncio.sleep(1.0)  # 防 limit

            refreshed += cat_refreshed
            await db.commit()
            logger.info(f"封面兜底: 分类 {cat_id} 刷新 {cat_refreshed}/{len(stale_book_ids)} 本")
            await asyncio.sleep(0.5)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"=== 番茄封面兜底完成，刷新 {refreshed}/{total_stale} 本，耗时 {elapsed:.1f}s ===")
    invalidate_novel_platform_stats_cache()
    return {"refreshed": refreshed, "stale_total": total_stale, "elapsed_seconds": elapsed}


async def full_sync() -> dict:
    """
    执行全量同步：
    1. 同步分类
    2. 按分类抓取阅读榜+新书榜
    3. 如果分类拉取失败（网络/反爬），降级为封面兜底刷新，
       确保至少把过期的 thumb_uri 续上，避免用户看到封面全部缺失。
    """
    logger.info("=== 番茄全量同步开始 ===")
    start = datetime.now()

    # Step 1: 分类
    categories = await sync_categories()

    # Step 2: 每个分类的阅读榜+新书榜
    await sync_category_books(categories)

    # Step 2.5: 如果分类同步失败（categories=0），降级为封面兜底
    cover_result = None
    if not categories:
        logger.warning("分类同步失败，降级为封面兜底刷新")
        try:
            cover_result = await refresh_stale_covers()
        except Exception as e:
            logger.error(f"封面兜底失败: {e}")

    # Step 3: 保存当日排名快照
    try:
        async with async_session() as db:
            snap_count = await _save_daily_snapshot(db)
            await db.commit()
        logger.info(f"保存排名快照 {snap_count} 条")
    except Exception as e:
        logger.error(f"保存快照失败: {e}")

    # Step 4: 清理 30 天前的快照
    try:
        async with async_session() as db:
            removed = await _cleanup_old_snapshots(db, days=30)
            await db.commit()
        if removed > 0:
            logger.info(f"清理旧快照 {removed} 条")
    except Exception as e:
        logger.error(f"清理快照失败: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"=== 番茄全量同步完成，耗时 {elapsed:.1f}s ===")
    invalidate_novel_platform_stats_cache()

    # 推送通知
    try:
        from app.services.notification_service import push_notification

        if categories:
            await push_notification(
                type="success",
                category="fanqie_sync",
                title="番茄数据同步完成",
                message=f"同步 {len(categories)} 个分类，耗时 {elapsed:.0f}s",
            )
        elif cover_result and cover_result.get("refreshed"):
            await push_notification(
                type="success",
                category="fanqie_sync",
                title="番茄封面兜底刷新完成",
                message=f"分类同步失败，已兜底刷新 {cover_result['refreshed']} 个过期封面，耗时 {elapsed:.0f}s",
            )
    except Exception:
        # 通知推送失败不影响主流程，但记录告警便于排查
        logger.warning("fanqie_sync success notification failed", exc_info=True)

    return {
        "categories": len(categories),
        "elapsed_seconds": elapsed,
        "cover_refresh": cover_result,
    }


# ── 快照逻辑 ──────────────────────────────────────────────────


async def _save_daily_snapshot(db: AsyncSession) -> int:
    """将当前排名数据保存为当日快照（幂等，重复调用不会重复写入）。"""
    today = date.today().isoformat()

    # 检查今天是否已有快照
    existing = await db.execute(select(FanqieRankSnapshot).where(FanqieRankSnapshot.snapshot_date == today).limit(1))
    if existing.scalar_one_or_none():
        logger.info(f"快照 {today} 已存在，跳过")
        return 0

    # 读取当前所有图书
    result = await db.execute(select(FanqieBook))
    books = result.scalars().all()

    count = 0
    for book in books:
        # 四个榜单各存一条
        for rank_type, pos_field in [
            ("male_reading", "male_reading_pos"),
            ("male_new", "male_new_pos"),
            ("female_reading", "female_reading_pos"),
            ("female_new", "female_new_pos"),
        ]:
            pos = getattr(book, pos_field, None)
            if pos is not None:
                snap = FanqieRankSnapshot(
                    snapshot_date=today,
                    book_id=book.book_id,
                    book_name=book.book_name,
                    rank_type=rank_type,
                    category_id=book.category_id,
                    position=pos,
                    read_count=book.read_count,
                    word_number=book.word_number,
                )
                db.add(snap)
                count += 1

    return count


async def _cleanup_old_snapshots(db: AsyncSession, days: int = 30) -> int:
    """删除 N 天前的快照。"""
    cutoff = (date.today() - __import__("datetime").timedelta(days=days)).isoformat()
    result = await db.execute(delete(FanqieRankSnapshot).where(FanqieRankSnapshot.snapshot_date < cutoff))
    return result.rowcount


# ── 供 scheduler 调用的入口 ────────────────────────────────────


def run_sync():
    """供 cronjob 同步的入口（同步运行）。"""
    return asyncio.run(full_sync())


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    result = asyncio.run(full_sync())
    print(json.dumps(result, ensure_ascii=False, indent=2))
