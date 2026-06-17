from app.services.dedup import build_hash, filter_duplicates, is_duplicate
from app.services.topic_clustering import _union_find_cluster


def test_content_hash_and_duplicate_filter_are_stable():
    first_hash = build_hash("same title")
    second_hash = build_hash("same title")

    assert first_hash == second_hash
    assert is_duplicate(first_hash, {second_hash})

    unique, duplicates = filter_duplicates([{"title": "alpha"}, {"title": "beta"}, {"title": "alpha"}])

    assert [item["title"] for item in unique] == ["alpha", "beta"]
    assert [item["title"] for item in duplicates] == ["alpha"]


def test_topic_cluster_groups_items_by_shared_tags():
    groups = _union_find_cluster(
        [
            {"id": 1, "tags": ["ai", "tools"]},
            {"id": 2, "tags": ["ai", "agents"]},
            {"id": 3, "tags": ["finance"]},
            {"id": 4, "tags": ["finance", "markets"]},
            {"id": 5, "tags": ["solo"]},
        ]
    )

    normalized = {tuple(sorted(group)) for group in groups}
    assert normalized == {(1, 2), (3, 4)}
