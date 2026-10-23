from copy import deepcopy

import pytest

from scripts.evaluate_event_pool import evaluate_pool


def dataset():
    def content(content_id, source):
        return {
            "id": content_id,
            "title": "GLM 5.2 发布模型池能力",
            "source_name": source,
            "created_at": "2026-10-20T08:00:00+00:00",
        }

    return {
        "dataset_id": "synthetic-test",
        "pool_kind": "synthetic",
        "candidates": [content(1, "publisher-a")],
        "queries": [
            {
                "query_id": "q1",
                "incoming": content(500, "publisher-b"),
                "expected": "same_event",
                "expected_target_ids": [1],
                "target_labels_exhaustive": True,
                "label_source": "synthetic-test",
            }
        ],
    }


@pytest.mark.asyncio
async def test_pool_competition_can_displace_the_true_candidate():
    data = dataset()
    for content_id in range(2, 11):
        data["candidates"].append({**data["candidates"][0], "id": content_id})
    result = await evaluate_pool(data, top_k=8)
    assert result["candidate_pool_size"] == 10
    assert len(result["outcomes"][0]["ranked_candidate_ids"]) == 8
    assert 1 not in result["outcomes"][0]["boundary_candidate_ids"]
    assert result["candidate_recall_at_k"] == 0
    assert result["model_calls"] == 0 and result["write_rollout_eligible"] is False


@pytest.mark.asyncio
async def test_replay_parser_preserves_wrong_target_failure_and_all_query_denominators():
    data = dataset()
    data["queries"].append({**deepcopy(data["queries"][0]), "query_id": "q2"})
    result = await evaluate_pool(
        data,
        mode="replay",
        max_model_calls=1,
        responses={
            "q1": {
                "response": {
                    "decision": "duplicate",
                    "target_content_id": 999,
                    "confidence": 1,
                    "reason": "invalid supplied ID",
                }
            },
        },
    )
    assert result["model_calls"] == 1
    assert result["model_status_counts"] == {"failed": 1, "budget_exhausted": 1}
    assert result["labeled_queries"] == 2 and result["decision_counts"] == {"pending": 2}
    assert result["correct_decisions_over_all_labeled"] == 0
    assert result["auto_accept_precision"] is None
    assert result["model_accuracy_measured"] is False


@pytest.mark.asyncio
async def test_replay_acceptance_is_not_live_model_or_human_validation():
    result = await evaluate_pool(
        dataset(),
        mode="replay",
        max_model_calls=1,
        responses={
            "q1": {
                "response": {
                    "decision": "duplicate",
                    "target_content_id": 1,
                    "confidence": 0.99,
                    "reason": "same facts",
                }
            },
        },
    )
    assert result["auto_accept_precision"] == 1
    assert 0 < result["auto_accept_precision_wilson_95_lower"] < 0.5
    assert result["model_accuracy_measured"] is False
    assert result["usage_and_cost_verified"] is False
    assert result["human_holdout_verified"] is False and result["write_rollout_eligible"] is False


@pytest.mark.asyncio
async def test_partial_positive_labels_do_not_count_unlabeled_alternative_as_false_merge():
    data = dataset()
    data["candidates"].append({**data["candidates"][0], "id": 2})
    data["queries"][0]["target_labels_exhaustive"] = False
    result = await evaluate_pool(
        data,
        mode="replay",
        max_model_calls=1,
        responses={
            "q1": {
                "response": {
                    "decision": "duplicate",
                    "target_content_id": 2,
                    "confidence": 0.99,
                    "reason": "same facts",
                }
            },
        },
    )
    assert result["unresolved_accepted_targets"] == 1
    assert result["false_auto_merges"] == 0 and result["auto_accept_precision"] is None


@pytest.mark.asyncio
async def test_pair_negative_cannot_be_reused_as_pool_negative_and_scopes_are_isolated():
    data = dataset()
    data["queries"][0].update(expected="different_event", expected_target_ids=[], target_labels_exhaustive=False)
    with pytest.raises(ValueError, match="complete supplied pool"):
        await evaluate_pool(data)
    data = dataset()
    data["candidates"][0]["owner_user_id"] = 123
    with pytest.raises(ValueError, match="owner"):
        await evaluate_pool(data)
    with pytest.raises(ValueError, match="explicit positive"):
        await evaluate_pool(dataset(), mode="live")
