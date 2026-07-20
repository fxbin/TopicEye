"""
指标阈值告警 — 定期检查关键指标，超阈值时通过已有 webhook 通道推送。

复用 alerting.send_alert() 推送到飞书/钉钉/Slack。
告警规则内置默认值，可通过环境变量覆盖。

规则：
- 5xx 错误率 > 10% → error 告警
- LLM 熔断器 OPEN → error 告警
- DB 连接池利用率 > 90% → warning 告警
- LLM 成功率 < 50% → warning 告警
- 慢查询累计 > 100 → warning 告警
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# ── 告警阈值（可通过环境变量覆盖）──
_ALERT_ERROR_RATE_THRESHOLD = 10.0     # %
_ALERT_LLM_SUCCESS_RATE_MIN = 50.0     # %
_ALERT_DB_POOL_UTIL_THRESHOLD = 90.0   # %
_ALERT_SLOW_QUERY_THRESHOLD = 100

# 去重窗口：同一条规则 1 小时内只告警一次
_ALERT_DEDUP_SECONDS = 3600
_last_alerted: dict[str, float] = {}


def _should_alert(key: str) -> bool:
    now = time.monotonic()
    last = _last_alerted.get(key)
    if last is not None and (now - last) < _ALERT_DEDUP_SECONDS:
        return False
    _last_alerted[key] = now
    return True


async def check_metrics_thresholds() -> list[str]:
    """检查所有阈值规则，超限时推送告警。

    Returns:
        触发的告警 key 列表（空列表 = 一切正常）。
    """
    triggered: list[str] = []

    try:
        from app.core.request_metrics import get_collector

        collector = get_collector()
        snap = collector.snapshot()
    except Exception as exc:
        logger.warning("metrics_alerting: snapshot failed: %s", exc)
        return triggered

    # ── 规则 1: 5xx 错误率 ──
    err_rate = snap.get("http", {}).get("error_rate", 0)
    total_req = snap.get("http", {}).get("total_requests", 0)
    if total_req > 10 and err_rate > _ALERT_ERROR_RATE_THRESHOLD:
        key = "high_error_rate"
        if _should_alert(key):
            from app.services.alerting import send_alert

            await send_alert(
                title="HTTP 5xx 错误率过高",
                message=f"错误率 {err_rate:.1f}%（阈值 {_ALERT_ERROR_RATE_THRESHOLD}%）\n"
                f"总请求: {total_req}, 5xx 错误: {snap['http']['total_errors_5xx']}",
                alert_key=key,
                severity="error",
            )
            triggered.append(key)

    # ── 规则 2: LLM 熔断器状态 ──
    try:
        from app.services.llm.circuit_breaker import get_llm_circuit_breaker

        breaker = get_llm_circuit_breaker()
        cb_status = breaker.status()
        if cb_status.get("state") == "OPEN":
            key = "circuit_breaker_open"
            if _should_alert(key):
                from app.services.alerting import send_alert

                await send_alert(
                    title="LLM 熔断器已开启",
                    message=f"连续失败 {cb_status.get('failure_count', 0)}/"
                    f"{cb_status.get('failure_threshold', 5)} 次\n"
                    f"所有 LLM 调用已被熔断，等待冷却期后恢复",
                    alert_key=key,
                    severity="error",
                )
                triggered.append(key)
    except Exception:
        pass

    # ── 规则 3: DB 连接池利用率 ──
    db_pool = snap.get("db_pool", {})
    db_util = db_pool.get("utilization", 0)
    if db_util > _ALERT_DB_POOL_UTIL_THRESHOLD:
        key = "db_pool_high_utilization"
        if _should_alert(key):
            from app.services.alerting import send_alert

            await send_alert(
                title="数据库连接池利用率过高",
                message=f"利用率 {db_util:.1f}%（阈值 {_ALERT_DB_POOL_UTIL_THRESHOLD}%）\n"
                f"已借出: {db_pool.get('checked_out', 0)} / {db_pool.get('size', 0)}",
                alert_key=key,
                severity="warning",
            )
            triggered.append(key)

    # ── 规则 4: LLM 成功率 ──
    llm = snap.get("llm", {})
    llm_total = llm.get("total_calls", 0)
    llm_success = llm.get("success_rate", 100)
    if llm_total > 5 and llm_success < _ALERT_LLM_SUCCESS_RATE_MIN:
        key = "llm_low_success_rate"
        if _should_alert(key):
            from app.services.alerting import send_alert

            await send_alert(
                title="LLM 调用成功率偏低",
                message=f"成功率 {llm_success:.1f}%（阈值 {_ALERT_LLM_SUCCESS_RATE_MIN}%）\n"
                f"总调用: {llm_total}, 失败: {llm.get('total_failed', 0)}",
                alert_key=key,
                severity="warning",
            )
            triggered.append(key)

    # ── 规则 5: 慢查询累计 ──
    try:
        from app.core.slow_query import get_slow_count

        slow_count = get_slow_count()
        if slow_count > _ALERT_SLOW_QUERY_THRESHOLD:
            key = "high_slow_query_count"
            if _should_alert(key):
                from app.services.alerting import send_alert

                await send_alert(
                    title="慢查询累计数量过高",
                    message=f"慢查询计数: {slow_count}（阈值 {_ALERT_SLOW_QUERY_THRESHOLD}）\n"
                    f"可能存在数据库性能问题，建议检查 /metrics 端点",
                    alert_key=key,
                    severity="warning",
                )
                triggered.append(key)
    except Exception:
        pass

    return triggered
