"""
RSSHub scraper with multi-instance fallback (DB-driven).

Routes: https://<instance>/<route>
Examples:
  - xiaohongshu/user/profile/<user_id>
  - weibo/user/<uid>
  - bilibili/user/<uid>

Instance list is read from app_settings DB table. Per-source override
via source_config.instances is also supported.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional, Any

import feedparser
import httpx

from . import BaseScraper, register_scraper

logger = logging.getLogger(__name__)

_BLOCKED_PATTERNS = [
    "rsshub.app is temporarily unable to reach your RSS reader",
    "Service Unavailable",
    "CDN Gateway Timeout",
    "504 Gateway Timeout",
]


async def _load_instances_from_db(db=None) -> list[dict]:
    """Load RSSHub instance list from app_settings. Returns list of dicts."""
    from app.models.app_setting import AppSetting
    from sqlalchemy import select

    close_after = False
    if db is None:
        from app.core.database import async_session

        db = async_session()
        close_after = True

    try:
        result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
        row = result.scalar_one_or_none()
        if row and row.value:
            try:
                instances = json.loads(row.value)
                return [i for i in instances if i.get("enabled", True)]
            except json.JSONDecodeError:
                pass
        return []
    finally:
        if close_after:
            await db.close()


def _default_instances() -> list[str]:
    return ["https://rsshub.app", "https://rsshub.rssforever.com"]


@register_scraper("RSSHub")
class RSSHubScraper(BaseScraper):
    """
    Fetch and parse RSSHub feeds with automatic instance fallback.

    source_url: RSSHub route only, e.g. "xiaohongshu/user/profile/xxx"
    source_config:
        instances: list[str] — per-source instance override (optional)
        timeout: float — request timeout in seconds (default 15)
        max_retries: int — retries per instance on transient failure (default 1)
    """

    def __init__(self, source_url: str, source_config: Optional[dict] = None):
        super().__init__(source_url, source_config or {})
        self.route = source_url.strip().lstrip("/")
        self.timeout = self.config.get("timeout", 15.0)
        self.max_retries = self.config.get("max_retries", 1)
        self._override_instances: Optional[list[str]] = self.config.get("instances")

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """
        Try each RSSHub instance in order until one succeeds.

        Instance list comes from (1) per-source override, (2) DB, or (3) defaults.
        """
        # Resolve instance list
        if self._override_instances:
            instance_list: list[dict] = [{"url": u} for u in self._override_instances]
        else:
            db_instances = await _load_instances_from_db()
            if db_instances:
                instance_list = sorted(db_instances, key=lambda x: x.get("priority", 0))
            else:
                instance_list = [{"url": u} for u in _default_instances()]

        all_errors: list[str] = []

        for inst in instance_list:
            base_url = inst["url"].rstrip("/")
            for attempt in range(self.max_retries + 1):
                full_url = f"{base_url}/{self.route}"

                try:
                    resp = await client.get(full_url, timeout=self.timeout)

                    if resp.status_code == 200:
                        content = resp.text
                        if any(pat in content for pat in _BLOCKED_PATTERNS):
                            logger.warning("Instance %s returned blocked page", base_url)
                            all_errors.append(f"{base_url}: blocked")
                            break  # try next instance

                        if "<?xml" not in content and "<rss" not in content and "<feed" not in content:
                            logger.warning("Instance %s returned non-RSS content", base_url)
                            all_errors.append(f"{base_url}: non-RSS")
                            break

                        logger.info("RSSHub fetched from %s (attempt %d)", full_url, attempt + 1)
                        return self._parse_entries(content, base_url)

                    elif resp.status_code in (503, 504, 429, 403):
                        logger.warning("Instance %s HTTP %d, trying next", base_url, resp.status_code)
                        all_errors.append(f"{base_url}: HTTP {resp.status_code}")
                        break  # try next instance

                    else:
                        all_errors.append(f"{base_url}: HTTP {resp.status_code}")
                        break

                except httpx.TimeoutException:
                    logger.warning("Instance %s timed out (attempt %d), trying next", base_url, attempt)
                    all_errors.append(f"{base_url}: timeout")

                except httpx.HTTPError as exc:
                    logger.warning("Instance %s error: %s", base_url, exc)
                    all_errors.append(f"{base_url}: {exc}")
                    break

        last_err = all_errors[-1] if all_errors else "unknown"
        raise httpx.HTTPError(f"All RSSHub instances failed. Last: {last_err}")

    def _parse_entries(self, xml_content: str, instance_url: str) -> list[dict[str, Any]]:
        """Parse RSSHub XML and return list of entry dicts."""
        feed = feedparser.parse(xml_content)
        entries: list[dict[str, Any]] = []

        for entry in feed.entries:
            # Image
            image_url = ""
            if hasattr(entry, "enclosures") and entry.enclosures:
                image_url = entry.enclosures[0].get("href", "")
            elif hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url", "")
            elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url", "")

            # Published date
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = time.strftime("%Y-%m-%dT%H:%M:%S", entry.published_parsed)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published_at = time.strftime("%Y-%m-%dT%H:%M:%S", entry.updated_parsed)

            # Author
            author = (
                (entry.author or "")
                if hasattr(entry, "author")
                else (entry.author_detail.get("name", "") if hasattr(entry, "author_detail") else "")
            )

            entries.append(
                {
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", "").strip(),
                    "author": author.strip() if author else "",
                    "summary": (entry.get("summary", "").strip() or entry.get("description", "").strip()),
                    "raw_content": (
                        entry.get("content", [{}])[0].get("value", "")
                        if hasattr(entry, "content") and entry.content
                        else ""
                    ),
                    "tags": [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")],
                    "published_at": published_at,
                    "cover_url": image_url,
                }
            )

        logger.info("RSSHub parsed %d entries from %s", len(entries), instance_url)
        return entries
