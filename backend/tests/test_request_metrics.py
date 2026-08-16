"""RequestMetricsCollector 单元测试。

覆盖：
- normalize_path: 路径模板化（数字 ID / UUID / hex hash / slug）
- _percentile_from_histogram: 分位数计算（空 / 单桶 / 跨桶插值）
- _HistogramData: observe() 累积桶行为
- RequestMetricsCollector: record → snapshot → render_prometheus 全链路
- 时间序列采样: maybe_sample_timeseries 去重 + 环形缓冲
"""

from __future__ import annotations

import pytest

from app.core.request_metrics import (
    _DURATION_BUCKETS,
    RequestMetricsCollector,
    _HistogramData,
    _percentile_from_histogram,
    normalize_path,
)

# ── normalize_path ──


class TestNormalizePath:
    def test_numeric_id(self):
        assert normalize_path("/api/v1/topics/123") == "/api/v1/topics/{id}"

    def test_uuid(self):
        assert normalize_path("/api/v1/sources/550e8400-e29b-41d4-a716-446655440000") == "/api/v1/sources/{uuid}"

    def test_hex_hash(self):
        assert normalize_path("/api/v1/contents/0123456789abcdef0123456789abcdef") == "/api/v1/contents/{hex}"

    def test_slug_preserved(self):
        """Slug 路径（如 abc-123-def）不应被模板化。"""
        assert normalize_path("/api/v1/sources/abc-123-def") == "/api/v1/sources/abc-123-def"

    def test_root(self):
        assert normalize_path("/") == "/"

    def test_empty(self):
        assert normalize_path("") == "/"

    def test_multi_segment(self):
        assert normalize_path("/api/v1/users/42/posts/99") == "/api/v1/users/{id}/posts/{id}"


# ── _percentile_from_histogram ──


class TestPercentileFromHistogram:
    def test_empty(self):
        """空 histogram 返回 0。"""
        buckets = [0] * len(_DURATION_BUCKETS)
        result = _percentile_from_histogram(buckets, _DURATION_BUCKETS, 0, 50)
        assert result == 0.0

    def test_all_in_first_bucket(self):
        """所有值在第一个桶内，P50 应 <= 第一桶边界。"""
        buckets = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10]
        p50 = _percentile_from_histogram(buckets, _DURATION_BUCKETS, 10, 50)
        p95 = _percentile_from_histogram(buckets, _DURATION_BUCKETS, 10, 95)
        assert 0 < p50 <= 0.005
        assert 0 < p95 <= 0.005

    def test_linear_interpolation(self):
        """跨桶线性插值：5 reqs <= 5ms, 3 more <= 10ms, 2 more <= 25ms。"""
        buckets = [5, 8, 10, 10, 10, 10, 10, 10, 10, 10, 10]
        p50 = _percentile_from_histogram(buckets, _DURATION_BUCKETS, 10, 50)
        p95 = _percentile_from_histogram(buckets, _DURATION_BUCKETS, 10, 95)
        # P50: target=5, bucket[0]=5 → 0.005 * 5/5 = 0.005
        assert abs(p50 - 0.005) < 0.001
        # P95: target=9.5, bucket[1]=8<9.5, bucket[2]=10>=9.5
        # Interpolate between 0.01 and 0.025: ratio=(9.5-8)/(10-8)=0.75
        # P95 = 0.01 + 0.75 * 0.015 = 0.02125
        assert abs(p95 - 0.02125) < 0.001

    def test_exceeds_all_buckets(self):
        """值全部在最后一个桶，P99 通过线性插值应接近最后一个桶边界。"""
        buckets = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5]
        p99 = _percentile_from_histogram(buckets, _DURATION_BUCKETS, 5, 99)
        # Prometheus 线性插值：在 5.0 和 10.0 之间，ratio=0.99 → 9.95
        assert abs(p99 - 9.95) < 0.01


# ── _HistogramData ──


class TestHistogramData:
    def test_observe_first_bucket(self):
        hist = _HistogramData(buckets=_DURATION_BUCKETS)
        hist.observe(0.001)
        assert hist.count == 1
        assert hist.bucket_counts[0] == 1
        assert hist.sum_seconds == pytest.approx(0.001)

    def test_observe_multiple_buckets(self):
        hist = _HistogramData(buckets=_DURATION_BUCKETS)
        hist.observe(0.003)  # <= 0.005
        hist.observe(0.02)  # <= 0.025
        hist.observe(0.3)  # <= 0.5
        assert hist.count == 3
        assert hist.bucket_counts[0] == 1
        assert hist.bucket_counts[2] == 2  # 累积：0.003 和 0.02 都 <= 0.025
        assert hist.bucket_counts[6] == 3  # 累积：全部 <= 0.5

    def test_observe_exceeds_buckets(self):
        hist = _HistogramData(buckets=_DURATION_BUCKETS)
        hist.observe(20.0)  # 超过所有桶
        assert hist.count == 1
        # 不应落入任何桶（所有 bucket_counts 保持 0）
        assert all(bc == 0 for bc in hist.bucket_counts)
        assert hist.sum_seconds == pytest.approx(20.0)


# ── RequestMetricsCollector ──


class TestRequestMetricsCollector:
    def _fresh_collector(self) -> RequestMetricsCollector:
        """创建独立 collector 避免全局单例污染。"""
        return RequestMetricsCollector()

    def test_request_started_completed(self):
        c = self._fresh_collector()
        c.request_started()
        c.request_started()
        snap = c.snapshot()
        assert snap["in_progress"] == 2

        c.request_completed(method="GET", path="/api/v1/test", status=200, duration_seconds=0.01)
        snap = c.snapshot()
        assert snap["in_progress"] == 1
        assert snap["http"]["total_requests"] == 1

    def test_5xx_error_counted(self):
        c = self._fresh_collector()
        c.request_started()
        c.request_completed(method="GET", path="/api/v1/fail", status=500, duration_seconds=0.01)
        snap = c.snapshot()
        assert snap["http"]["total_errors_5xx"] == 1
        assert snap["http"]["error_rate"] > 0

    def test_rate_limit_hit(self):
        c = self._fresh_collector()
        c.rate_limit_hit("/api/v1/test")
        c.rate_limit_hit("/api/v1/test")
        snap = c.snapshot()
        assert snap["http"]["total_rate_limit_hits"] == 2

    def test_llm_call_recorded(self):
        c = self._fresh_collector()
        c.record_llm_call(
            scene="analysis",
            status="DONE",
            duration_seconds=1.5,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.002,
        )
        snap = c.snapshot()
        assert snap["llm"]["total_calls"] == 1
        assert snap["llm"]["total_done"] == 1
        assert snap["llm"]["success_rate"] == 100.0
        assert snap["llm"]["total_cost_usd"] == pytest.approx(0.002)
        assert snap["llm"]["total_input_tokens"] == 100
        assert snap["llm"]["total_output_tokens"] == 50

    def test_llm_failed_call(self):
        c = self._fresh_collector()
        c.record_llm_call(scene="analysis", status="FAILED", duration_seconds=0.5)
        c.record_llm_call(scene="analysis", status="DONE", duration_seconds=1.0)
        snap = c.snapshot()
        assert snap["llm"]["total_calls"] == 2
        assert snap["llm"]["total_done"] == 1
        assert snap["llm"]["total_failed"] == 1
        assert snap["llm"]["success_rate"] == 50.0

    def test_snapshot_latency_percentiles(self):
        c = self._fresh_collector()
        # 记录多个请求到不同延迟桶
        for dur in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5]:
            c.request_started()
            c.request_completed(method="GET", path="/api/v1/test", status=200, duration_seconds=dur)
        snap = c.snapshot()
        lat = snap["http"]["latency"]
        assert lat["count"] == 6
        assert lat["p50"] > 0
        assert lat["p95"] >= lat["p50"]
        assert lat["p99"] >= lat["p95"]

    def test_snapshot_llm_latency_percentiles(self):
        c = self._fresh_collector()
        for dur in [0.5, 1.0, 2.0, 5.0, 10.0]:
            c.record_llm_call(scene="test", status="DONE", duration_seconds=dur)
        snap = c.snapshot()
        lat = snap["llm"]["latency"]
        assert lat["count"] == 5
        assert lat["p50"] > 0
        assert lat["p95"] >= lat["p50"]
        assert lat["p99"] >= lat["p95"]

    def test_render_prometheus_format(self):
        c = self._fresh_collector()
        c.request_started()
        c.request_completed(method="GET", path="/api/v1/test", status=200, duration_seconds=0.01)
        c.record_llm_call(scene="test", status="DONE", duration_seconds=1.0)

        lines = c.render_prometheus()
        text = "\n".join(lines)

        # 验证 Prometheus text format 关键标记
        assert "# HELP topiceye_http_requests_total" in text
        assert "# TYPE topiceye_http_requests_total counter" in text
        assert "# HELP topiceye_http_request_duration_seconds" in text
        assert "# TYPE topiceye_http_request_duration_seconds histogram" in text
        assert "# HELP topiceye_llm_calls_total" in text
        assert "# HELP topiceye_llm_call_duration_seconds" in text
        assert "topiceye_http_requests_in_progress" in text

        # 验证 histogram 有 +Inf 桶
        assert 'le="+Inf"' in text

        # 验证有实际数据行
        assert any("topiceye_http_requests_total{" in line for line in lines)
        assert any("topiceye_llm_calls_total{" in line for line in lines)

    def test_render_prometheus_empty(self):
        """空 collector 不应崩溃。"""
        c = self._fresh_collector()
        lines = c.render_prometheus()
        assert len(lines) > 0  # 仍有 HELP/TYPE 头
        assert any("topiceye_http_requests_in_progress" in line for line in lines)

    def test_db_pool_snapshot(self):
        c = self._fresh_collector()
        c.update_db_pool_snapshot(checked_out=3, size=10)
        snap = c.snapshot()
        assert snap["db_pool"]["checked_out"] == 3
        assert snap["db_pool"]["size"] == 10
        assert snap["db_pool"]["utilization"] == 30.0


# ── 时间序列采样 ──


class TestTimeSeries:
    def test_maybe_sample_dedup(self):
        """连续调用 maybe_sample_timeseries 在间隔内不应重复采样。"""
        c = RequestMetricsCollector()
        c.maybe_sample_timeseries()
        c.maybe_sample_timeseries()  # 应被去重
        ts = c.timeseries()
        assert len(ts) == 1

    def test_timeseries_captures_current_state(self):
        c = RequestMetricsCollector()
        c.request_started()
        c.request_completed(method="GET", path="/api/v1/test", status=200, duration_seconds=0.01)
        c.maybe_sample_timeseries()
        ts = c.timeseries()
        assert len(ts) >= 1
        assert ts[-1]["total_requests"] == 1
