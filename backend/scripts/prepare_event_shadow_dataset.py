"""Prepare an unlabeled review packet; optionally bootstrap an empty pool locally.

Bootstrap representatives are routing hypotheses from earlier public articles,
never persisted canonical facts or independently reviewed labels.
"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import content_event_normalization as normalizer  # noqa: E402
from scripts.evaluate_event_pool import _snapshot  # noqa: E402


def prepare_dataset(raw: dict, *, allow_bootstrap: bool = False, seed_limit: int = 500) -> dict:
    if raw.get("owner_user_id") is not None:
        raise ValueError("only the public owner scope is supported")
    if not 1 <= seed_limit <= 5000:
        raise ValueError("seed_limit must be 1..5000")
    dataset = copy.deepcopy(raw)
    queries = dataset["queries"]
    content_ids = [q["incoming"].get("id") for q in queries] + [c.get("id") for c in dataset["candidates"]]
    if any(type(content_id) is not int or content_id < 1 for content_id in content_ids):
        raise ValueError("content IDs must be positive integers, not aliases or booleans")
    if any(q.get("expected", "unknown") != "unknown" for q in queries):
        raise ValueError("prepare splits before labels; do not recycle calibrated labels into a holdout")
    query_ids = [q["query_id"] for q in queries]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("duplicate query IDs")
    if not dataset["candidates"]:
        if not allow_bootstrap:
            raise ValueError("actual canonical pool is empty; bootstrap requires an explicit flag")
        if len(queries) < 2:
            raise ValueError("not enough incoming articles for separate bootstrap and evaluation cohorts")
        seed_count = min(seed_limit, len(queries) - 1)
        pool = []
        seed_ids = []
        for q in queries[:seed_count]:
            incoming = _snapshot(q["incoming"], default_id=0, owner_user_id=None)
            ranked = normalizer._best_candidates(incoming, pool, limit=8)
            prediction, _ = normalizer._local_prediction(incoming, ranked)
            if prediction is not None and prediction.decision == "standalone":
                pool.append(normalizer._Candidate(event_id=None, canonical=incoming))
                seed_ids.append(incoming.id)
        projections = {q["incoming"]["id"]: q["incoming"] for q in queries[:seed_count]}
        dataset["candidates"] = [projections[content_id] for content_id in seed_ids]
        dataset["queries"] = queries[seed_count:]
        dataset["pool_kind"] = "actual_public_articles_shadow_bootstrap"
        dataset["bootstrap"] = {
            "seed_scan_count": seed_count,
            "provisional_canonical_count": len(seed_ids),
            "seed_content_ids": [q["incoming"]["id"] for q in queries[:seed_count]],
            "actual_persisted_canonical_count": 0,
            "seed_decisions_human_verified": False,
            "model_calls": 0,
            "event_fact_writes": 0,
            "warning": "Local cold-start hypotheses; does not establish actual canonical-pool recall.",
        }
    candidate_ids = {c["id"] for c in dataset["candidates"]}
    for candidate in dataset["candidates"]:
        _snapshot(candidate, default_id=0, owner_user_id=None)
    if len(candidate_ids) != len(dataset["candidates"]):
        raise ValueError("duplicate candidate IDs")
    incoming_ids = [q["incoming"]["id"] for q in dataset["queries"]]
    if len(incoming_ids) != len(set(incoming_ids)):
        raise ValueError("duplicate incoming content IDs")
    for q in dataset["queries"]:
        _snapshot(q["incoming"], default_id=0, owner_user_id=None)
        if q["incoming"]["id"] in candidate_ids:
            raise ValueError("an evaluation query cannot be its own candidate")
        # This only plans a workload. True event families still require an
        # independent reviewer to check cross-split leakage before acceptance.
        fold = int(hashlib.sha256(q["query_id"].encode()).hexdigest()[:8], 16) % 5
        q["planned_split"] = "holdout" if fold == 0 else "calibration"
        q["label_source"] = "unlabeled"
        q["expected_target_ids"] = []
        q["target_labels_exhaustive"] = False
    dataset["split"] = "unlabeled_review_packet"
    dataset["human_holdout_verified"] = False
    dataset["split_event_family_independence_verified"] = False
    dataset["write_rollout_eligible"] = False
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-empty-pool", action="store_true")
    parser.add_argument("--seed-limit", type=int, default=500)
    args = parser.parse_args()
    source = args.dataset.read_bytes()
    result = prepare_dataset(json.loads(source), allow_bootstrap=args.bootstrap_empty_pool, seed_limit=args.seed_limit)
    result["source_export_sha256"] = hashlib.sha256(source).hexdigest()
    result["preparation_classifier_sha256"] = hashlib.sha256(Path(normalizer.__file__).read_bytes()).hexdigest()
    args.output_dir.mkdir(exist_ok=False)
    (args.output_dir / "dataset.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for split in ("calibration", "holdout"):
        rows = [q for q in result["queries"] if q["planned_split"] == split]
        (args.output_dir / f"{split}-cases.jsonl").write_text(
            "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in rows)
        )
    (args.output_dir / "labels-template.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "query_id": q["query_id"],
                    "planned_split": q["planned_split"],
                    "expected": "unknown",
                    "expected_target_ids": [],
                    "target_labels_exhaustive": False,
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "evidence": [],
                    "notes": "",
                },
                ensure_ascii=False,
            )
            + "\n"
            for q in result["queries"]
        )
    )
    print(
        json.dumps(
            {
                "candidates": len(result["candidates"]),
                "queries": len(result["queries"]),
                "bootstrap": result.get("bootstrap"),
                "human_holdout_verified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
