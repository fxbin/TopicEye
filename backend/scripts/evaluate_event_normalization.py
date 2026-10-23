"""Evaluate local event routing on labeled JSONL pairs without DB/LLM writes.

Run from backend:
  uv run python scripts/evaluate_event_normalization.py --pairs path/to/pairs.jsonl

Each record has incoming/canonical content projections, expected
(same_event|different_event|unknown), and label_source. This measures local
auto-accepts and recall into the model boundary, not end-to-end model accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.content_event_normalization import (  # noqa: E402
    CLASSIFIER_VERSION,
    _best_candidates,
    _Candidate,
    _ContentSnapshot,
    _local_prediction,
)


def _content(row: dict, *, default_id: int) -> _ContentSnapshot:
    def timestamp(key: str, fallback: datetime | None = None):
        value = row.get(key)
        if not value:
            return fallback
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed

    created = timestamp("created_at") or timestamp("crawled_at") or timestamp("published_at")
    if created is None:
        raise ValueError("each content needs an explicit timestamp; evaluation must be reproducible")
    return _ContentSnapshot(
        id=int(row.get("id", default_id)),
        title=str(row["title"]),
        summary=str(row.get("summary") or ""),
        source_id=row.get("source_id"),
        source_name=row.get("source_name"),
        platform=row.get("platform"),
        tags=row.get("tags") or [],
        owner_user_id=None,
        published_at=timestamp("published_at"),
        crawled_at=timestamp("crawled_at", created),
        created_at=created,
    )


def evaluate_pairs(records: list[dict]) -> dict:
    outcomes = []
    positives = recalled = auto_true = auto_false = labeled = 0
    for index, record in enumerate(records):
        expected = record.get("expected", "unknown")
        if expected not in {"same_event", "different_event", "unknown"}:
            raise ValueError(f"invalid expected label at pair {index + 1}")
        incoming = _content(record["incoming"], default_id=index * 2 + 1)
        canonical = _content(record["canonical"], default_id=index * 2 + 2)
        ranked = _best_candidates(incoming, [_Candidate(event_id=1, canonical=canonical)], limit=8)
        prediction, boundary = _local_prediction(incoming, ranked)
        decision = prediction.decision if prediction else "model_boundary"
        auto = prediction is not None and prediction.review_status == "auto"
        if expected != "unknown":
            labeled += 1
        if expected == "same_event":
            positives += 1
            recalled += int(auto or boundary is not None)
            auto_true += int(auto)
        elif expected == "different_event":
            auto_false += int(auto)
        outcomes.append(
            {
                "pair_id": record.get("pair_id", index + 1),
                "expected": expected,
                "label_source": record.get("label_source", "unspecified"),
                "route": decision,
                "auto_accepted": auto,
                "recall_score": round(ranked[0].score, 4) if ranked else None,
            }
        )
    accepted_labeled = auto_true + auto_false
    return {
        "classifier_version": CLASSIFIER_VERSION,
        "classifier_source_sha256": hashlib.sha256(
            Path(_best_candidates.__code__.co_filename).read_bytes()
        ).hexdigest(),
        "evaluation_scope": "local_routing_only",
        "pairs": len(records),
        "labeled_pairs": labeled,
        "same_event_pairs": positives,
        "recalled_same_event_pairs": recalled,
        "candidate_recall": recalled / positives if positives else None,
        "auto_accepted_labeled_pairs": accepted_labeled,
        "false_auto_merges": auto_false,
        "local_auto_accept_precision": auto_true / accepted_labeled if accepted_labeled else None,
        "model_accuracy_measured": False,
        "write_rollout_eligible": False,
        "rollout_blocker": "requires independently human-labeled holdout and real shadow classifier evidence",
        "outcomes": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.pairs.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    result = {"input_sha256": hashlib.sha256(raw).hexdigest(), **evaluate_pairs(records)}
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
