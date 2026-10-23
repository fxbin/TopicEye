"""Evaluate event recall and classification against one provided candidate pool.

No DB writes. Default routing mode makes no model calls. Replay exercises the
production response parser. Live calls require explicit --live and a call cap.
A supplied pool/label declaration never by itself authorizes write rollout.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import content_event_normalization as normalizer  # noqa: E402
from scripts.evaluate_event_normalization import _content  # noqa: E402


def _snapshot(row: dict, *, default_id: int, owner_user_id: int | None):
    if row.get("owner_user_id") != owner_user_id:
        raise ValueError("candidate/query owner does not match the declared scope")
    return replace(_content(row, default_id=default_id), owner_user_id=owner_user_id)


def _wilson_lower(correct: int, total: int) -> float | None:
    if not total:
        return None
    z = 1.959963984540054
    p = correct / total
    return (p + z * z / (2 * total) - z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / (
        1 + z * z / total
    )


async def evaluate_pool(
    dataset: dict,
    *,
    mode: str = "routing",
    responses: dict | None = None,
    max_model_calls: int = 0,
    top_k: int = 8,
) -> dict:
    if mode not in {"routing", "replay", "live"}:
        raise ValueError("mode must be routing, replay, or live")
    if not 1 <= top_k <= 50 or not 0 <= max_model_calls <= 100:
        raise ValueError("top_k/call cap out of bounds")
    if mode in {"replay", "live"} and max_model_calls < 1:
        raise ValueError("classification requires an explicit positive model call cap")
    owner = dataset.get("owner_user_id")
    candidates = [
        normalizer._Candidate(
            event_id=row.get("event_id"), canonical=_snapshot(row, default_id=index + 1, owner_user_id=owner)
        )
        for index, row in enumerate(dataset["candidates"])
    ]
    candidate_ids = {candidate.canonical.id for candidate in candidates}
    if len(candidate_ids) != len(candidates):
        raise ValueError("duplicate candidate IDs")
    queries = dataset["queries"]
    query_ids = [str(row["query_id"]) for row in queries]
    if len(set(query_ids)) != len(query_ids):
        raise ValueError("duplicate query IDs")
    limits = replace(normalizer._limits(), max_candidates=top_k)
    outcomes = []
    calls = model_completed = 0
    started = time.perf_counter()
    for index, query in enumerate(queries):
        expected = query.get("expected", "unknown")
        if expected not in {"same_event", "different_event", "unknown"}:
            raise ValueError("invalid expected label")
        if not query.get("label_source"):
            raise ValueError("each query needs label_source")
        targets = set(query.get("expected_target_ids", []))
        if not targets <= candidate_ids or (expected == "same_event" and not targets):
            raise ValueError("same_event needs expected targets in the supplied pool")
        if expected == "different_event" and (targets or not query.get("target_labels_exhaustive")):
            raise ValueError("different_event must label the complete supplied pool, not one negative pair")
        incoming = _snapshot(query["incoming"], default_id=1_000_000 + index, owner_user_id=owner)
        if incoming.id in targets:
            raise ValueError("incoming cannot be its own expected target")
        ranked = normalizer._best_candidates(incoming, candidates, limit=top_k)
        boundary_candidates = [candidate for candidate in ranked if candidate.score >= 0.62]
        prediction, boundary = normalizer._local_prediction(incoming, ranked)
        model_status = "not_needed"
        latency_ms = None
        if prediction is None and boundary is not None:
            model_status = "not_requested" if mode == "routing" else "budget_exhausted"
            if mode != "routing" and calls < max_model_calls:
                query_id = str(query["query_id"])
                call_started = time.perf_counter()
                if mode == "replay":
                    if responses is None or query_id not in responses:
                        model_status = "missing_replay"
                    else:

                        async def replay(*args, entry=responses[query_id], **kwargs):
                            if "error" in entry:
                                raise RuntimeError(str(entry["error"]))
                            return entry["response"]

                        with patch.object(normalizer, "call_llm_json", replay):
                            prediction = await normalizer._classify_boundary(
                                incoming, boundary_candidates, limits=limits, semaphore=asyncio.Semaphore(1)
                            )
                        calls += 1
                else:
                    prediction = await normalizer._classify_boundary(
                        incoming, boundary_candidates, limits=limits, semaphore=asyncio.Semaphore(1)
                    )
                    calls += 1
                latency_ms = round((time.perf_counter() - call_started) * 1000, 3)
                if prediction is not None:
                    model_status = "failed" if prediction.llm_failed else "completed"
                    model_completed += int(not prediction.llm_failed)
        auto = prediction is not None and prediction.review_status == "auto"
        target = prediction.target_content_id if prediction is not None else None
        correctness = None
        if expected != "unknown" and prediction is not None:
            if auto:
                if target in targets:
                    correctness = True
                elif expected == "different_event" or query.get("target_labels_exhaustive"):
                    correctness = False
            elif prediction.decision == "standalone":
                correctness = expected == "different_event"
        outcomes.append(
            {
                "query_id": str(query["query_id"]),
                "expected": expected,
                "label_source": query["label_source"],
                "ranked_candidate_ids": [candidate.canonical.id for candidate in ranked],
                "boundary_candidate_ids": [candidate.canonical.id for candidate in boundary_candidates],
                "expected_target_recalled": bool(
                    targets & {candidate.canonical.id for candidate in boundary_candidates}
                )
                if expected == "same_event"
                else None,
                "decision": prediction.decision if prediction is not None else "pending",
                "target_content_id": target,
                "auto_accepted": auto,
                "correct": correctness,
                "model_status": model_status,
                "latency_ms": latency_ms,
                "failure_reason": prediction.llm_error if prediction is not None and prediction.llm_failed else None,
            }
        )
    positives = [row for row in outcomes if row["expected"] == "same_event"]
    accepted_labeled = [row for row in outcomes if row["auto_accepted"] and row["correct"] is not None]
    correct_accepts = sum(row["correct"] is True for row in accepted_labeled)
    labeled = [row for row in outcomes if row["expected"] != "unknown"]
    return {
        "classifier_version": normalizer.CLASSIFIER_VERSION,
        "classifier_source_sha256": hashlib.sha256(Path(normalizer.__file__).read_bytes()).hexdigest(),
        "evaluation_scope": "provided_candidate_pool",
        "mode": mode,
        "dataset_id": dataset.get("dataset_id"),
        "split": dataset.get("split", "unspecified"),
        "pool_kind": dataset.get("pool_kind", "unspecified"),
        "production_pool_completeness_verified": False,
        "pool_completeness_declared": dataset.get("candidate_pool_complete", False),
        "candidate_pool_size": len(candidates),
        "top_k": top_k,
        "query_count": len(outcomes),
        "label_sources": dict(Counter(row["label_source"] for row in outcomes)),
        "labeled_queries": len(labeled),
        "positive_queries": len(positives),
        "candidate_recall_at_k": sum(row["expected_target_recalled"] for row in positives) / len(positives)
        if positives
        else None,
        "auto_accepted_labeled": len(accepted_labeled),
        "unresolved_accepted_targets": sum(row["auto_accepted"] and row["correct"] is None for row in outcomes),
        "false_auto_merges": len(accepted_labeled) - correct_accepts,
        "auto_accept_precision": correct_accepts / len(accepted_labeled) if accepted_labeled else None,
        "auto_accept_precision_wilson_95_lower": _wilson_lower(correct_accepts, len(accepted_labeled)),
        "correct_decisions_over_all_labeled": sum(row["correct"] is True for row in labeled) / len(labeled)
        if labeled
        else None,
        "decision_counts": dict(Counter(row["decision"] for row in outcomes)),
        "model_status_counts": dict(Counter(row["model_status"] for row in outcomes)),
        "model_call_cap": max_model_calls,
        "model_calls": calls,
        "model_completed": model_completed,
        "model_accuracy_measured": mode == "live" and any(row["model_status"] == "completed" for row in labeled),
        "model_call_unit": "classifier_requests; provider retry/failover attempts are not measured here",
        "routing_group": limits.routing_group,
        "resolved_model_identity": None,
        "cost_usd": None,
        "usage_and_cost_verified": False,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "human_holdout_verified": False,
        "write_rollout_eligible": False,
        "rollout_blocker": "requires independent holdout review, real model identity/usage evidence and governed write pilot",
        "outcomes": outcomes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--max-model-calls", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    replay_raw = args.replay.read_bytes() if args.replay else None
    result = asyncio.run(
        evaluate_pool(
            json.loads(raw),
            mode="live" if args.live else "replay" if args.replay else "routing",
            responses=json.loads(replay_raw) if replay_raw else None,
            max_model_calls=args.max_model_calls,
            top_k=args.top_k,
        )
    )
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    result["replay_sha256"] = hashlib.sha256(replay_raw).hexdigest() if replay_raw else None
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
