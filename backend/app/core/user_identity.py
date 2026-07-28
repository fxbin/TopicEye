"""Pure normalization helpers shared by persistence and authentication code."""

from __future__ import annotations


def normalize_email(email: str) -> str:
    """Return the canonical representation used for unique email lookups."""
    return email.strip().lower()
