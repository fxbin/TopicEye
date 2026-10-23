"""Check pilot prerequisites from bound evaluation and independent review files.

This produces an owner-review packet. It never authorizes or executes a write.
Review declarations still require the owner's independent provenance check.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_event_pool import _wilson_lower  # noqa: E402


def _linked_usage_evidence(report: dict) -> bool:
    """Cross-check receipts, never promote summary flags into evidence."""
    traces = [row["llm_trace"] for row in report.get("outcomes", []) if row.get("llm_trace")]
    if not traces or len(traces) != report.get("model_calls"):
        return False
    request_ids, log_ids, models, logical_ids = set(), set(), set(), set()
    physical_count = 0
    total_cost = 0.0

    def amount(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0

    for trace in traces:
        logical = trace.get("logical_request_id")
        if not logical or logical in logical_ids or trace.get("usage_linkage_verified") is not True:
            return False
        logical_ids.add(logical)
        if not amount(trace.get("cost_usd")):
            return False
        attempts = trace.get("physical_attempts", [])
        route = trace.get("route", {})
        if route.get("provider_reported_model"):
            models.add(route["provider_reported_model"])
        trace_cost = 0.0
        for attempt in attempts:
            request_id, log_id = attempt.get("request_id"), attempt.get("log_id")
            usage = attempt.get("usage") or {}
            if (
                not isinstance(request_id, str)
                or not 1 <= len(request_id) <= 64
                or request_id in request_ids
                or type(log_id) is not int
                or log_id < 1
                or log_id in log_ids
                or attempt.get("persisted") is not True
                or attempt.get("status") != "done"
                or not usage.get("actual_model")
                or not amount(attempt.get("cost_usd"))
                or any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens"))
            ):
                return False
            request_ids.add(request_id)
            log_ids.add(log_id)
            models.add(usage["actual_model"])
            trace_cost += attempt["cost_usd"]
            physical_count += 1
        if not attempts and not (
            trace.get("cache_hit") is True
            and route.get("origin_usage_linkage_verified") is True
            and bool(route.get("origin_request_id"))
            and type(route.get("origin_log_id")) is int
            and route["origin_log_id"] > 0
            and bool(route.get("provider_reported_model"))
        ):
            return False
        if not math.isclose(trace_cost, trace["cost_usd"], abs_tol=1e-8):
            return False
        total_cost += trace_cost
    return (
        physical_count == report.get("physical_attempts")
        and models == set(report.get("resolved_model_identity") or [])
        and amount(report.get("cost_usd"))
        and math.isclose(total_cost, report["cost_usd"], abs_tol=1e-8)
    )


def assess_pilot(dataset: dict, report: dict, review: dict, *, dataset_sha256: str, report_sha256: str) -> dict:
    blockers = []

    def require(condition, reason):
        if not condition:
            blockers.append(reason)

    require(report.get("input_sha256") == dataset_sha256, "evaluation_dataset_digest_mismatch")
    require(review.get("evaluation_sha256") == report_sha256, "review_evaluation_digest_mismatch")
    require(dataset.get("owner_user_id") is None, "public_owner_scope_required")
    require(dataset.get("pool_kind") == "actual_public_canonical_export", "actual_canonical_pool_required")
    require(bool(dataset.get("candidates")), "actual_canonical_pool_empty")
    selection = dataset.get("selection", {})
    require(selection.get("pool_truncated") is False, "pool_truncated_or_unknown")
    require(selection.get("incoming_truncated") is False, "incoming_truncated_or_unknown")
    require(review.get("pool_completeness_verified") is True, "independent_pool_verification_missing")
    require(review.get("event_family_split_verified") is True, "independent_event_family_holdout_missing")
    require(dataset.get("split") == "holdout", "holdout_dataset_required")
    require(report.get("mode") == "live", "real_shadow_evaluation_required")
    require(report.get("usage_and_cost_verified") is True, "real_usage_and_cost_linkage_missing")
    require(_linked_usage_evidence(report), "per_call_usage_receipts_missing_or_inconsistent")
    require(bool(report.get("resolved_model_identity")), "model_identity_missing")
    require(bool(review.get("reviewer_id")) and bool(review.get("reviewed_at")), "reviewer_provenance_missing")
    require(review.get("reviewer_kind") == "human", "independent_human_review_required")
    require(review.get("independent_of_implementation") is True, "reviewer_independence_missing")
    require(bool(review.get("evidence")), "human_review_evidence_missing")

    queries = dataset.get("queries", [])
    outcomes = report.get("outcomes", [])
    labels = review.get("labels", [])
    query_ids = [str(q["query_id"]) for q in queries]
    incoming_ids = [(q.get("incoming") or {}).get("id") for q in queries]
    outcome_ids = [str(o["query_id"]) for o in outcomes]
    label_ids = [str(row["query_id"]) for row in labels]
    require(len(query_ids) == len(set(query_ids)), "duplicate_queries")
    require(
        all(type(content_id) is int and content_id > 0 for content_id in incoming_ids)
        and len(incoming_ids) == len(set(incoming_ids)),
        "duplicate_or_invalid_incoming_ids",
    )
    require(len(outcome_ids) == len(set(outcome_ids)), "duplicate_outcomes")
    require(len(label_ids) == len(set(label_ids)), "duplicate_human_labels")
    require(set(query_ids) == set(outcome_ids) == set(label_ids), "query_outcome_review_coverage_mismatch")
    by_query = {str(q["query_id"]): q for q in queries}
    by_label = {str(row["query_id"]): row for row in labels}
    pool_ids = {c["id"] for c in dataset.get("candidates", [])}
    require(all(type(content_id) is int and content_id > 0 for content_id in pool_ids), "invalid_candidate_ids")
    accepted = correct = negatives = wrongly_hidden = unknown_accepted = 0
    for outcome in outcomes:
        key = str(outcome["query_id"])
        label = by_label.get(key, {})
        query = by_query.get(key, {})
        expected = label.get("expected", "unknown")
        targets = set(label.get("expected_target_ids", []))
        valid = (
            label.get("target_labels_exhaustive") is True
            and bool(label.get("evidence"))
            and expected in {"same_event", "different_event"}
            and targets <= pool_ids
            and all(type(content_id) is int and content_id > 0 for content_id in targets)
            and bool(targets) == (expected == "same_event")
            and query.get("expected") == expected
            and set(query.get("expected_target_ids", [])) == targets
            and query.get("target_labels_exhaustive") is True
        )
        require(valid, f"unverified_or_mismatched_label:{key}")
        if outcome.get("auto_accepted") is True:
            if valid:
                accepted += 1
                correct += int(expected == "same_event" and outcome.get("target_content_id") in targets)
            else:
                unknown_accepted += 1
        if valid and expected == "different_event" and label.get("hard_negative") is True:
            negatives += 1
            wrongly_hidden += int(outcome.get("auto_accepted") is True)
    lower = _wilson_lower(correct, accepted)
    require(accepted >= 400, "fewer_than_400_reviewed_real_auto_accepts")
    require(lower is not None and lower >= 0.99, "precision_wilson_lower_below_99_percent")
    require(negatives >= 200, "fewer_than_200_whole_pool_hard_negatives")
    require(wrongly_hidden == 0, "hard_negative_wrongly_hidden")
    require(unknown_accepted == 0, "unreviewed_auto_accepts")
    return {
        "status": "HOLD" if blockers else "OWNER_REVIEW_REQUIRED",
        "blockers": list(dict.fromkeys(blockers)),
        "dataset_sha256": dataset_sha256,
        "evaluation_sha256": report_sha256,
        "reviewed_auto_accepts": accepted,
        "correct_auto_accepts": correct,
        "precision_wilson_95_lower": lower,
        "whole_pool_hard_negatives": negatives,
        "wrongly_hidden_hard_negatives": wrongly_hidden,
        "unknown_auto_accepts": unknown_accepted,
        "write_authorized": False,
        "scheduled_write_authorized": False,
        "remaining_owner_checks": [
            "Verify independent human review provenance and bound source/model/pool digests.",
            "Approve exact candidate, environment, public owner, limits, backup and versioned rollback.",
        ],
        "proposed_limits": {"window_hours": 1, "max_items": 20, "max_logical_calls": 5},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--human-review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset_raw, report_raw = args.dataset.read_bytes(), args.evaluation.read_bytes()
    review_raw = args.human_review.read_bytes() if args.human_review else b"{}"
    result = assess_pilot(
        json.loads(dataset_raw),
        json.loads(report_raw),
        json.loads(review_raw),
        dataset_sha256=hashlib.sha256(dataset_raw).hexdigest(),
        report_sha256=hashlib.sha256(report_raw).hexdigest(),
    )
    result["human_review_sha256"] = hashlib.sha256(review_raw).hexdigest() if args.human_review else None
    with args.output.open("x") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "blocker_count": len(result["blockers"]),
                "first_blockers": result["blockers"][:10],
            }
        )
    )


if __name__ == "__main__":
    main()
