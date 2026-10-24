"""Consistency tokens for feed traversal, never an authorization credential."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class ContentFeedChangedError(Exception):
    """The ordered visible feed no longer matches the browsing snapshot."""


@dataclass(frozen=True)
class FeedSnapshot:
    anchor: datetime
    digest: str | None = None

    @classmethod
    def parse(cls, token: str | None, *, now: datetime) -> FeedSnapshot:
        if token is None:
            return cls(anchor=now)
        try:
            anchor_text, digest = token.rsplit("|", 1)
            anchor = datetime.fromisoformat(anchor_text)
            if anchor.tzinfo is None or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("malformed snapshot")
            if not -60 <= (now - anchor).total_seconds() <= 1800:
                raise ValueError("expired snapshot")
            return cls(anchor=anchor.astimezone(UTC), digest=digest)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ContentFeedChangedError("列表快照已失效，请刷新列表后继续浏览。") from exc

    def token(self, digest: str) -> str:
        return f"{self.anchor.isoformat()}|{digest}"


def ordered_feed_digest(rows, *, binding: str) -> str:
    payload = {
        "version": 1,
        "binding": binding,
        "rows": [[row.content_id, row.event_key, str(row.event_order)] for row in rows],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class GroupedFeedPage:
    items: Any
    total: int
    digest: str
