"""监控大盘的体检项判定：阈值、单位与状态映射的真源。

判定放在服务端而不是大盘的 JS 里，因为有三件事只有服务端知道：

1. **单位**。接口返回的延迟是秒，而阈值是按毫秒读的（500ms / 2000ms）。
   前端各写一份换算，就会出现「阈值比毫秒、值是秒」的静默失配——检查永远不触发。
2. **枚举的大小写**。熔断器状态是 ``closed`` / ``open`` / ``half_open``，
   前端拿字符串匹配，写错大小写就会把熔断中的实例判成「正常」。
3. **「没有样本」不等于「样本值是 0」**。LLM 一次都没调用时成功率是 0%，
   那是没数据；当成 0% 去比阈值就会被判成「严重」。

所以这里负责算「当前值 / 展示串 / 阈值 / 状态」，大盘只负责把结论画出来。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 判定状态。info 既用于「这项只是参考值，不参与合格判定」，
# 也用于「这一项当前没有样本」——两种情况都不该算作通过。
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_CRIT = "crit"
STATE_INFO = "info"

# 没有样本时展示的占位符
NO_VALUE = "—"


@dataclass(frozen=True)
class CheckDefinition:
    """一个体检项的定义：阈值、单位、严重程度映射。

    ``invert=True`` 表示越小越好（成功率这类）。
    ``state_map`` 用于枚举型指标（熔断器状态）。
    ``informational=True`` 表示这项只作参考，不参与合格判定。
    """

    key: str
    label: str
    hint: str
    unit: str = ""
    warn: float | None = None
    crit: float | None = None
    invert: bool = False
    informational: bool = False
    state_map: dict[str, str] | None = None
    trend: str | None = None
    logs: str = "app"


# ── 取值：从快照里挖出当前值，同时判断这一项到底有没有样本 ──


def _snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("snapshot") or {}


def _http(payload: dict[str, Any]) -> dict[str, Any]:
    return _snapshot(payload).get("http") or {}


def _llm(payload: dict[str, Any]) -> dict[str, Any]:
    return _snapshot(payload).get("llm") or {}


def _db_pool(payload: dict[str, Any]) -> dict[str, Any]:
    return _snapshot(payload).get("db_pool") or {}


def _errrate(payload: dict[str, Any]) -> tuple[float, bool]:
    """5xx 占比（%）。一次请求都没有时这个 0% 没有意义。"""
    http = _http(payload)
    return float(http.get("error_rate") or 0.0), bool(http.get("total_requests"))


def _http_p95(payload: dict[str, Any]) -> tuple[float, bool]:
    """HTTP P95 延迟（毫秒）。接口给的是秒，这里换算到毫秒再跟阈值比。"""
    latency = _http(payload).get("latency") or {}
    p95 = latency.get("p95")
    if p95 is None:
        return 0.0, False
    return float(p95) * 1000.0, bool(latency.get("count"))


def _llm_success_rate(payload: dict[str, Any]) -> tuple[float, bool]:
    """LLM 成功率（%）。没有调用记录时是 0%，但那是没数据不是失败。"""
    llm = _llm(payload)
    return float(llm.get("success_rate") or 0.0), bool(llm.get("total_calls"))


def _db_utilization(payload: dict[str, Any]) -> tuple[float, bool]:
    """连接池利用率（%）。池子还没初始化时算不出比例。"""
    pool = _db_pool(payload)
    return float(pool.get("utilization") or 0.0), bool(pool.get("size"))


def _slow_query_rate(payload: dict[str, Any]) -> tuple[float, bool]:
    """每小时慢查询数。

    慢查询是**进程启动至今的累计计数**，直接跟固定阈值比，进程跑久了必然「超标」——
    那是拿累计量比瞬时量，量纲不对。改用「累计数 ÷ 进程运行时长」得到速率，
    分子分母都从进程启动算起，口径对得上。

    刚启动不到一分钟时速率没有意义，算没有样本（而不是显示 0.0 次/小时）。
    """
    total = payload.get("slow_queries")
    if total is None:
        return 0.0, False
    uptime = float(_snapshot(payload).get("uptime_seconds") or 0)
    if uptime < 60:
        return 0.0, False
    return float(total) / (uptime / 3600.0), True


def _circuit_state(payload: dict[str, Any]) -> tuple[str, bool]:
    """熔断器状态。状态值由服务端给出，取不到就不算正常。"""
    breaker = payload.get("circuit_breaker") or {}
    state = breaker.get("state")
    return str(state or ""), bool(state)


def _request_rate(payload: dict[str, Any]) -> tuple[float, bool]:
    """最近两个采样点之间的请求速率（req/s）。

    进程重启后累计计数会归零，差值可能为负——那不是真实速率，算作没有数据。
    """
    series = payload.get("timeseries") or []
    if len(series) < 2:
        return 0.0, False
    previous, latest = series[-2], series[-1]
    elapsed = float(latest.get("ts") or 0) - float(previous.get("ts") or 0)
    if elapsed <= 0:
        return 0.0, False
    delta = float(latest.get("total_requests") or 0) - float(previous.get("total_requests") or 0)
    if delta < 0:
        return 0.0, False
    return delta / elapsed, True


def _llm_cost(payload: dict[str, Any]) -> tuple[float, bool]:
    """LLM 累计成本（USD）。没调用过时 0 美元是空话，不算读数。"""
    llm = _llm(payload)
    return float(llm.get("total_cost_usd") or 0.0), bool(llm.get("total_calls"))


# ── 展示串 ──


def format_ms(ms: float) -> str:
    """毫秒数的展示串：小于 1 秒用 ms，超过用 s。"""
    if ms < 1000:
        return f"{ms:.1f}ms" if ms < 10 else f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _fmt_errrate(value: float) -> str:
    return f"{value:.2f}%"


def _fmt_p95(value: float) -> str:
    return format_ms(value)


def _fmt_llm_success(value: float) -> str:
    return f"{value:.1f}%"


def _fmt_db_utilization(value: float) -> str:
    return f"{value:.0f}%"


def _fmt_slow(value: float) -> str:
    return f"{value:.1f} 次/小时"


def _fmt_circuit(value: Any) -> str:
    return str(value)


def _fmt_request_rate(value: float) -> str:
    return f"{value:.1f} req/s"


def _fmt_cost(value: float) -> str:
    return f"${value:.4f}"


# ── 体检项清单 ──

CHECK_DEFINITIONS: tuple[CheckDefinition, ...] = (
    CheckDefinition(
        key="errrate",
        label="错误率 (5xx)",
        hint="HTTP 5xx 占比",
        unit="%",
        warn=1,
        crit=5,
        trend="errors",
        logs="app",
    ),
    CheckDefinition(
        key="p95",
        label="HTTP P95 延迟",
        hint="请求耗时 95 分位",
        unit="ms",
        warn=500,
        crit=2000,
        trend="p95",
        logs="app",
    ),
    CheckDefinition(
        key="llmok",
        label="LLM 调用成功率",
        hint="DONE 占全部调用",
        unit="%",
        warn=99,
        crit=95,
        invert=True,
        trend="llmok",
        logs="llm",
    ),
    CheckDefinition(
        key="db",
        label="DB 连接池利用率",
        hint="已借出 / 池大小",
        unit="%",
        warn=80,
        crit=95,
        trend="db",
        logs="app",
    ),
    CheckDefinition(
        key="slow",
        label="慢查询",
        hint="每小时慢查询数（累计 ÷ 运行时长）",
        unit=" 次/小时",
        warn=10,
        crit=50,
        trend=None,
        logs="app",
    ),
    CheckDefinition(
        key="cb",
        label="熔断器",
        hint="LLM 熔断状态",
        # 已知状态要列全：closed 是正常，open 严重，half_open 注意。
        # 表里没有的状态值按 info 处理（认不出来 ≠ 没问题）。
        state_map={"closed": STATE_OK, "open": STATE_CRIT, "half_open": STATE_WARN},
        trend=None,
        logs="app",
    ),
    CheckDefinition(
        key="req",
        label="请求速率",
        hint="最近两个采样点的增量",
        unit=" req/s",
        informational=True,
        trend="reqrate",
        logs="app",
    ),
    CheckDefinition(
        key="cost",
        label="LLM 成本（累计）",
        hint="进程启动至今",
        unit="$",
        informational=True,
        trend="cost",
        logs="llm",
    ),
)

_VALUE_GETTERS: dict[str, Callable[[dict[str, Any]], tuple[Any, bool]]] = {
    "errrate": _errrate,
    "p95": _http_p95,
    "llmok": _llm_success_rate,
    "db": _db_utilization,
    "slow": _slow_query_rate,
    "cb": _circuit_state,
    "req": _request_rate,
    "cost": _llm_cost,
}

_FORMATTERS: dict[str, Callable[[Any], str]] = {
    "errrate": _fmt_errrate,
    "p95": _fmt_p95,
    "llmok": _fmt_llm_success,
    "db": _fmt_db_utilization,
    "slow": _fmt_slow,
    "cb": _fmt_circuit,
    "req": _fmt_request_rate,
    "cost": _fmt_cost,
}


def threshold_text(definition: CheckDefinition) -> str:
    """阈值说明：让人一眼看出「到什么程度算不合格」。

    用 ≤ / ≥ 而不是 < / >：判定是**严格**超过阈值才算超标，
    正好等于阈值算合格，文案得跟实现说同一件事。
    """
    if definition.informational:
        return NO_VALUE
    if definition.state_map is not None:
        return "熔断打开 = 严重 / 半开 = 注意"
    if definition.warn is None:
        return NO_VALUE
    if definition.invert:
        return f"≥ {definition.warn:g}{definition.unit} 合格"
    return f"≤ {definition.warn:g}{definition.unit} 合格"


def evaluate_state(definition: CheckDefinition, value: Any, has_data: bool) -> str:
    """判定一项的状态。

    没有样本一律算 info（待定），不拿 0 去套阈值——
    「没有调用记录」和「调用全失败」在成功率上都是 0%，但意思相反。
    """
    if not has_data:
        return STATE_INFO
    if definition.informational:
        return STATE_INFO
    if definition.state_map is not None:
        # 未知的状态值不能当成正常：那是「没认出来」，不是「没问题」
        return definition.state_map.get(str(value), STATE_INFO)
    if value is None or definition.warn is None or definition.crit is None:
        return STATE_INFO
    if definition.invert:
        if value < definition.crit:
            return STATE_CRIT
        if value < definition.warn:
            return STATE_WARN
        return STATE_OK
    if value > definition.crit:
        return STATE_CRIT
    if value > definition.warn:
        return STATE_WARN
    return STATE_OK


def evaluate_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """按定义逐项判定，返回可直接给前端渲染的结论列表。"""
    results: list[dict[str, Any]] = []
    for definition in CHECK_DEFINITIONS:
        value, has_data = _VALUE_GETTERS[definition.key](payload)
        state = evaluate_state(definition, value, has_data)
        results.append(
            {
                "key": definition.key,
                "label": definition.label,
                "hint": definition.hint,
                "unit": definition.unit,
                "value": value if has_data else None,
                "display": _FORMATTERS[definition.key](value) if has_data else NO_VALUE,
                "threshold": threshold_text(definition),
                "state": state,
                "has_data": has_data,
                "informational": definition.informational,
                "trend": definition.trend,
                "logs": definition.logs,
            }
        )
    return results


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, int]:
    """体检项的计数汇总，供顶部判定条直接用。

    ``checked`` 是真正参与合格判定的项数（排除参考项与没有样本的项）。
    有数据但判定不出档位的项（状态 info）单独记在 ``undetermined``，
    不混进 ``ok``——否则「没判出好坏」会被说成「检查通过」。
    """
    ok = warn = crit = no_data = informational = undetermined = 0
    for check in checks:
        if not check["has_data"]:
            no_data += 1
            continue
        if check["informational"]:
            informational += 1
            continue
        state = check["state"]
        if state == STATE_CRIT:
            crit += 1
        elif state == STATE_WARN:
            warn += 1
        elif state == STATE_OK:
            ok += 1
        else:
            undetermined += 1
    return {
        "total": len(checks),
        "checked": ok + warn + crit,
        "ok": ok,
        "warn": warn,
        "crit": crit,
        "no_data": no_data,
        "informational": informational,
        "undetermined": undetermined,
    }
