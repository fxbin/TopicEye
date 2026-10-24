"""Read-model event representatives shared by picks, stats, and trend scoring."""

import math
from datetime import UTC, datetime

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


def display_event_candidate_ids(items: list[ScoringInput], assignments: dict[int, EventAssignment]) -> set[int]:
    """Choose one visible report per event for a reader-facing slate.

    Metrics keep their existing canonical identity through event_candidate_ids.
    Here a manual choice wins among formal candidates, followed by a reviewed
    primary-source profile, quality and curation. A filtered-out canonical
    cannot hide every in-scope member. Fallback canonicals remain in the
    separate pending-review pool when a formal representative is available.
    """
    standalone = {item.content_id for item in items if item.content_id not in assignments}
    groups: dict[int, list[ScoringInput]] = {}
    for item in items:
        if (assignment := assignments.get(item.content_id)) is not None:
            groups.setdefault(assignment.event_group_id, []).append(item)

    def number(value) -> float:
        try:
            parsed = float(value)
            return min(100, max(0, parsed)) if math.isfinite(parsed) else 0
        except (ValueError, TypeError):
            return 0

    def timestamp(item: ScoringInput) -> float:
        value = item.published_at or item.crawled_at
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return float("inf")
        if not isinstance(value, datetime):
            return float("inf")
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).timestamp()

    for members in groups.values():
        formal = [item for item in members if item.summary_source != "local_fallback"]
        # Source preference must not let a thin/risky official brief suppress
        # another report that can actually pass the curation substance gates.
        eligible = [item for item in formal if any(bd.selected for bd, _ in score_items([item]))]
        chosen = max(
            eligible or formal or members,
            key=lambda item: (
                assignments[item.content_id].canonical_locked and assignments[item.content_id].is_canonical,
                assignments[item.content_id].display_is_primary,
                number(item.quality_score),
                number(item.curation_score),
                -timestamp(item),
                -item.content_id,
            ),
        )
        standalone.add(chosen.content_id)
        standalone.update(
            item.content_id
            for item in members
            if item.summary_source == "local_fallback" and assignments[item.content_id].is_canonical
        )
    return standalone
