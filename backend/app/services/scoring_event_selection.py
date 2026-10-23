"""Read-model event representatives shared by picks, stats, and trend scoring."""

from app.repositories.content_event_consumption_repo import EventAssignment
from app.services.scoring_engine import ScoringInput, score_items


def event_candidate_ids(items: list[ScoringInput], assignments: dict[int, EventAssignment]) -> set[int]:
    """Preserve event identity while allowing a reviewed member to stand in for a fallback canonical."""
    fallback_ids = {item.content_id for item in items if item.summary_source == "local_fallback"}
    fallback_groups = {
        a.event_group_id
        for a in assignments.values()
        if a.canonical_summary_source == "local_fallback" or a.canonical_content_id in fallback_ids
    }
    replacements: dict[int, int] = {}
    members = [
        item
        for item in items
        if item.summary_source != "local_fallback"
        and (a := assignments.get(item.content_id)) is not None
        and a.event_group_id in fallback_groups
    ]
    for _bd, item in score_items(members):
        replacements.setdefault(assignments[item.content_id].event_group_id, item.content_id)
    return {
        item.content_id
        for item in items
        if (a := assignments.get(item.content_id)) is None
        or a.is_canonical
        or replacements.get(a.event_group_id) == item.content_id
    }
