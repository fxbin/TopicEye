"""前端体验指标的口径与编排（#179）。

这里是**口径真源**：阈值、p75 定义、路径归一、值域校验都只此一处。
大盘 HTML 与 API 都从这里取数，不允许另抄一份阈值。

阈值取自 Google 核心网页指标，与浏览器侧 web-vitals v5 的判定一致：

======== ========== ==============
指标     good 上界  needs-improvement 上界
======== ========== ==============
LCP      2500 ms    4000 ms
INP      200 ms     500 ms
CLS      0.1        0.25
FCP      1800 ms    3000 ms
TTFB     800 ms     1800 ms
======== ========== ==============

判定语义与 web-vitals 一致：``value > needs-improvement 上界`` 记 poor，
``value > good 上界`` 记 needs-improvement，否则 good（边界值归 good 侧）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.web_vitals_repo import WebVitalsRepository

# (good 上界, needs-improvement 上界)
METRIC_THRESHOLDS: dict[str, tuple[float, float]] = {
    "LCP": (2500.0, 4000.0),
    "INP": (200.0, 500.0),
    "CLS": (0.1, 0.25),
    "FCP": (1800.0, 3000.0),
    "TTFB": (800.0, 1800.0),
}

# 时间类指标（毫秒）的值域上界；超过即视为异常值丢弃
TIME_METRIC_MAX_MS = 60_000.0
# CLS 是无量纲分值，正常远小于 1，给一个宽松上界用于挡脏数据
CLS_MAX = 100.0

NAVIGATION_TYPES = frozenset(
    {
        "navigate",
        "reload",
        "back-forward",
        "back-forward-cache",
        "prerender",
        "restore",
        "soft-navigation",
    }
)
DEVICE_CLASSES = frozenset({"mobile", "desktop", "tablet", "unknown"})

# 样本保留期（天）。逐条样本量级远大于聚合快照，单独设更长的窗口。
RETENTION_DAYS = 30

# 路径归一：纯数字段与 UUID 段视为 id
_ID_SEGMENT_RE = re.compile(r"^\d+$")
_UUID_SEGMENT_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class NormalizedSample:
    """通过校验、可落库的样本。"""

    metric: str
    value: float
    path: str
    rating: str
    navigation_type: str
    device_class: str


def classify_metric(metric: str, value: float) -> str:
    """按阈值把指标值判成 good / needs-improvement / poor。

    边界语义与 web-vitals v5 一致：等于 good 上界仍是 good，
    严格大于才是 needs-improvement。
    """
    good_max, needs_improvement_max = METRIC_THRESHOLDS[metric]
    if value > needs_improvement_max:
        return "poor"
    if value > good_max:
        return "needs-improvement"
    return "good"


def normalize_route_path(path: str) -> str:
    """把原始 pathname 归一成路由模板。

    ``/topics/123`` → ``/topics/[id]``；``/contents/5/reader`` → ``/contents/[id]/reader``；
    ``/`` 保持 ``/``。归一后路径基数不随内容 id 增长。

    非 id 的静态段（如 ``/admin/model-eval``）原样保留。
    """
    cleaned = path.split("?", 1)[0].split("#", 1)[0].strip()
    if not cleaned:
        return "/"
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    segments = [segment for segment in cleaned.split("/") if segment]
    normalized = [
        "[id]" if (_ID_SEGMENT_RE.match(segment) or _UUID_SEGMENT_RE.match(segment)) else segment
        for segment in segments
    ]
    return "/" + "/".join(normalized) if normalized else "/"


def validate_sample(
    metric: str,
    value: float,
    path: str,
    navigation_type: str,
    device_class: str,
) -> NormalizedSample | None:
    """校验并归一单条上报样本，非法返回 ``None``（调用方丢弃该条，不整批失败）。"""
    if metric not in METRIC_THRESHOLDS:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        return None
    max_value = CLS_MAX if metric == "CLS" else TIME_METRIC_MAX_MS
    if value > max_value:
        return None

    normalized_path = normalize_route_path(path)
    if len(normalized_path) > 200:
        return None

    if navigation_type not in NAVIGATION_TYPES:
        navigation_type = "navigate"
    if device_class not in DEVICE_CLASSES:
        device_class = "unknown"

    return NormalizedSample(
        metric=metric,
        value=value,
        path=normalized_path,
        rating=classify_metric(metric, value),
        navigation_type=navigation_type,
        device_class=device_class,
    )


async def record_samples(
    db: AsyncSession,
    samples: list[tuple[str, float, str, str, str]],
    user_id: int | None = None,
) -> tuple[int, int]:
    """落库一批上报样本，返回 (accepted, rejected)。

    ``samples`` 每项为 ``(metric, value, path, navigation_type, device_class)``。
    非法条目逐条丢弃，不影响同批合法条目。
    """
    repo = WebVitalsRepository(db)
    now = datetime.now(UTC)
    rows: list[dict] = []
    rejected = 0
    for metric, value, path, navigation_type, device_class in samples:
        normalized = validate_sample(metric, value, path, navigation_type, device_class)
        if normalized is None:
            rejected += 1
            continue
        rows.append(
            {
                "captured_at": now,
                "path": normalized.path,
                "metric": normalized.metric,
                "value": normalized.value,
                "rating": normalized.rating,
                "navigation_type": normalized.navigation_type,
                "device_class": normalized.device_class,
                "user_id": user_id,
            }
        )
    accepted = await repo.insert_samples(rows)
    return accepted, rejected


async def summarize(
    db: AsyncSession,
    hours: int = 24,
    navigation_type: str = "navigate",
    route_limit: int = 40,
) -> dict:
    """聚合窗口内的前端体验指标。

    返回纯 dict，由 API 层整形为响应模型。``navigation_type`` 传 ``all``
    表示不区分导航类型（默认只算首次加载，即经典 LCP 口径）。
    """
    repo = WebVitalsRepository(db)
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    metric_rows = await repo.percentiles_by_metric(cutoff, navigation_type)
    metrics = []
    for metric, p50, p75, p95, count in metric_rows:
        metrics.append(
            {
                "metric": metric,
                "p50": float(p50) if p50 is not None else None,
                "p75": float(p75) if p75 is not None else None,
                "p95": float(p95) if p95 is not None else None,
                "rating": _rating_of(metric, p75),
                "sample_count": int(count or 0),
            }
        )
    # 指标顺序固定：LCP 优先，其余按名称
    metrics.sort(key=lambda item: (_metric_order(item["metric"]), item["metric"]))

    path_rows = await repo.percentiles_by_path_metric(cutoff, navigation_type)
    per_path_counts: dict[str, int] = {}
    for _path, _metric, _p75, count in path_rows:
        per_path_counts[_path] = per_path_counts.get(_path, 0) + int(count or 0)
    top_paths = {
        path for path, _count in sorted(per_path_counts.items(), key=lambda kv: kv[1], reverse=True)[:route_limit]
    }

    routes = []
    for path, metric, p75, count in path_rows:
        if path not in top_paths or p75 is None:
            continue
        routes.append(
            {
                "path": path,
                "metric": metric,
                "p75": float(p75),
                "rating": _rating_of(metric, p75),
                "sample_count": int(count or 0),
            }
        )
    routes.sort(key=lambda item: (item["path"], _metric_order(item["metric"]), item["metric"]))

    total = await repo.count_samples(cutoff, navigation_type)
    return {
        "hours": hours,
        "navigation_type": navigation_type,
        "generated_at": datetime.now(UTC),
        "sample_count": total,
        "metrics": metrics,
        "routes": routes,
    }


async def cleanup_old_samples(db: AsyncSession) -> int:
    """删除超出保留期的样本，返回删除条数。"""
    repo = WebVitalsRepository(db)
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    return await repo.delete_older_than(cutoff)


def _metric_order(metric: str) -> int:
    """指标展示顺序：LCP 优先，其余按字母。"""
    return 0 if metric == "LCP" else 1


def _rating_of(metric: str, value: float | None) -> str:
    """按阈值判定档位；指标名不在阈值表内时给 unknown 而不是抛错。

    阈值表是唯一的档位真源，但数据里的 metric 受数据库 CHECK 约束，
    两者理论上同步；这里留一道兜底，避免将来加了指标忘了加阈值就把大盘打成 500。
    """
    if value is None or metric not in METRIC_THRESHOLDS:
        return "unknown"
    return classify_metric(metric, float(value))
