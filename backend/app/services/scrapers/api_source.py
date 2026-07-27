"""
Generic JSON API source scraper.

source_config examples:
{
  "method": "GET",
  "headers": {"Authorization": "Bearer ..."},
  "params": {"limit": 20},
  "items_path": "data.items",
  "fields": {
    "title": "title",
    "url": "url",
    "summary": "summary",
    "published_at": "created_at",
    "cover_url": "image"
  }
}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from . import BaseScraper, register_scraper

DEFAULT_FIELD_PATHS = {
    "title": ("title", "name", "headline"),
    "url": ("url", "link", "href", "web_url"),
    "author": ("author", "user.name", "creator.name", "source"),
    "summary": ("summary", "description", "excerpt", "abstract"),
    "raw_content": ("content", "text", "body"),
    "published_at": ("published_at", "publishedAt", "created_at", "createdAt", "date"),
    "cover_url": ("cover_url", "image", "image_url", "thumbnail", "thumb"),
}


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _first_path(value: dict, paths: tuple[str, ...]) -> Any:
    for path in paths:
        result = _get_path(value, path)
        if result not in (None, ""):
            return result
    return None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, int | float):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    if isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            # 统一 aware UTC: 无 tzinfo 的视为 UTC
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _to_list(payload: Any, items_path: str | None) -> list[dict]:
    value = _get_path(payload, items_path) if items_path else payload
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "data", "results", "list", "articles"):
            child = value.get(key)
            if isinstance(child, list):
                return [item for item in child if isinstance(item, dict)]
    return []


@register_scraper("API")
class APIScraper(BaseScraper):
    """Fetch a JSON API endpoint and normalize records into content entries."""

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        method = str(self.config.get("method") or "GET").upper()
        headers = self.config.get("headers") if isinstance(self.config.get("headers"), dict) else None
        params = self.config.get("params") if isinstance(self.config.get("params"), dict) else None
        body = self.config.get("body") if method != "GET" else None
        timeout = float(self.config.get("timeout") or 30)

        response = await client.request(
            method,
            self.url,
            headers=headers,
            params=params,
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()

        items_path = self.config.get("items_path")
        raw_items = _to_list(payload, str(items_path) if items_path else None)
        fields = self.config.get("fields") if isinstance(self.config.get("fields"), dict) else {}

        entries: list[dict[str, Any]] = []
        for item in raw_items:
            mapped: dict[str, Any] = {}
            for field, default_paths in DEFAULT_FIELD_PATHS.items():
                configured_path = fields.get(field)
                value = _get_path(item, str(configured_path)) if configured_path else _first_path(item, default_paths)
                mapped[field] = value

            title = str(mapped.get("title") or "").strip()
            url = str(mapped.get("url") or self.url).strip()
            if not title and not mapped.get("summary"):
                continue

            entries.append(
                {
                    "title": title or str(mapped.get("summary", ""))[:80],
                    "url": url,
                    "author": mapped.get("author"),
                    "summary": str(mapped.get("summary") or "")[:1000],
                    "raw_content": mapped.get("raw_content") or mapped.get("summary") or "",
                    "published_at": _parse_datetime(mapped.get("published_at")),
                    "cover_url": mapped.get("cover_url"),
                }
            )

        return entries
