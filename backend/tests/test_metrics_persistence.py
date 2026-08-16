"""Tests for metrics persistence, log ring buffer, and process metrics."""

from __future__ import annotations

import logging

from app.core.log_ringbuffer import RingBufferHandler, get_ring_buffer_handler

# ── RingBufferHandler tests ──


class TestRingBufferHandler:
    def test_singleton(self):
        h1 = get_ring_buffer_handler()
        h2 = get_ring_buffer_handler()
        assert h1 is h2

    def test_basic_capture(self):
        handler = RingBufferHandler(capacity=100)
        logger = logging.getLogger("test_ring_basic")
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)

        logger.info("hello world")
        logger.warning("warn message")
        logger.error("error occurred")

        entries = handler.get_entries(limit=10)
        assert len(entries) == 3
        # newest first
        assert entries[0]["level"] == "ERROR"
        assert entries[1]["level"] == "WARNING"
        assert entries[2]["level"] == "INFO"

    def test_level_filter(self):
        handler = RingBufferHandler(capacity=100)
        logger = logging.getLogger("test_ring_filter")
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)

        logger.info("info 1")
        logger.warning("warn 1")
        logger.error("err 1")
        logger.error("err 2")

        errors = handler.get_entries(level="ERROR", limit=10)
        assert len(errors) == 2
        assert all(e["level"] == "ERROR" for e in errors)

    def test_capacity_limit(self):
        handler = RingBufferHandler(capacity=5)
        logger = logging.getLogger("test_ring_cap")
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)

        for i in range(10):
            logger.info("msg %d", i)

        entries = handler.get_entries(limit=100)
        assert len(entries) == 5  # only last 5 retained
        # newest first: msg 9, 8, 7, 6, 5
        assert "msg 9" in entries[0]["message"]
        assert "msg 5" in entries[4]["message"]

    def test_summary(self):
        handler = RingBufferHandler(capacity=100)
        logger = logging.getLogger("test_ring_summary")
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)

        logger.info("a")
        logger.info("b")
        logger.warning("c")
        logger.error("d")

        summary = handler.get_summary()
        assert summary["total"] == 4
        assert summary["capacity"] == 100
        assert summary["by_level"].get("INFO") == 2
        assert summary["by_level"].get("WARNING") == 1
        assert summary["by_level"].get("ERROR") == 1

    def test_exception_capture(self):
        handler = RingBufferHandler(capacity=100)
        logger = logging.getLogger("test_ring_exc")
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)

        try:
            raise ValueError("test exception")
        except ValueError:
            logger.exception("caught error")

        entries = handler.get_entries(level="ERROR", limit=1)
        assert len(entries) == 1
        assert "test exception" in entries[0].get("exc_info", "")


# ── Process metrics tests ──


class TestProcessMetrics:
    def test_get_process_metrics(self):
        from app.services.metrics_persistence import _get_process_metrics

        metrics = _get_process_metrics()
        assert "process_rss_mb" in metrics
        assert "process_cpu_user_s" in metrics
        assert "process_cpu_sys_s" in metrics
        assert metrics["process_rss_mb"] > 0
        assert metrics["process_cpu_user_s"] >= 0

    def test_collect_snapshot_fields(self):
        from app.services.metrics_persistence import _collect_snapshot_fields

        fields = _collect_snapshot_fields()
        # Should contain all expected keys
        expected_keys = [
            "uptime_seconds",
            "http_total_requests",
            "http_error_rate",
            "http_p50",
            "http_p95",
            "http_p99",
            "llm_total_calls",
            "llm_success_rate",
            "llm_total_cost_usd",
            "db_pool_checked_out",
            "process_rss_mb",
            "slow_queries_total",
        ]
        for key in expected_keys:
            assert key in fields, f"Missing key: {key}"


# ── MetricsSnapshotRecord model tests ──


class TestMetricsSnapshotModel:
    def test_model_import(self):
        from app.models.metrics_snapshot import MetricsSnapshotRecord

        assert MetricsSnapshotRecord.__tablename__ == "metrics_snapshots"

    def test_model_fields(self):
        from app.models.metrics_snapshot import MetricsSnapshotRecord

        columns = {c.name for c in MetricsSnapshotRecord.__table__.columns}
        expected = {
            "id",
            "captured_at",
            "uptime_seconds",
            "http_total_requests",
            "http_total_errors_5xx",
            "http_error_rate",
            "http_p50",
            "http_p95",
            "http_p99",
            "http_in_progress",
            "http_rate_limit_hits",
            "llm_total_calls",
            "llm_total_done",
            "llm_total_failed",
            "llm_success_rate",
            "llm_total_cost_usd",
            "llm_total_input_tokens",
            "llm_total_output_tokens",
            "llm_p50",
            "llm_p95",
            "llm_p99",
            "db_pool_checked_out",
            "db_pool_size",
            "db_pool_utilization",
            "process_rss_mb",
            "process_cpu_user_s",
            "process_cpu_sys_s",
            "slow_queries_total",
        }
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"
