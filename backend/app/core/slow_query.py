
"""
慢查询监听 + 告警。

SQLAlchemy event listener 拦截每条 SQL 的执行时间：
- 超过 SLOW_QUERY_THRESHOLD_MS（默认 1000ms）记录 warning 日志
- 超过 SLOW_QUERY_ALERT_MS（默认 5000ms）触发 webhook 告警
  （复用 alerting 模块，1h 内同 sql 去重）
- 通过 /metrics 暴露 slow_queries_total 计数器
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.services.alerting import send_alert

logger = logging.getLogger(__name__)

# Defaults; override via env in deploy if needed
SLOW_QUERY_THRESHOLD_MS = 1000
SLOW_QUERY_ALERT_MS = 5000

_slow_count: int = 0
_alerted_keys: dict[str, float] = {}
_ALERT_DEDUP_SECONDS = 3600


def _now_ms() -> float:
    return time.monotonic() * 1000


def _register_listeners(engine: Engine) -> None:
    """Attach before/after cursor execute listeners to one engine."""
    if getattr(engine, "_slow_query_attached", False):
        return  # idempotent
    setattr(engine, "_slow_query_attached", True)

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._slow_query_start = _now_ms()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        global _slow_count
        start = getattr(context, "_slow_query_start", None)
        if start is None:
            return
        elapsed = _now_ms() - start
        if elapsed < SLOW_QUERY_THRESHOLD_MS:
            return
        _slow_count += 1

        # Truncate statement for log
        stmt_preview = " ".join(statement.split())[:300]
        logger.warning(
            "Slow query: %.0fms (>%dms): %s",
            elapsed, SLOW_QUERY_THRESHOLD_MS, stmt_preview,
        )

        if elapsed >= SLOW_QUERY_ALERT_MS:
            _maybe_alert(stmt_preview, elapsed)


def _maybe_alert(stmt_preview: str, elapsed_ms: float) -> None:
    """Alert webhook for severe slow queries (1h dedup)."""
    import asyncio

    # Dedup key: first 200 chars of statement + elapsed bucket
    bucket = int(elapsed_ms / 1000)  # 5s, 6s, 7s...
    alert_key = f"slow_query:{hash(stmt_preview[:200]) & 0xffffffff}:{bucket}"

    now = time.monotonic()
    last = _alerted_keys.get(alert_key)
    if last is not None and (now - last) < _ALERT_DEDUP_SECONDS:
        return
    _alerted_keys[alert_key] = now

    message = f"慢查询 ({elapsed_ms:.0f}ms): {stmt_preview[:200]}"
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context; schedule as background task
            asyncio.create_task(send_alert(
                title="慢查询告警",
                message=message,
                alert_key=alert_key,
                severity="warning",
            ))
        else:
            asyncio.run(send_alert(
                title="慢查询告警",
                message=message,
                alert_key=alert_key,
                severity="warning",
            ))
    except Exception as exc:
        logger.debug("Slow query alert skipped: %s", exc)


def get_slow_count() -> int:
    return _slow_count


def attach_to_all_engines() -> None:
    """Call once at startup. Iterates known engines and attaches listeners."""
    from app.core.database import engine
    _register_listeners(engine.sync_engine)
    # Also attach to any async engines (each has its own pool but listeners
    # fire on the underlying sync engine)
    logger.info("Slow query listener attached (threshold=%dms, alert=%dms)",
                SLOW_QUERY_THRESHOLD_MS, SLOW_QUERY_ALERT_MS)
