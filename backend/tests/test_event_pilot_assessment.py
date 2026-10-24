from copy import deepcopy

from scripts.assess_event_pilot import assess_pilot


def packet():
    labels = []
    queries = []
    outcomes = []
    for i in range(600):
        expected = "same_event" if i < 400 else "different_event"
        label = {
            "query_id": str(i),
            "expected": expected,
            "expected_target_ids": [1] if i < 400 else [],
            "target_labels_exhaustive": True,
            "hard_negative": i >= 400,
            "evidence": ["independent-review-row"],
        }
        labels.append(label)
        queries.append({**label, "incoming": {"id": 1000 + i}})
        outcomes.append({"query_id": str(i), "auto_accepted": i < 400, "target_content_id": 1 if i < 400 else None})
    dataset = {
        "pool_kind": "actual_public_canonical_export",
        "owner_user_id": None,
        "split": "holdout",
        "candidates": [{"id": 1}],
        "selection": {"pool_truncated": False, "incoming_truncated": False},
        "queries": queries,
    }
    report = {
        "input_sha256": "dataset-digest",
        "mode": "live",
        "usage_and_cost_verified": True,
        "resolved_model_identity": ["real-model"],
        "outcomes": outcomes,
        "model_calls": 1,
        "physical_attempts": 1,
        "cost_usd": 0.001,
    }
    outcomes[0]["llm_trace"] = {
        "logical_request_id": "logical-1",
        "usage_linkage_verified": True,
        "cost_usd": 0.001,
        "route": {"provider_reported_model": "real-model"},
        "physical_attempts": [
            {
                "request_id": "physical-1",
                "log_id": 1,
                "persisted": True,
                "status": "done",
                "cost_usd": 0.001,
                "usage": {"actual_model": "real-model", "input_tokens": 10, "output_tokens": 1},
            }
        ],
    }
    review = {
        "evaluation_sha256": "report-digest",
        "pool_completeness_verified": True,
        "event_family_split_verified": True,
        "reviewer_id": "independent-reviewer",
        "reviewed_at": "2026-10-24",
        "reviewer_kind": "human",
        "independent_of_implementation": True,
        "evidence": ["review-record"],
        "labels": labels,
    }
    return dataset, report, review


def assess(data):
    return assess_pilot(*data, dataset_sha256="dataset-digest", report_sha256="report-digest")


def test_thresholds_only_prepare_owner_review_never_authorize_write():
    result = assess(packet())
    assert result["status"] == "OWNER_REVIEW_REQUIRED"
    assert result["precision_wilson_95_lower"] >= 0.99
    assert not result["write_authorized"] and not result["scheduled_write_authorized"]


def test_bootstrap_replay_unknown_and_spoofed_summary_cannot_pass():
    dataset, report, review = packet()
    dataset["pool_kind"] = "actual_public_articles_shadow_bootstrap"
    report.update(mode="replay", auto_accepted_labeled=10000, auto_accept_precision=1)
    review["labels"] = []
    result = assess((dataset, report, review))
    assert result["status"] == "HOLD" and result["reviewed_auto_accepts"] == 0
    assert "actual_canonical_pool_required" in result["blockers"]
    assert "real_shadow_evaluation_required" in result["blockers"]


def test_digest_duplicate_negative_and_wrong_target_fail_closed():
    dataset, report, review = packet()
    report["input_sha256"] = "different"
    report["outcomes"][0]["target_content_id"] = 999
    report["outcomes"][400].update(auto_accepted=True, target_content_id=1)
    review["labels"].append(deepcopy(review["labels"][0]))
    result = assess((dataset, report, review))
    assert result["status"] == "HOLD"
    assert "evaluation_dataset_digest_mismatch" in result["blockers"]
    assert "duplicate_human_labels" in result["blockers"]
    assert "hard_negative_wrongly_hidden" in result["blockers"]
    assert result["precision_wilson_95_lower"] < 0.99


def test_summary_flags_without_receipts_do_not_prove_real_usage():
    dataset, report, review = packet()
    report["outcomes"][0].pop("llm_trace")
    result = assess((dataset, report, review))
    assert result["status"] == "HOLD"
    assert "per_call_usage_receipts_missing_or_inconsistent" in result["blockers"]


def test_content_id_aliases_cannot_inflate_real_sample_counts():
    dataset, report, review = packet()
    for index, query in enumerate(dataset["queries"]):
        query["incoming"]["id"] = "0" * index + "1000"
    assert "duplicate_or_invalid_incoming_ids" in assess((dataset, report, review))["blockers"]
