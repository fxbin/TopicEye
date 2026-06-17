#!/usr/bin/env python3
"""Measure local API latency for key TopicEye endpoints.

This script intentionally uses only the Python standard library so it can run
inside the existing backend venv without adding benchmark dependencies.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable


DEFAULT_ENDPOINTS = (
    "/health",
    "/api/v1/contents/favorites/list?page=1&page_size=20",
    "/api/v1/contents/scoring-flow?hours=48&limit=160",
    "/api/v1/sources?page=1&page_size=20",
    "/api/v1/stats/overview",
)


@dataclass
class Sample:
    status: int
    elapsed_ms: float
    server_ms: float | None
    bytes_read: int
    error: str | None = None


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def fetch(base_url: str, endpoint: str, timeout: float) -> Sample:
    url = base_url.rstrip("/") + endpoint
    req = urllib.request.Request(url, headers={"User-Agent": "topiceye-perf-baseline"})
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            server_header = resp.headers.get("X-Process-Time-Ms")
            server_ms = float(server_header) if server_header else None
            return Sample(resp.status, elapsed_ms, server_ms, len(body))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        server_header = exc.headers.get("X-Process-Time-Ms")
        server_ms = float(server_header) if server_header else None
        return Sample(exc.code, elapsed_ms, server_ms, len(body), error=str(exc))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        return Sample(0, elapsed_ms, None, 0, error=str(exc))


def summarize(endpoint: str, samples: list[Sample]) -> dict:
    ok_samples = [sample for sample in samples if sample.status and not sample.error]
    elapsed = [sample.elapsed_ms for sample in samples]
    server = [sample.server_ms for sample in samples if sample.server_ms is not None]
    statuses: dict[int, int] = {}
    for sample in samples:
        statuses[sample.status] = statuses.get(sample.status, 0) + 1

    return {
        "endpoint": endpoint,
        "requests": len(samples),
        "ok": len(ok_samples),
        "statuses": statuses,
        "client_avg_ms": round(statistics.mean(elapsed), 3) if elapsed else 0,
        "client_p95_ms": round(percentile(elapsed, 95), 3),
        "server_avg_ms": round(statistics.mean(server), 3) if server else None,
        "server_p95_ms": round(percentile(server, 95), 3) if server else None,
        "max_bytes": max((sample.bytes_read for sample in samples), default=0),
        "errors": [sample.error for sample in samples if sample.error][:3],
    }


def run(base_url: str, endpoints: Iterable[str], rounds: int, timeout: float, warmup: int) -> list[dict]:
    results: list[dict] = []
    for endpoint in endpoints:
        for _ in range(warmup):
            fetch(base_url, endpoint, timeout)
        samples = [fetch(base_url, endpoint, timeout) for _ in range(rounds)]
        results.append(summarize(endpoint, samples))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure key TopicEye API endpoint latency.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    parser.add_argument("endpoints", nargs="*", default=list(DEFAULT_ENDPOINTS))
    args = parser.parse_args()

    results = run(args.base_url, args.endpoints, args.rounds, args.timeout, args.warmup)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print(f"Base URL: {args.base_url} | rounds={args.rounds} | warmup={args.warmup}")
    print("endpoint | ok/requests | client_avg | client_p95 | server_avg | server_p95 | statuses")
    for row in results:
        print(
            f"{row['endpoint']} | {row['ok']}/{row['requests']} | "
            f"{row['client_avg_ms']}ms | {row['client_p95_ms']}ms | "
            f"{row['server_avg_ms']}ms | {row['server_p95_ms']}ms | {row['statuses']}"
        )
        if row["errors"]:
            print(f"  errors: {row['errors']}")


if __name__ == "__main__":
    main()
