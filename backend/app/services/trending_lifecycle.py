"""趋势话题生命周期阶段标注（issue #173）。

输入某 topic 在 7 天快照窗口内的观测点序列，按四阶段决策树输出
stage + stage_reason（一句话中文依据）。判定是读取时纯函数，不落库。

## 归一口径

topic 归一**完全复用**跨平台共振分析（app.services.trending_cross）的标题
归一口径：jieba TF-IDF 关键词（_extract_keywords）+ 相似度
（_title_similarity）≥ 共振阈值（SIM_THRESHOLD）。实时条目标题与快照
条目标题满足该阈值即视为同一 topic；不做第二套归一。

**所有实时标题统一走相似扩展**：与「精确同题 ∪ {相似度 ≥ SIM_THRESHOLD}
的快照标题」合并观测点。精确同题只是保底成员（同题但关键词为空集时
相似度不可达，靠字面相等保住），不构成旁路——否则精确命中的标题会漏并
高相似变体，与走模糊路径的同簇标题得到不同结果。实现上用关键词倒排
索引缩小候选集，结果与两两全量比对严格等价（相似度无公共关键词时恒为
0，倒排索引不丢候选）。

## 决策树（互斥，按序）

1. 常青 evergreen：窗口内在榜天数 ≥ EVERGREEN_MIN_DAYS（5）。
2. 爆发 peaking：在榜 <5 天，且（最新排名较上一在榜日数值下降 ≥30%
   =名次上升，或最新排名进入前 PEAKING_TOP_RANK（10））。
3. 回落 declining：最新两个快照点排名数值上升=名次下降（「连续 ≥2 个
   快照点」指回落段至少覆盖 2 个点，即最近一次转变是名次下降；更长的
   连续回落不改变判定）。
4. 发酵 ferment：其余（新上榜、中段徘徊或排名持平）。

## 边界语义（与单测一一对应）

- 窗口：snapshot_date ≥ today - STAGE_WINDOW_DAYS 天（含当日、含边界
  当天）。STAGE_WINDOW_DAYS 直接取快照保留期 SNAPSHOT_RETENTION_DAYS，
  两侧不各自维护 7 天数字；today 锚点在 service（compute_trending_item_
  stages），repository 只按传入的 cutoff 过滤，避免日期语义在两层漂移。
- 在榜天数：窗口内出现过的**不同日期数**（非连续累计；快照缺天不影响，
  掉榜一天后回榜仍累计）。恰好 5 天 → 常青。
- 「较上一在榜日」：指序列中最新点的前一个快照日（通常为昨日；中途
  掉榜时为其上一在榜日，文案统一如实写「上一在榜日」）。
- 恰好 30%：上升比例 ≥30% 含等号（prev=10、latest=7 → 30% → 爆发）。
- 恰好前 10：最新排名 ≤10 含等号；排名 11 不算。
- 同日多平台/多小时快照：折叠为一天，取最好（最小）名次、最高热度。
- 排名持平：既不满足爆发（0% <30%）也不满足回落 → 发酵。
- 单快照点：无前一日可比，只可能经「进入前 10」判为爆发，否则发酵。
- 无窗口数据（窗口内无该 topic 的在榜记录、窗口为空、或标题关键词为空
  无法归一）：返回 None，API 上表现为 stage/stage_reason 为 null。
- 坏快照容错：单个快照行/条目形状非法时跳过该行/条目并打 warning，
  单个标题的阶段计算异常时降级为 null 并打 warning；不把 GET /trending
  打成 500，也不静默（warning 可见）。

快照信源排除：SYNC_EXCLUDED_SOURCES（heiyan/ishugui）的快照不参与
聚合，与 analyze_persistent_topics 的既有口径一致（网文书库快照陈旧且
书名语义上不属于热点话题，其条目 stage 恒为 null）。
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.trending_repo import TrendingRepository
from app.services.trending_cross import (
    SIM_THRESHOLD,
    _extract_keywords,
    _title_similarity,
)
from app.services.trending_scrapers import SYNC_EXCLUDED_SOURCES
from app.services.trending_snapshot import SNAPSHOT_RETENTION_DAYS

logger = logging.getLogger(__name__)

# ── 阈值常量（模块级，便于调参） ──────────────────────────────────────

# 阶段判定窗口（天）：直接挂钩快照保留期（cleanup_old_snapshots 按同一
# 常量清理），改保留期时窗口随之变化，不产生第二份 7 天数字。
STAGE_WINDOW_DAYS = SNAPSHOT_RETENTION_DAYS

# 常青门槛：窗口内在榜天数 ≥ 该值（含等号）
EVERGREEN_MIN_DAYS = 5

# 爆发：最新排名较前一快照日数值下降比例 ≥ 该值（含等号），即名次上升
PEAKING_RANK_RISE_RATIO = 0.30

# 爆发：最新排名进入前 N 名（≤ N 含等号）
PEAKING_TOP_RANK = 10


class TrendStage(enum.StrEnum):
    """趋势话题生命周期阶段。"""

    FERMENT = "ferment"  # 发酵
    PEAKING = "peaking"  # 爆发
    DECLINING = "declining"  # 回落
    EVERGREEN = "evergreen"  # 常青


@dataclass(frozen=True)
class TopicPoint:
    """某 topic 在一个快照点的观测（同日多条由 classify_topic_stage 折叠）。"""

    date: date
    rank: int
    hot_value: int = 0


@dataclass(frozen=True)
class TopicStageInfo:
    """一个 topic 的阶段判定结果。"""

    stage: TrendStage
    stage_reason: str


# ── 纯函数：决策树 ────────────────────────────────────────────────────


def classify_topic_stage(points: Sequence[TopicPoint]) -> TopicStageInfo | None:
    """按四阶段决策树判定 topic 生命周期阶段（纯函数，无 IO）。

    Args:
        points: 窗口内快照点序列，可含同日多条（跨平台/跨小时），
                顺序不限；空序列返回 None（无窗口数据）。

    Returns:
        TopicStageInfo 或 None（无观测点时）。
    """
    if not points:
        return None

    # 同日折叠：取最好（最小）名次、最高热度，再按日期升序
    by_day: dict[date, TopicPoint] = {}
    for p in points:
        current = by_day.get(p.date)
        if current is None:
            by_day[p.date] = p
        else:
            by_day[p.date] = TopicPoint(
                date=p.date,
                rank=min(p.rank, current.rank),
                hot_value=max(p.hot_value, current.hot_value),
            )
    daily = [by_day[d] for d in sorted(by_day)]

    days_on_list = len(daily)
    latest = daily[-1]
    latest_rank = latest.rank
    prev = daily[-2] if days_on_list >= 2 else None

    # 1. 常青：在榜天数 ≥5（窗口内语义）
    if days_on_list >= EVERGREEN_MIN_DAYS:
        return TopicStageInfo(
            stage=TrendStage.EVERGREEN,
            stage_reason=f"在榜 {days_on_list} 天 · 最新排名 {latest_rank}",
        )

    # 2. 爆发：排名较上一在榜日上升 ≥30%，或进入前 10
    if prev is not None and prev.rank > 0:
        rise_ratio = (prev.rank - latest_rank) / prev.rank
        if rise_ratio >= PEAKING_RANK_RISE_RATIO:
            pct = round(rise_ratio * 100)
            return TopicStageInfo(
                stage=TrendStage.PEAKING,
                stage_reason=f"排名较上一在榜日上升 {pct}% · 最新排名 {latest_rank}",
            )
    if latest_rank <= PEAKING_TOP_RANK:
        return TopicStageInfo(
            stage=TrendStage.PEAKING,
            stage_reason=f"进入前 {PEAKING_TOP_RANK} · 最新排名 {latest_rank}",
        )

    # 3. 回落：最新两个快照点排名数值上升=名次下降
    if prev is not None and latest_rank > prev.rank:
        return TopicStageInfo(
            stage=TrendStage.DECLINING,
            stage_reason=f"排名回落 {prev.rank} → {latest_rank} · 在榜 {days_on_list} 天",
        )

    # 4. 发酵：其余（新上榜 / 中段 / 持平）
    return TopicStageInfo(
        stage=TrendStage.FERMENT,
        stage_reason=f"在榜 {days_on_list} 天 · 最新排名 {latest_rank}",
    )


# ── 纯函数：topic 归一 + 窗口聚合 ─────────────────────────────────────


@dataclass(frozen=True)
class _SnapshotObservation:
    """窗口内一条快照观测：某标题在某日期的名次/热度。"""

    title: str
    date: date
    rank: int
    hot_value: int


def _collect_observations(snapshots: Iterable[object]) -> list[_SnapshotObservation]:
    """从快照行提取观测点，跳过 SYNC_EXCLUDED 信源、空标题与坏形状条目。

    snapshots 只需鸭子类型提供 snapshot_date / source / items 属性
    （TrendingSnapshot 或等价测试替身）。坏形状（items 非列表、条目非
    dict、rank/hot_value 非数值）跳过并打 warning，不让读取链路 500。
    """
    observations: list[_SnapshotObservation] = []
    for snap in snapshots:
        source_name = snap.source if isinstance(snap.source, str) else snap.source.value
        if source_name in SYNC_EXCLUDED_SOURCES:
            continue
        items = snap.items or []
        if not isinstance(items, list | tuple):
            logger.warning(
                "trending_lifecycle: 快照 items 形状异常（非列表），跳过该行 source=%s date=%s type=%s",
                source_name,
                snap.snapshot_date,
                type(items).__name__,
            )
            continue
        for item in items:
            if not isinstance(item, dict):
                logger.warning(
                    "trending_lifecycle: 快照条目非 dict，跳过 source=%s date=%s item=%r",
                    source_name,
                    snap.snapshot_date,
                    item,
                )
                continue
            try:
                title = str(item.get("title", "")).strip()
                if not title:
                    continue
                observations.append(
                    _SnapshotObservation(
                        title=title,
                        date=snap.snapshot_date,
                        rank=int(item.get("rank", 0)),
                        hot_value=int(item.get("hot_value", 0)),
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "trending_lifecycle: 快照条目字段非法，跳过 source=%s date=%s item=%r err=%s",
                    source_name,
                    snap.snapshot_date,
                    item,
                    exc,
                )
    return observations


def _match_and_classify(
    live_title: str,
    obs_by_title: dict[str, list[TopicPoint]],
    kw_by_title: dict[str, set[str]],
    index: dict[str, list[str]],
) -> TopicStageInfo | None:
    """归并 live 标题的观测点并判定阶段：精确同题 ∪ 相似度 ≥ 阈值。

    所有标题统一走这条路径：精确同题仅是保底成员（同题关键词为空集时
    相似度不可达），相似扩展照常进行，保证与两两全量比对严格等价。
    """
    matched = {live_title} if live_title in obs_by_title else set()
    live_kws = kw_by_title.get(live_title)
    if live_kws is None:
        live_kws = set(_extract_keywords(live_title))
    if live_kws:
        candidates = {t for kw in live_kws for t in index.get(kw, [])}
        for cand in candidates:
            if _title_similarity(live_kws, kw_by_title[cand]) >= SIM_THRESHOLD:
                matched.add(cand)
    if not matched:
        return None
    points = [p for t in matched for p in obs_by_title[t]]
    return classify_topic_stage(points)


def build_topic_stage_map(
    titles: Iterable[str],
    snapshots: Iterable[object],
) -> dict[str, TopicStageInfo | None]:
    """为一批实时条目标题计算生命周期阶段（纯函数，无 IO）。

    归一复用共振分析口径：每个标题与「精确同题 ∪ {关键词相似度 ≥
    SIM_THRESHOLD}」的快照标题合并观测点，统一路径、无旁路。窗口为空
    或标题在窗口内无匹配时对应值为 None；单个标题计算异常时降级为
    None 并打 warning，不影响其余标题。

    Args:
        titles: 实时条目标题（重复标题只算一次，返回 dict 以 strip 后
                标题为键）。
        snapshots: 窗口内快照行（TrendingSnapshot 或鸭子类型替身）。

    Returns:
        {strip 后标题: TopicStageInfo | None}
    """
    unique_titles = list({t.strip() for t in titles if t and t.strip()})
    observations = _collect_observations(snapshots)

    stage_map: dict[str, TopicStageInfo | None] = {t: None for t in unique_titles}
    if not observations:
        return stage_map

    # 按标题聚合观测点
    obs_by_title: dict[str, list[TopicPoint]] = {}
    for obs in observations:
        obs_by_title.setdefault(obs.title, []).append(TopicPoint(date=obs.date, rank=obs.rank, hot_value=obs.hot_value))

    # 关键词倒排索引覆盖**全部**快照标题：所有实时标题统一经它做相似
    # 扩展（无公共关键词的对比相似度恒为 0，索引不丢候选，结果与两两
    # 全量比对严格等价）。
    kw_by_title: dict[str, set[str]] = {}
    index: dict[str, list[str]] = {}
    for snap_title in obs_by_title:
        kws = set(_extract_keywords(snap_title))
        kw_by_title[snap_title] = kws
        for kw in kws:
            index.setdefault(kw, []).append(snap_title)

    for live_title in unique_titles:
        try:
            stage_map[live_title] = _match_and_classify(live_title, obs_by_title, kw_by_title, index)
        except Exception as exc:  # noqa: BLE001 - 单标题降级不拖垮整列表
            logger.warning("trending_lifecycle: 标题 %r 阶段计算失败，降级为 null：%s", live_title, exc)
            stage_map[live_title] = None

    return stage_map


# ── IO 编排：查询仍在 repository ─────────────────────────────────────


async def compute_trending_item_stages(
    db: AsyncSession,
    titles: Iterable[str],
) -> dict[str, TopicStageInfo | None]:
    """查询窗口快照并为标题计算阶段（查询下沉在 TrendingRepository）。

    窗口的 today 锚点与长度（STAGE_WINDOW_DAYS）都在本模块定义，repo 只按
    传入的 cutoff 过滤，两侧不会各自演化出日期语义。

    Returns:
        {strip 后标题: TopicStageInfo | None}；窗口无快照或标题为空时值全为 None。
    """
    unique_titles = {t.strip() for t in titles if t and t.strip()}
    if not unique_titles:
        return {}
    cutoff = date.today() - timedelta(days=STAGE_WINDOW_DAYS)
    snapshots = await TrendingRepository(db).list_snapshots_since(cutoff=cutoff)
    return build_topic_stage_map(unique_titles, snapshots)
