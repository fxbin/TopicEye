from copy import deepcopy

import pytest

from scripts.prepare_event_shadow_dataset import prepare_dataset


def raw():
    return {
        "owner_user_id": None,
        "candidates": [],
        "queries": [
            {
                "query_id": f"q{i}",
                "incoming": {
                    "id": i,
                    "title": f"Unique subject {i}",
                    "created_at": "2026-10-23T00:00:00+00:00",
                    "source_name": "Publisher",
                },
                "expected": "unknown",
                "label_source": "unlabeled",
            }
            for i in range(1, 10)
        ],
    }


def test_bootstrap_is_explicit_unlabeled_and_disjoint():
    data = raw()
    with pytest.raises(ValueError, match="explicit flag"):
        prepare_dataset(data)
    result = prepare_dataset(data, allow_bootstrap=True, seed_limit=3)
    assert result["bootstrap"]["seed_scan_count"] == 3
    assert result["bootstrap"]["event_fact_writes"] == result["bootstrap"]["model_calls"] == 0
    assert {c["id"] for c in result["candidates"]}.isdisjoint({q["incoming"]["id"] for q in result["queries"]})
    assert len(result["queries"]) == 6
    assert all(q["expected"] == "unknown" and q["label_source"] == "unlabeled" for q in result["queries"])
    assert not result["human_holdout_verified"] and not result["split_event_family_independence_verified"]
    assert data == raw()


def test_private_or_previously_labeled_queries_do_not_become_holdout():
    data = raw()
    data["queries"][0]["incoming"]["owner_user_id"] = 7
    with pytest.raises(ValueError, match="owner"):
        prepare_dataset(data, allow_bootstrap=True)
    labeled = deepcopy(raw())
    labeled["queries"][0]["expected"] = "same_event"
    with pytest.raises(ValueError, match="before labels"):
        prepare_dataset(labeled, allow_bootstrap=True)


def test_existing_pool_must_be_public_and_queries_are_unique_articles():
    data = raw()
    data["candidates"] = [{**data["queries"][0]["incoming"], "id": 100, "owner_user_id": 9}]
    with pytest.raises(ValueError, match="owner"):
        prepare_dataset(data)
    data["candidates"][0]["owner_user_id"] = None
    data["queries"][1]["incoming"]["id"] = data["queries"][0]["incoming"]["id"]
    with pytest.raises(ValueError, match="duplicate incoming"):
        prepare_dataset(data)


@pytest.mark.parametrize("identifier", ["0001", True, -1])
def test_article_identity_requires_positive_integer(identifier):
    data = raw()
    data["queries"][0]["incoming"]["id"] = identifier
    with pytest.raises(ValueError, match="positive integers"):
        prepare_dataset(data, allow_bootstrap=True)
