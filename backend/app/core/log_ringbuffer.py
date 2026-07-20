"""In-memory ring buffer log handler for the monitoring dashboard.

Keeps the last N log entries in a thread-safe deque, queryable via
``/api/v1/metrics/logs``.  No disk I/O — purely for real-time dashboard
log viewing.  Production log aggregation should still use stdout → Loki / ES.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone, UTC
from typing import Literal


class RingBufferHandler(logging.Handler):
    """Thread-safe ring buffer that captures formatted log entries.

    Each entry is a dict suitable for JSON serialisation:
    ``{ts, level, logger, message, request_id, source}``
    """

    def __init__(self, capacity: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry: dict = {
                "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "request_id": getattr(record, "request_id", "-"),
                "source": f"{record.filename}:{record.lineno}",
            }
            if record.exc_info and record.exc_info[1]:
                entry["exc_info"] = str(record.exc_info[1])[:500]
            with self._lock:
                self._buffer.append(entry)
        except Exception:  # noqa: BLE001 — logging handler must never raise
            pass

    def get_entries(
        self,
        *,
        level: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return recent log entries, optionally filtered by level.

        Entries are returned newest-first (most recent at index 0).
        """
        with self._lock:
            entries = list(self._buffer)
        if level and level != "ALL":
            entries = [e for e in entries if e["level"] == level]
        entries.reverse()  # newest first
        return entries[:limit]

    def get_summary(self) -> dict:
        """Return a quick summary of buffered logs (level counts)."""
        with self._lock:
            entries = list(self._buffer)
        counts: dict[str, int] = {}
        for e in entries:
            counts[e["level"]] = counts.get(e["level"], 0) + 1
        return {
            "total": len(entries),
            "capacity": self._buffer.maxlen,
            "by_level": counts,
        }


# ── Module-level singleton ──

_handler: RingBufferHandler | None = None


def get_ring_buffer_handler() -> RingBufferHandler:
    global _handler
    if _handler is None:
        _handler = RingBufferHandler(capacity=1000)
    return _handler
