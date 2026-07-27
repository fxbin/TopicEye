"""
结构化日志配置。

通过 LOG_FORMAT 环境变量切换：
- text（默认）：人类可读，dev 友好
- json：每行一条 JSON，便于 Loki / Elasticsearch / Datadog 聚合

所有 LogRecord 都会自动带 request_id（来自 RequestIdFilter in main.py）。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON-structured log formatter for production log aggregation."""

    # Standard LogRecord attributes to exclude from the JSON payload
    _RESERVED = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.filename:
            payload["source"] = f"{record.filename}:{record.lineno}"

        # Any custom extras attached to the record (e.g. via logger.info("msg", extra={...}))
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_format: str = "text", level: int = logging.INFO) -> None:
    """Configure root logger with the specified format.

    Idempotent: safe to call multiple times (e.g. from tests).
    """
    root = logging.getLogger()
    # Remove all existing handlers (avoid duplicate output)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        # Human-friendly format with request_id
        fmt = "%(asctime)s [%(levelname)s] [req=%(request_id)s] %(name)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root.addHandler(handler)

    # ── In-memory ring buffer for dashboard log viewing ──
    from app.core.log_ringbuffer import get_ring_buffer_handler
    root.addHandler(get_ring_buffer_handler())

    root.setLevel(level)

    # Quiet down noisy third-party loggers
    for noisy in ("httpx", "httpcore", "apscheduler.scheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
