"""
请求级可观测性指标采集器（内存，无外部依赖）。

设计原则：
- 纯内存计数器，进程重启后归零（与现有 /metrics 风格一致）
- 线程安全：asyncio 单线程模型下无需锁，但提供了 thread-safe 递增接口
  以兼容 scheduler worker thread 场景
- 路径模板化：/api/v1/topics/123 → /api/v1/topics/{id}，避免高基数标签

暴露的指标（通过 /metrics 端点以 Prometheus text format 输出）：

HTTP 请求：
- topiceye_http_requests_total{method, path, status}      counter
- topiceye_http_request_duration_seconds{method, path}    histogram
- topiceye_http_requests_in_progress                      gauge
- topiceye_http_rate_limit_hits_total{path}               counter
- topiceye_http_errors_total{method, path, status_class}  counter (5xx only)

LLM 调用聚合：
- topiceye_llm_calls_total{scene, status}                 counter
- topiceye_llm_call_duration_seconds{scene}               histogram
- topiceye_llm_tokens_total{scene, direction}             counter (input/output)
- topiceye_llm_cost_total{scene}                          counter (USD)

数据库连接池：
- topiceye_db_pool_size{pool}                             gauge
- topiceye_db_pool_checked_out{pool}                      gauge
- topiceye_db_pool_overflow{pool}                         gauge
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

# ── Prometheus histogram bucket boundaries (seconds) ──
# 标准 Prometheus latency buckets，覆盖 5ms → 10s+
_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# LLM 调用延迟 bucket（LLM 调用通常 0.5s–30s）
_LLM_DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    30.0,
    60.0,
)

# ── Path 模板化正则 ──
_NUMERIC_ID = re.compile(r"^\d+$")
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HEX_HASH = re.compile(r"^[0-9a-f]{12,}$", re.IGNORECASE)


def _percentile_from_histogram(
    bucket_counts: list[int],
    buckets: tuple[float, ...],
    count: int,
    percentile: float,
) -> float:
    """从累积 histogram 桶中近似计算分位数。

    Prometheus 兼容的线性插值法：
    1. target = count * (percentile / 100)
    2. 找到第一个 bucket_counts[i] >= target 的桶
    3. 在前一个桶边界和当前桶边界之间线性插值
    """
    if count == 0:
        return 0.0
    target = count * (percentile / 100.0)
    for i, boundary in enumerate(buckets):
        if bucket_counts[i] >= target:
            if i == 0:
                # 第一个桶：从 0 到 boundary[0] 线性插值
                if bucket_counts[0] == 0:
                    return 0.0
                return boundary * (target / bucket_counts[0])
            prev_boundary = buckets[i - 1]
            prev_count = bucket_counts[i - 1]
            if bucket_counts[i] == prev_count:
                return boundary
            ratio = (target - prev_count) / (bucket_counts[i] - prev_count)
            return prev_boundary + ratio * (boundary - prev_boundary)
    # 超过所有桶边界
    return buckets[-1]


def normalize_path(raw_path: str) -> str:
    """将 URL path 规范化为低基数模板。

    /api/v1/topics/123        → /api/v1/topics/{id}
    /api/v1/sources/abc-123   → /api/v1/sources/{id}
    /analyses/jobs/abc123...  → /analyses/jobs/{id}

    保留 query string 不参与（labels 不含 query）。
    """
    if not raw_path:
        return "/"

    segments = raw_path.strip("/").split("/")
    normalized: list[str] = []
    for seg in segments:
        if not seg:
            continue
        if _NUMERIC_ID.match(seg):
            normalized.append("{id}")
        elif _UUID_PATTERN.match(seg):
            normalized.append("{uuid}")
        elif _HEX_HASH.match(seg):
            normalized.append("{hex}")
        else:
            normalized.append(seg)
    return "/" + "/".join(normalized)


@dataclass
class _HistogramData:
    """累积 histogram 桶（Prometheus 兼容：每个 bucket 含 <= 该边界值的累计计数）。

    buckets 由调用方传入，兼容 HTTP 和 LLM 两种延迟分布。
    """

    buckets: tuple[float, ...] = field(default_factory=lambda: _DURATION_BUCKETS)
    bucket_counts: list[int] = field(init=False)
    sum_seconds: float = 0.0
    count: int = 0

    def __post_init__(self) -> None:
        self.bucket_counts = [0] * len(self.buckets)

    def observe(self, duration_seconds: float) -> None:
        """记录一次观测值到累积桶。"""
        for i, boundary in enumerate(self.buckets):
            if duration_seconds <= boundary:
                self.bucket_counts[i] += 1
        self.sum_seconds += duration_seconds
        self.count += 1

    def merged_bucket_counts(self) -> list[int]:
        """返回桶计数副本（供合并多个 histogram 时使用）。"""
        return list(self.bucket_counts)


# ── 时间序列环形缓冲 ──
# 每 10s 采样一次，保留最近 180 个点 = 30 分钟趋势
_TS_INTERVAL = 10.0
_TS_MAX_POINTS = 180


@dataclass
class _TimeSeriesPoint:
    """单个时间序列采样点。"""

    ts: float  # monotonic timestamp
    wall_ts: float  # epoch seconds (for display)
    in_progress: int = 0
    total_requests: int = 0
    total_errors_5xx: int = 0
    total_rate_limit_hits: int = 0
    total_llm_calls: int = 0
    total_llm_cost_usd: float = 0.0
    total_llm_tokens: int = 0
    db_pool_checked_out: int = 0
    db_pool_size: int = 0


class RequestMetricsCollector:
    """进程内请求指标采集器（单例）。

    在 asyncio 事件循环中调用 record_* 方法无需加锁（单线程）。
    scheduler 的 thread pool 场景使用 _lock 保护。

    除了累计计数器，还维护一个时间序列环形缓冲（每 10s 采样一次，
    保留 30 分钟），供内置监控大盘绘制趋势图。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # HTTP 请求计数: {(method, path, status): count}
        self._request_counts: dict[tuple[str, str, int], int] = defaultdict(int)

        # HTTP 请求延迟 histogram: {(method, path): _HistogramData}
        self._request_durations: dict[tuple[str, str], _HistogramData] = defaultdict(
            lambda: _HistogramData(buckets=_DURATION_BUCKETS)
        )

        # 当前在途请求数
        self._in_progress: int = 0

        # 限流命中计数: {path: count}
        self._rate_limit_hits: dict[str, int] = defaultdict(int)

        # 5xx 错误计数: {(method, path, status_class): count}
        self._error_counts: dict[tuple[str, str, str], int] = defaultdict(int)

        # LLM 调用计数: {(scene, status): count}
        self._llm_call_counts: dict[tuple[str, str], int] = defaultdict(int)

        # LLM 调用延迟: {scene: _HistogramData}
        self._llm_durations: dict[str, _HistogramData] = defaultdict(
            lambda: _HistogramData(buckets=_LLM_DURATION_BUCKETS)
        )

        # LLM token 用量: {(scene, direction): count}
        self._llm_token_counts: dict[tuple[str, str], int] = defaultdict(int)

        # LLM 成本累计: {scene: cost_usd}
        self._llm_cost_total: dict[str, float] = defaultdict(float)

        # 时间序列环形缓冲
        self._ts_buffer: deque[_TimeSeriesPoint] = deque(maxlen=_TS_MAX_POINTS)
        self._last_ts_sample: float = 0.0

        self._started_at = time.monotonic()

        # DB 连接池快照（由 /metrics 端点更新）
        self._db_pool_checked_out: int = 0
        self._db_pool_size: int = 0

    # ── HTTP 请求指标 ──

    def request_started(self) -> None:
        with self._lock:
            self._in_progress += 1

    def request_completed(
        self,
        *,
        method: str,
        path: str,
        status: int,
        duration_seconds: float,
    ) -> None:
        norm_path = normalize_path(path)
        with self._lock:
            self._in_progress = max(0, self._in_progress - 1)
            self._request_counts[(method, norm_path, status)] += 1

            hist = self._request_durations[(method, norm_path)]
            hist.observe(duration_seconds)

            if status >= 500:
                status_class = f"{status // 100}xx"
                self._error_counts[(method, norm_path, status_class)] += 1

    def rate_limit_hit(self, path: str) -> None:
        norm_path = normalize_path(path)
        with self._lock:
            self._rate_limit_hits[norm_path] += 1

    # ── LLM 调用指标 ──

    def record_llm_call(
        self,
        *,
        scene: str,
        status: str,
        duration_seconds: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        with self._lock:
            self._llm_call_counts[(scene, status)] += 1

            hist = self._llm_durations[scene]
            hist.observe(duration_seconds)

            if input_tokens:
                self._llm_token_counts[(scene, "input")] += input_tokens
            if output_tokens:
                self._llm_token_counts[(scene, "output")] += output_tokens
            if cost_usd:
                self._llm_cost_total[scene] += cost_usd

    # ── Prometheus text format 输出 ──

    def render_prometheus(self) -> list[str]:
        """渲染所有指标为 Prometheus text format 行列表。"""
        lines: list[str] = []

        def _render_histogram(
            metric_name: str,
            help_text: str,
            durations: dict,
            label_keys: list[str],
        ) -> None:
            """通用 histogram 渲染（HTTP / LLM 共用）。"""
            lines.append(f"# HELP {metric_name} {help_text}")
            lines.append(f"# TYPE {metric_name} histogram")
            for key, hist in sorted(durations.items()):
                labels = ",".join(f'{k}="{v}"' for k, v in zip(label_keys, key, strict=False))
                for i, boundary in enumerate(hist.buckets):
                    lines.append(f'{metric_name}_bucket{{{labels},le="{boundary}"}} {hist.bucket_counts[i]}')
                lines.append(f'{metric_name}_bucket{{{labels},le="+Inf"}} {hist.count}')
                lines.append(f"{metric_name}_sum{{{labels}}} {hist.sum_seconds:.6f}")
                lines.append(f"{metric_name}_count{{{labels}}} {hist.count}")

        with self._lock:
            # ── HTTP 请求总数 ──
            lines.append("# HELP topiceye_http_requests_total Total HTTP requests by method, path, status")
            lines.append("# TYPE topiceye_http_requests_total counter")
            for (method, path, status), count in sorted(self._request_counts.items()):
                lines.append(
                    f'topiceye_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )

            # ── HTTP 请求延迟 histogram ──
            _render_histogram(
                "topiceye_http_request_duration_seconds",
                "HTTP request latency distribution",
                self._request_durations,
                ["method", "path"],
            )

            # ── 在途请求数 ──
            lines.append("# HELP topiceye_http_requests_in_progress Current in-flight HTTP requests")
            lines.append("# TYPE topiceye_http_requests_in_progress gauge")
            lines.append(f"topiceye_http_requests_in_progress {self._in_progress}")

            # ── 限流命中 ──
            lines.append("# HELP topiceye_http_rate_limit_hits_total Requests rejected by rate limiter")
            lines.append("# TYPE topiceye_http_rate_limit_hits_total counter")
            for path, count in sorted(self._rate_limit_hits.items()):
                lines.append(f'topiceye_http_rate_limit_hits_total{{path="{path}"}} {count}')

            # ── 5xx 错误 ──
            lines.append("# HELP topiceye_http_errors_total HTTP 5xx errors by method, path, status_class")
            lines.append("# TYPE topiceye_http_errors_total counter")
            for (method, path, status_class), count in sorted(self._error_counts.items()):
                lines.append(
                    f'topiceye_http_errors_total{{method="{method}",path="{path}",status_class="{status_class}"}} {count}'
                )

            # ── LLM 调用总数 ──
            lines.append("# HELP topiceye_llm_calls_total LLM API calls by scene and status")
            lines.append("# TYPE topiceye_llm_calls_total counter")
            for (scene, status), count in sorted(self._llm_call_counts.items()):
                lines.append(f'topiceye_llm_calls_total{{scene="{scene}",status="{status}"}} {count}')

            # ── LLM 调用延迟 histogram ──
            _render_histogram(
                "topiceye_llm_call_duration_seconds",
                "LLM call latency distribution",
                self._llm_durations,
                ["scene"],
            )

            # ── LLM token 用量 ──
            lines.append("# HELP topiceye_llm_tokens_total LLM token usage by scene and direction")
            lines.append("# TYPE topiceye_llm_tokens_total counter")
            for (scene, direction), count in sorted(self._llm_token_counts.items()):
                lines.append(f'topiceye_llm_tokens_total{{scene="{scene}",direction="{direction}"}} {count}')

            # ── LLM 成本 ──
            lines.append("# HELP topiceye_llm_cost_total LLM cumulative cost in USD by scene")
            lines.append("# TYPE topiceye_llm_cost_total counter")
            for scene, cost in sorted(self._llm_cost_total.items()):
                lines.append(f'topiceye_llm_cost_total{{scene="{scene}"}} {cost:.6f}')

        return lines

    def update_db_pool_snapshot(self, checked_out: int, size: int) -> None:
        """由 /metrics 端点在采集 DB 池指标时同步写入（非加锁路径）。"""
        with self._lock:
            self._db_pool_checked_out = checked_out
            self._db_pool_size = size

    def maybe_sample_timeseries(self) -> None:
        """如果距上次采样已超过 _TS_INTERVAL 秒，追加一个采样点到环形缓冲。

        由 /api/v1/metrics/snapshot 端点每次被请求时调用（dashboard 轮询驱动采样）。
        这样不需要额外的后台定时器——仪表盘看的时候才有数据，不看的时候不浪费内存。
        """
        now = time.monotonic()
        if now - self._last_ts_sample < _TS_INTERVAL:
            return
        with self._lock:
            self._last_ts_sample = now

            self._ts_buffer.append(
                _TimeSeriesPoint(
                    ts=now,
                    wall_ts=time.time(),
                    in_progress=self._in_progress,
                    total_requests=sum(self._request_counts.values()),
                    total_errors_5xx=sum(self._error_counts.values()),
                    total_rate_limit_hits=sum(self._rate_limit_hits.values()),
                    total_llm_calls=sum(self._llm_call_counts.values()),
                    total_llm_cost_usd=sum(self._llm_cost_total.values()),
                    total_llm_tokens=sum(self._llm_token_counts.values()),
                    db_pool_checked_out=self._db_pool_checked_out,
                    db_pool_size=self._db_pool_size,
                )
            )

    def timeseries(self) -> list[dict]:
        """返回时间序列数据（JSON 可序列化）。"""
        with self._lock:
            return [
                {
                    "ts": p.wall_ts,
                    "in_progress": p.in_progress,
                    "total_requests": p.total_requests,
                    "total_errors_5xx": p.total_errors_5xx,
                    "total_rate_limit_hits": p.total_rate_limit_hits,
                    "total_llm_calls": p.total_llm_calls,
                    "total_llm_cost_usd": round(p.total_llm_cost_usd, 6),
                    "total_llm_tokens": p.total_llm_tokens,
                    "db_pool_checked_out": p.db_pool_checked_out,
                    "db_pool_size": p.db_pool_size,
                }
                for p in self._ts_buffer
            ]

    @staticmethod
    def _merge_and_percentiles(
        durations: dict,
        buckets: tuple[float, ...],
    ) -> tuple[float, float, float, int]:
        """合并多个 histogram 的桶计数，返回 (p50, p95, p99, count)。"""
        merged = [0] * len(buckets)
        total_count = 0
        for hist in durations.values():
            for i, bc in enumerate(hist.bucket_counts):
                merged[i] += bc
            total_count += hist.count
        p50 = _percentile_from_histogram(merged, buckets, total_count, 50)
        p95 = _percentile_from_histogram(merged, buckets, total_count, 95)
        p99 = _percentile_from_histogram(merged, buckets, total_count, 99)
        return p50, p95, p99, total_count

    def snapshot(self) -> dict:
        """返回完整快照（供 JSON API 和内置监控大盘使用）。"""
        with self._lock:
            total_req = sum(self._request_counts.values())
            total_err = sum(self._error_counts.values())
            total_rl = sum(self._rate_limit_hits.values())
            total_llm = sum(self._llm_call_counts.values())
            total_llm_done = sum(v for (s, st), v in self._llm_call_counts.items() if st == "DONE")
            total_llm_failed = sum(v for (s, st), v in self._llm_call_counts.items() if st == "FAILED")
            total_cost = sum(self._llm_cost_total.values())
            total_tokens_in = sum(v for (s, d), v in self._llm_token_counts.items() if d == "input")
            total_tokens_out = sum(v for (s, d), v in self._llm_token_counts.items() if d == "output")

            # 按 path 聚合 top 请求
            path_counts: dict[str, int] = defaultdict(int)
            for (method, path, _status), count in self._request_counts.items():
                path_counts[f"{method} {path}"] += count
            top_paths = sorted(path_counts.items(), key=lambda x: -x[1])[:15]

            # 按 scene 聚合 LLM 调用
            llm_by_scene: dict[str, dict] = defaultdict(lambda: {"done": 0, "failed": 0, "cost": 0.0, "tokens": 0})
            for (scene, status), count in self._llm_call_counts.items():
                if status == "DONE":
                    llm_by_scene[scene]["done"] += count
                elif status == "FAILED":
                    llm_by_scene[scene]["failed"] += count
            for scene, cost in self._llm_cost_total.items():
                llm_by_scene[scene]["cost"] = round(cost, 6)
            for (scene, _direction), count in self._llm_token_counts.items():
                llm_by_scene[scene]["tokens"] += count

            # ── HTTP 延迟分位数（从全局聚合 histogram 计算）──
            http_p50, http_p95, http_p99, http_count = self._merge_and_percentiles(
                self._request_durations, _DURATION_BUCKETS
            )

            # ── LLM 延迟分位数 ──
            llm_p50, llm_p95, llm_p99, llm_count = self._merge_and_percentiles(
                self._llm_durations, _LLM_DURATION_BUCKETS
            )

            return {
                "uptime_seconds": round(time.monotonic() - self._started_at, 1),
                "in_progress": self._in_progress,
                "http": {
                    "total_requests": total_req,
                    "total_errors_5xx": total_err,
                    "total_rate_limit_hits": total_rl,
                    "error_rate": round(total_err / max(total_req, 1) * 100, 2),
                    "top_paths": [{"path": p, "count": c} for p, c in top_paths],
                    "latency": {
                        "p50": round(http_p50, 4),
                        "p95": round(http_p95, 4),
                        "p99": round(http_p99, 4),
                        "count": http_count,
                    },
                },
                "llm": {
                    "total_calls": total_llm,
                    "total_done": total_llm_done,
                    "total_failed": total_llm_failed,
                    "success_rate": round(total_llm_done / max(total_llm, 1) * 100, 2),
                    "total_cost_usd": round(total_cost, 6),
                    "total_input_tokens": total_tokens_in,
                    "total_output_tokens": total_tokens_out,
                    "by_scene": dict(llm_by_scene),
                    "latency": {
                        "p50": round(llm_p50, 4),
                        "p95": round(llm_p95, 4),
                        "p99": round(llm_p99, 4),
                        "count": llm_count,
                    },
                },
                "db_pool": {
                    "checked_out": self._db_pool_checked_out,
                    "size": self._db_pool_size,
                    "utilization": round(self._db_pool_checked_out / max(self._db_pool_size, 1) * 100, 1),
                },
            }


# ── 全局单例 ──

_collector: RequestMetricsCollector | None = None


def get_collector() -> RequestMetricsCollector:
    global _collector
    if _collector is None:
        _collector = RequestMetricsCollector()
    return _collector
