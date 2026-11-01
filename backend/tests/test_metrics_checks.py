"""监控大盘体检项判定的回归测试。

这三个用例对应三个真实踩过的坑，改判定逻辑时别把它们改回去：

1. **熔断器状态的大小写**。服务端给的是 ``closed`` / ``open`` / ``half_open``，
   大小写写错就会把熔断中的实例判成「正常」。
2. **延迟的单位**。接口返回秒，阈值按毫秒读；不换算的话 P95 检查永远不会触发。
3. **「没有样本」不等于「样本值是 0」**。LLM 一次都没调用时成功率是 0%，
   当成 0% 去比阈值就会被误判成「严重」。
"""

from __future__ import annotations

from typing import Any

from app.services.metrics_checks import (
    CHECK_DEFINITIONS,
    evaluate_checks,
    evaluate_state,
    summarize_checks,
    threshold_text,
)

# ── 构造快照载荷的辅助 ──


def _payload(
    *,
    total_requests: int = 0,
    error_rate: float = 0.0,
    latency: dict[str, Any] | None = None,
    llm: dict[str, Any] | None = None,
    db_pool: dict[str, Any] | None = None,
    circuit_state: str | None = "closed",
    slow_queries: int = 0,
    timeseries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "snapshot": {
            "http": {
                "total_requests": total_requests,
                "error_rate": error_rate,
                "latency": latency if latency is not None else {"p50": 0.0, "p95": 0.0, "count": 0},
            },
            "llm": llm if llm is not None else {"total_calls": 0, "success_rate": 0.0, "total_cost_usd": 0.0},
            "db_pool": db_pool if db_pool is not None else {"checked_out": 0, "size": 0, "utilization": 0.0},
        },
        "circuit_breaker": {"state": circuit_state} if circuit_state is not None else {},
        "slow_queries": slow_queries,
        "timeseries": timeseries if timeseries is not None else [],
    }


def _by_key(checks: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(c for c in checks if c["key"] == key)


class TestCircuitBreakerState:
    """熔断器状态是小写枚举，映射必须按小写匹配。"""

    def test_open_is_critical(self):
        checks = evaluate_checks(_payload(circuit_state="open"))
        assert _by_key(checks, "cb")["state"] == "crit"

    def test_half_open_is_warning(self):
        checks = evaluate_checks(_payload(circuit_state="half_open"))
        assert _by_key(checks, "cb")["state"] == "warn"

    def test_closed_is_ok(self):
        checks = evaluate_checks(_payload(circuit_state="closed"))
        assert _by_key(checks, "cb")["state"] == "ok"

    def test_missing_state_is_not_ok(self):
        """取不到状态时不能当成正常——那是「不知道」，不是「没问题」。"""
        checks = evaluate_checks(_payload(circuit_state=None))
        cb = _by_key(checks, "cb")
        assert cb["has_data"] is False
        assert cb["state"] == "info"


class TestLatencyUnit:
    """接口给秒，阈值按毫秒读。"""

    def test_p95_value_converted_to_milliseconds(self):
        checks = evaluate_checks(_payload(total_requests=10, latency={"p50": 0.1, "p95": 1.5, "count": 10}))
        p95 = _by_key(checks, "p95")
        assert p95["value"] == 1500.0
        assert p95["display"] == "1.50s"

    def test_p95_over_critical_threshold_is_critical(self):
        """1500ms 低于 2000ms 阈值 → 注意；2500ms → 严重。"""
        warn_case = evaluate_checks(_payload(total_requests=10, latency={"p50": 0.1, "p95": 1.5, "count": 10}))
        crit_case = evaluate_checks(_payload(total_requests=10, latency={"p50": 0.1, "p95": 2.5, "count": 10}))
        assert _by_key(warn_case, "p95")["state"] == "ok"
        assert _by_key(crit_case, "p95")["state"] == "crit"

    def test_p95_without_samples_has_no_data(self):
        checks = evaluate_checks(_payload(total_requests=0, latency={"p50": 0.0, "p95": 0.0, "count": 0}))
        p95 = _by_key(checks, "p95")
        assert p95["has_data"] is False
        assert p95["display"] == "—"
        assert p95["state"] == "info"

    def test_threshold_text_carries_unit(self):
        definition = next(d for d in CHECK_DEFINITIONS if d.key == "p95")
        assert threshold_text(definition) == "< 500ms 合格"


class TestNoDataIsNotZero:
    """没有样本时不能拿 0 去套阈值。"""

    def test_llm_success_rate_without_calls_is_not_critical(self):
        """一次都没调用 → 成功率 0%，但那是没数据，不是失败。"""
        checks = evaluate_checks(_payload(llm={"total_calls": 0, "success_rate": 0.0, "total_cost_usd": 0.0}))
        llmok = _by_key(checks, "llmok")
        assert llmok["has_data"] is False
        assert llmok["state"] == "info"
        assert llmok["display"] == "—"

    def test_llm_success_rate_with_calls_uses_threshold(self):
        failed = evaluate_checks(_payload(llm={"total_calls": 10, "success_rate": 90.0, "total_cost_usd": 0.1}))
        good = evaluate_checks(_payload(llm={"total_calls": 10, "success_rate": 100.0, "total_cost_usd": 0.1}))
        assert _by_key(failed, "llmok")["state"] == "crit"
        assert _by_key(good, "llmok")["state"] == "ok"

    def test_error_rate_without_requests_has_no_data(self):
        checks = evaluate_checks(_payload(total_requests=0, error_rate=0.0))
        errrate = _by_key(checks, "errrate")
        assert errrate["has_data"] is False
        assert errrate["state"] == "info"

    def test_db_utilization_without_pool_has_no_data(self):
        checks = evaluate_checks(_payload(db_pool={"checked_out": 0, "size": 0, "utilization": 0.0}))
        db = _by_key(checks, "db")
        assert db["has_data"] is False
        assert db["state"] == "info"

    def test_llm_cost_without_calls_has_no_data(self):
        checks = evaluate_checks(_payload(llm={"total_calls": 0, "success_rate": 0.0, "total_cost_usd": 0.0}))
        cost = _by_key(checks, "cost")
        assert cost["has_data"] is False
        assert cost["state"] == "info"


class TestInformationalChecks:
    """参考项（请求速率、成本）不参与合格判定。"""

    def test_informational_is_never_ok_state(self):
        checks = evaluate_checks(
            _payload(
                timeseries=[
                    {"ts": 1000.0, "total_requests": 10},
                    {"ts": 1010.0, "total_requests": 20},
                ],
                llm={"total_calls": 3, "success_rate": 100.0, "total_cost_usd": 0.25},
            )
        )
        assert _by_key(checks, "req")["state"] == "info"
        assert _by_key(checks, "cost")["state"] == "info"
        assert _by_key(checks, "cost")["display"] == "$0.2500"

    def test_informational_thresholds_are_blank(self):
        definition = next(d for d in CHECK_DEFINITIONS if d.key == "req")
        assert threshold_text(definition) == "—"


class TestRequestRate:
    def test_rate_from_two_samples(self):
        checks = evaluate_checks(
            _payload(
                timeseries=[
                    {"ts": 1000.0, "total_requests": 10},
                    {"ts": 1010.0, "total_requests": 30},
                ]
            )
        )
        req = _by_key(checks, "req")
        assert req["has_data"] is True
        assert req["value"] == 2.0
        assert req["display"] == "2.0 req/s"

    def test_single_sample_has_no_data(self):
        checks = evaluate_checks(_payload(timeseries=[{"ts": 1000.0, "total_requests": 10}]))
        assert _by_key(checks, "req")["has_data"] is False

    def test_counter_reset_has_no_data(self):
        """进程重启后累计值归零，差值为负——不是真实速率。"""
        checks = evaluate_checks(
            _payload(
                timeseries=[
                    {"ts": 1000.0, "total_requests": 500},
                    {"ts": 1010.0, "total_requests": 0},
                ]
            )
        )
        assert _by_key(checks, "req")["has_data"] is False


class TestSummary:
    def test_summary_separates_no_data_from_passed(self):
        checks = evaluate_checks(
            _payload(
                total_requests=10,
                error_rate=0.0,
                latency={"p50": 0.01, "p95": 0.05, "count": 10},
                llm={"total_calls": 0, "success_rate": 0.0, "total_cost_usd": 0.0},
                db_pool={"checked_out": 1, "size": 20, "utilization": 5.0},
            )
        )
        summary = summarize_checks(checks)
        # 没样本的 LLM 成功率与成本不算通过，也不算失败
        assert summary["no_data"] == 2
        assert summary["crit"] == 0
        assert summary["warn"] == 0
        assert summary["ok"] >= 4
        assert summary["total"] == len(CHECK_DEFINITIONS)

    def test_critical_counts_separately(self):
        checks = evaluate_checks(
            _payload(
                total_requests=10,
                error_rate=9.0,
                latency={"p50": 0.01, "p95": 3.0, "count": 10},
            )
        )
        summary = summarize_checks(checks)
        assert summary["crit"] == 2


class TestEvaluateState:
    def test_invert_semantics(self):
        """成功率类：越低越差。"""
        definition = next(d for d in CHECK_DEFINITIONS if d.key == "llmok")
        assert evaluate_state(definition, 90.0, True) == "crit"
        assert evaluate_state(definition, 97.0, True) == "warn"
        assert evaluate_state(definition, 99.5, True) == "ok"

    def test_boundary_is_not_a_violation(self):
        """阈值是严格大于才超标，正好等于阈值算合格。"""
        definition = next(d for d in CHECK_DEFINITIONS if d.key == "errrate")
        assert evaluate_state(definition, 1.0, True) == "ok"
        assert evaluate_state(definition, 1.01, True) == "warn"
        assert evaluate_state(definition, 5.0, True) == "warn"
        assert evaluate_state(definition, 5.01, True) == "crit"
