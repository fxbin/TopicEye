"""
Content deduplication utilities.

Uses content_hash (SHA-256) to identify and filter duplicate content.
"""

from app.utils.hash import content_hash


def is_duplicate(hash_value: str, existing_hashes: set[str]) -> bool:
    """Check whether *hash_value* already exists in *existing_hashes*."""
    return hash_value in existing_hashes


def build_hash(text: str) -> str:
    """Generate a content hash for the given text."""
    return content_hash(text)


def filter_duplicates(items: list[dict], text_key: str = "title") -> tuple[list[dict], list[dict]]:
    """
    Split *items* into (unique, duplicates) based on content_hash of *text_key*.

    Each item dict gets a ``content_hash`` field added in-place.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    dupes: list[dict] = []

    for item in items:
        h = build_hash(item.get(text_key, ""))
        item["content_hash"] = h
        if h in seen:
            dupes.append(item)
        else:
            seen.add(h)
            unique.append(item)

    return unique, dupes
