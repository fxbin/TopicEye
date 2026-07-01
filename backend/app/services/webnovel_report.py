"""
Webnovel report service — weekly history and rank movement analysis.

覆盖 5 个网文平台：
- 番茄小说 (fanqie)：独立 ORM + 日级排名快照，周内变化曲线最完整
- 七猫小说 (qimao)：独立 ORM，排名变化来自 API 的 index_change
- 知乎盐选 (zhihu)：独立 ORM，排名变化来自 rank_pos_diff
- 黑岩书城 (heiyan)：trending 体系，排名变化来自 TrendingSnapshot 快照对比
- 点众阅读 (ishugui)：trending 体系，排名变化来自 TrendingSnapshot 快照对比

跨平台涨跌榜采用"每平台配额制"（各取前 N），避免不同榜单量纲差异导致的偏倚。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone, UTC
from typing import Optional, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fanqie import FanqieBook, FanqieCategory, FanqieRankSnapshot
from app.models.qimao import QimaoBook
from app.models.trending import TrendingItem, TrendingSnapshot
from app.models.zhihu import ZhihuAlbum
# Shared cross-platform helpers extracted to _webnovel_common.py
from app.services._webnovel_common import (  # noqa: F401 — re-export for backward compat
    _PER_PLATFORM_QUOTA,
    _PLATFORM_LABELS,
    _TOP_LIMIT,
    _TRENDING_CATEGORY_FIELDS,
    _movement_item,
    _platform_label,
    _safe_int,
)




# ── 番茄（独立 ORM + 日级排名快照） ──────────────────────────────────


async def _fanqie_history(db: AsyncSession, start_date: str, end_date: str) -> dict:
    rows = await db.execute(
        select(FanqieRankSnapshot)
        .where(FanqieRankSnapshot.snapshot_date >= start_date)
        .where(FanqieRankSnapshot.snapshot_date <= end_date)
        .order_by(
            FanqieRankSnapshot.snapshot_date.asc(),
            FanqieRankSnapshot.rank_type.asc(),
            FanqieRankSnapshot.position.asc(),
        )
    )
    snapshots = rows.scalars().all()
    if not snapshots:
        return {
            "snapshot_dates": [],
            "daily_counts": [],
            "rank_movements": [],
            "category_mix": [],
            "read_count_delta": 0,
        }

    category_rows = await db.execute(select(FanqieCategory.fanqie_id, FanqieCategory.name))
    category_names = {row[0]: row[1] for row in category_rows.all()}

    dates = sorted({snap.snapshot_date for snap in snapshots})
    latest_date = dates[-1]
    daily_counter = Counter(snap.snapshot_date for snap in snapshots)
    latest_category_counter = Counter(
        category_names.get(snap.category_id, snap.category_id)
        for snap in snapshots
        if snap.snapshot_date == latest_date
    )

    by_book_rank: dict[tuple[str, str], list[FanqieRankSnapshot]] = defaultdict(list)
    for snap in snapshots:
        by_book_rank[(snap.book_id, snap.rank_type)].append(snap)

    movements = []
    read_count_delta = 0
    for (_, rank_type), items in by_book_rank.items():
        items.sort(key=lambda item: item.snapshot_date)
        first = items[0]
        latest = items[-1]
        if first.snapshot_date == latest.snapshot_date:
            continue
        change = first.position - latest.position
        first_reads = _safe_int(first.read_count)
        latest_reads = _safe_int(latest.read_count)
        read_count_delta += max(0, latest_reads - first_reads)
        if change == 0:
            continue
        movements.append(
            _movement_item(
                platform="fanqie",
                title=latest.book_name,
                author=None,
                category=category_names.get(latest.category_id, latest.category_id),
                rank_type=rank_type,
                position=latest.position,
                change=change,
                url=f"https://fanqienovel.com/page/{latest.book_id}",
            )
        )

    movements.sort(key=lambda item: abs(item["change"]), reverse=True)
    category_mix = [{"category": name, "count": count} for name, count in latest_category_counter.most_common(10)]

    return {
        "snapshot_dates": dates,
        "daily_counts": [{"date": day, "count": daily_counter.get(day, 0)} for day in dates],
        "rank_movements": movements[:24],
        "category_mix": category_mix,
        "read_count_delta": read_count_delta,
    }


async def _fanqie_current(db: AsyncSession) -> tuple[int, list[dict]]:
    rows = await db.execute(
        select(FanqieBook)
        .where(FanqieBook.rank_pos_diff != None)  # noqa: E711
        .order_by(func.abs(FanqieBook.rank_pos_diff).desc())
        .limit(30)
    )
    books = rows.scalars().all()
    movements = [
        _movement_item(
            platform="fanqie",
            title=book.book_name,
            author=book.author,
            category=book.category_name,
            rank_type=book.rank_type,
            position=book.current_pos,
            change=book.rank_pos_diff or 0,
            url=f"https://fanqienovel.com/page/{book.book_id}",
        )
        for book in books
        if book.rank_pos_diff
    ]
    count = (await db.execute(select(func.count()).select_from(FanqieBook))).scalar() or 0
    return count, movements


# ── 七猫（独立 ORM，index_change 来自 API） ──────────────────────────


async def _qimao_current(db: AsyncSession) -> tuple[int, list[dict], list[dict]]:
    rows = await db.execute(
        select(QimaoBook)
        .where(QimaoBook.index_change != None)  # noqa: E711
        .order_by(func.abs(QimaoBook.index_change).desc())
        .limit(30)
    )
    books = rows.scalars().all()
    movements = [
        _movement_item(
            platform="qimao",
            title=book.title,
            author=book.author,
            category=book.category1_name,
            rank_type=f"{book.channel}_{book.rank_type}",
            position=book.position,
            change=book.index_change or 0,
            url=f"https://www.qimao.com/shuku/{book.book_id}/",
        )
        for book in books
        if book.index_change
    ]
    count = (await db.execute(select(func.count()).select_from(QimaoBook))).scalar() or 0
    category_rows = await db.execute(
        select(QimaoBook.category1_name, func.count(QimaoBook.id).label("count"))
        .where(QimaoBook.category1_name != None)  # noqa: E711
        .group_by(QimaoBook.category1_name)
        .order_by(func.count(QimaoBook.id).desc())
        .limit(8)
    )
    categories = [{"category": row[0], "count": row[1]} for row in category_rows.all()]
    return count, movements, categories


# ── 知乎（独立 ORM，rank_pos_diff） ────────────────────────────────────


async def _zhihu_current(db: AsyncSession) -> tuple[int, list[dict], list[dict]]:
    rows = await db.execute(
        select(ZhihuAlbum)
        .where(ZhihuAlbum.rank_pos_diff != None)  # noqa: E711
        .order_by(func.abs(ZhihuAlbum.rank_pos_diff).desc(), ZhihuAlbum.position.asc())
        .limit(30)
    )
    albums = rows.scalars().all()
    movements = [
        _movement_item(
            platform="zhihu",
            title=album.title,
            author=album.author,
            category=album.category2_name or album.category1_name,
            rank_type=album.sort_type,
            position=album.position,
            change=album.rank_pos_diff or 0,
            url=album.url,
        )
        for album in albums
        if album.rank_pos_diff
    ]
    count = (await db.execute(select(func.count()).select_from(ZhihuAlbum))).scalar() or 0
    category_rows = await db.execute(
        select(ZhihuAlbum.category2_name, func.count(ZhihuAlbum.id).label("count"))
        .where(ZhihuAlbum.category2_name != None)  # noqa: E711
        .group_by(ZhihuAlbum.category2_name)
        .order_by(func.count(ZhihuAlbum.id).desc())
        .limit(8)
    )
    categories = [{"category": row[0], "count": row[1]} for row in category_rows.all()]
    return count, movements, categories


# ── 黑岩 / 点众（trending 体系，复用 TrendingSnapshot 快照） ──────────


async def _trending_history(db: AsyncSession, source: str, start_date: str, end_date: str) -> dict:
    """从 TrendingSnapshot 对比首末日 rank，算黑岩/点众的周内排名变化。

    快照结构（trending_snapshot.save_snapshot）每条只存 rank/title/url/hot_value。
    同一本书在多个 shelf/rank 中可能出现多次，此处取每个快照内的最佳 rank 去重。
    """
    rows = await db.execute(
        select(TrendingSnapshot)
        .where(TrendingSnapshot.source == source)
        .where(TrendingSnapshot.snapshot_date >= start_date)
        .where(TrendingSnapshot.snapshot_date <= end_date)
        .order_by(TrendingSnapshot.snapshot_date.asc(), TrendingSnapshot.snapshot_hour.asc())
    )
    snapshots = rows.scalars().all()
    if not snapshots:
        return {"snapshot_dates": [], "daily_counts": [], "rank_movements": []}

    dates = sorted({s.snapshot_date for s in snapshots})
    daily_counter = Counter(s.snapshot_date for s in snapshots)

    # 每个快照内，同 title 取最佳 rank（最小值），去重
    best_rank_per_snap: dict[tuple[date, str], tuple[int, str | None]] = {}
    for snap in snapshots:
        for item in snap.items or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            rank = item.get("rank", 0)
            key = (snap.snapshot_date, title)
            if key not in best_rank_per_snap or rank < best_rank_per_snap[key][0]:
                best_rank_per_snap[key] = (rank, item.get("url"))

    # 按 title 聚合首末日
    by_title: dict[str, list[tuple[date, int, str | None]]] = defaultdict(list)
    for (snap_date, title), (rank, url) in best_rank_per_snap.items():
        by_title[title].append((snap_date, rank, url))

    movements = []
    for title, entries in by_title.items():
        entries.sort(key=lambda e: e[0])
        first = entries[0]
        latest = entries[-1]
        if first[0] == latest[0]:
            continue
        change = first[1] - latest[1]  # 正 = 上升
        if change == 0:
            continue
        movements.append(
            _movement_item(
                platform=source,
                title=title,
                author=None,
                category=None,
                rank_type="rank",
                position=latest[1],
                change=change,
                url=latest[2] or None,
            )
        )

    movements.sort(key=lambda item: abs(item["change"]), reverse=True)

    return {
        "snapshot_dates": dates,
        "daily_counts": [{"date": str(day), "count": daily_counter.get(day, 0)} for day in dates],
        "rank_movements": movements,
    }


async def _trending_current(db: AsyncSession, source: str) -> tuple[int, list[dict]]:
    """从实时 TrendingItem 取样本数和分类分布。

    注意：TrendingItem.trend 对黑岩/点众是硬编码 'stable'，不可靠，
    排名变化统一走 _trending_history 的快照对比。
    """
    rows = await db.execute(select(TrendingItem).where(TrendingItem.source == source).order_by(TrendingItem.rank.asc()))
    items = rows.scalars().all()
    count = len(items)

    category_field = _TRENDING_CATEGORY_FIELDS.get(source)
    counter: Counter = Counter()
    for item in items:
        extra = item.extra or {}
        cat = None
        if category_field:
            cat = extra.get(category_field)
        if not cat:
            cat = "未分类"
        counter[cat] += 1

    categories = [{"category": k, "count": v} for k, v in counter.most_common(8)]
    return count, categories


# ── 跨平台汇总：归一化 top 涨跌（每平台配额制） ──────────────────────


def _normalize_top_movements(
    platform_movements: dict[str, list[dict]],
) -> tuple[list[dict], list[dict], int, int]:
    """每平台取前 quota 名，合并后再取 top N，避免量纲偏倚。

    返回 (top_risers, top_fallers, rising_count_total, falling_count_total)。
    rising/falling_count 是全量统计（含配额外），用于 summary 指标。
    """
    rising_pool: list[dict] = []
    falling_pool: list[dict] = []
    rising_count_total = 0
    falling_count_total = 0

    for _platform, movements in platform_movements.items():
        risers = sorted(
            [m for m in movements if m["change"] > 0],
            key=lambda m: m["change"],
            reverse=True,
        )
        fallers = sorted(
            [m for m in movements if m["change"] < 0],
            key=lambda m: m["change"],
        )
        rising_count_total += len(risers)
        falling_count_total += len(fallers)
        rising_pool.extend(risers[:_PER_PLATFORM_QUOTA])
        falling_pool.extend(fallers[:_PER_PLATFORM_QUOTA])

    top_risers = sorted(rising_pool, key=lambda m: m["change"], reverse=True)[:_TOP_LIMIT]
    top_fallers = sorted(falling_pool, key=lambda m: m["change"])[:_TOP_LIMIT]
    return top_risers, top_fallers, rising_count_total, falling_count_total


# ── 主入口 ────────────────────────────────────────────────────────────


async def build_weekly_webnovel_report(db: AsyncSession, days: int = 7) -> dict:
    """Build a read-only weekly webnovel report across all 5 webnovel platforms."""
    safe_days = max(3, min(days, 31))
    today = date.today()
    start = today - timedelta(days=safe_days - 1)
    start_iso = start.isoformat()
    end_iso = today.isoformat()

    # ── 番茄（有日级排名快照，变化曲线最完整） ──
    fanqie_history = await _fanqie_history(db, start_iso, end_iso)
    fanqie_count, fanqie_current = await _fanqie_current(db)

    # ── 七猫（index_change 来自 API） ──
    qimao_count, qimao_current, qimao_categories = await _qimao_current(db)

    # ── 知乎（rank_pos_diff） ──
    zhihu_count, zhihu_current, zhihu_categories = await _zhihu_current(db)

    # ── 黑岩（trending 快照对比） ──
    heiyan_history = await _trending_history(db, "heiyan", start_iso, end_iso)
    heiyan_count, heiyan_categories = await _trending_current(db, "heiyan")

    # ── 点众（trending 快照对比） ──
    ishugui_history = await _trending_history(db, "ishugui", start_iso, end_iso)
    ishugui_count, ishugui_categories = await _trending_current(db, "ishugui")

    # ── 每平台 movement 收集 ──
    # 番茄：合并快照变化 + 当前 rank_pos_diff
    fanqie_movements = list(fanqie_current)
    if fanqie_history["rank_movements"]:
        movement_keys = {(item["platform"], item["title"], item["rank_type"]) for item in fanqie_movements}
        fanqie_movements.extend(
            item
            for item in fanqie_history["rank_movements"]
            if (item["platform"], item["title"], item["rank_type"]) not in movement_keys
        )

    platform_movements: dict[str, list[dict]] = {
        "fanqie": fanqie_movements,
        "qimao": list(qimao_current),
        "zhihu": list(zhihu_current),
        "heiyan": list(heiyan_history.get("rank_movements", [])),
        "ishugui": list(ishugui_history.get("rank_movements", [])),
    }

    # ── 归一化 top 涨跌（每平台配额制） ──
    top_risers, top_fallers, rising_count, falling_count = _normalize_top_movements(platform_movements)

    # ── platform_summary ──
    platform_summary = [
        {
            "platform": "fanqie",
            "label": _platform_label("fanqie"),
            "item_count": fanqie_count,
            "rising_count": len([m for m in platform_movements["fanqie"] if m["change"] > 0]),
            "falling_count": len([m for m in platform_movements["fanqie"] if m["change"] < 0]),
            "history_days": len(fanqie_history["snapshot_dates"]),
        },
        {
            "platform": "qimao",
            "label": _platform_label("qimao"),
            "item_count": qimao_count,
            "rising_count": len([m for m in platform_movements["qimao"] if m["change"] > 0]),
            "falling_count": len([m for m in platform_movements["qimao"] if m["change"] < 0]),
            "history_days": 1 if qimao_count else 0,
        },
        {
            "platform": "zhihu",
            "label": _platform_label("zhihu"),
            "item_count": zhihu_count,
            "rising_count": len([m for m in platform_movements["zhihu"] if m["change"] > 0]),
            "falling_count": len([m for m in platform_movements["zhihu"] if m["change"] < 0]),
            "history_days": 1 if zhihu_count else 0,
        },
        {
            "platform": "heiyan",
            "label": _platform_label("heiyan"),
            "item_count": heiyan_count,
            "rising_count": len([m for m in platform_movements["heiyan"] if m["change"] > 0]),
            "falling_count": len([m for m in platform_movements["heiyan"] if m["change"] < 0]),
            "history_days": len(heiyan_history["snapshot_dates"]),
        },
        {
            "platform": "ishugui",
            "label": _platform_label("ishugui"),
            "item_count": ishugui_count,
            "rising_count": len([m for m in platform_movements["ishugui"] if m["change"] > 0]),
            "falling_count": len([m for m in platform_movements["ishugui"] if m["change"] < 0]),
            "history_days": len(ishugui_history["snapshot_dates"]),
        },
    ]

    return {
        "period": {
            "start": start_iso,
            "end": end_iso,
            "days": safe_days,
            "label": f"{start.month}月{start.day}日 ~ {today.month}月{today.day}日",
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total_items": fanqie_count + qimao_count + zhihu_count + heiyan_count + ishugui_count,
            "snapshot_days": len(fanqie_history["snapshot_dates"]),
            "rising_count": rising_count,
            "falling_count": falling_count,
            "read_count_delta": fanqie_history["read_count_delta"],
        },
        "platforms": platform_summary,
        "daily_counts": fanqie_history["daily_counts"],
        "top_risers": top_risers,
        "top_fallers": top_fallers,
        "category_mix": {
            "fanqie": fanqie_history["category_mix"],
            "qimao": qimao_categories,
            "zhihu": zhihu_categories,
            "heiyan": heiyan_categories,
            "ishugui": ishugui_categories,
        },
        "notes": [
            "番茄小说已保存日级排名快照，可展示周内排名变化曲线。",
            "七猫小说使用 API 返回的 index_change（最近一次同步的变化）。",
            "知乎盐选使用最近一次同步的排名变化（rank_pos_diff）。",
            "黑岩书城与点众阅读基于趋势雷达每日快照对比首末日排名，分类取自最新实时数据。",
            "跨平台涨跌榜采用每平台配额制（各取前 5），避免不同榜单量纲差异导致的偏倚。",
        ],
    }
