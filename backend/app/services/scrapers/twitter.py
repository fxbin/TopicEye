"""
Twitter scraper via Apify (altimis/scweet actor).

Requires APIFY_TOKEN env var. Free tier provides ~$5/month.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC
from html import unescape
from typing import Any

import httpx

from . import BaseScraper, register_scraper

logger = logging.getLogger(__name__)

_APIFY_BASE = "https://api.apify.com/v2"
_POLL_INTERVAL = 3.0
_MAX_WAIT = 180


@register_scraper("X")
class TwitterScraper(BaseScraper):
    """
    Fetch tweets via Apify scweet actor.

    config keys:
        users: list[str]          — @handles to monitor
        search_query: Optional[str]  — optional search instead of profiles
        fetch_limit: int          — max items per run (default 50)
        actor_id: str             — Apify actor ID (default altimis/scweet)
    """

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        token = os.environ.get("APIFY_TOKEN", "")
        if not token:
            logger.warning("TwitterScraper: APIFY_TOKEN not set, skipping")
            return []

        users = self.config.get("users", [])
        search_query = self.config.get("search_query")
        fetch_limit = self.config.get("fetch_limit", 50)
        actor_id = self.config.get("actor_id", "altimis~scweet")

        if not users and not search_query:
            logger.debug("TwitterScraper: no users or search_query configured")
            return []

        # Build payload
        if search_query:
            payload = {
                "source_mode": "search",
                "search_query": search_query,
                "search_sort": "Latest",
                "max_items": max(100, fetch_limit),
            }
        else:
            clean_users = [u.strip().lstrip("@") for u in users if u.strip()]
            if not clean_users:
                return []
            payload = {
                "source_mode": "profiles",
                "profile_urls": clean_users,
                "search_sort": "Latest",
                "max_items": max(100, fetch_limit),
            }

        # Start Apify run
        run_url = f"{_APIFY_BASE}/acts/{actor_id}/runs?token={token}"
        try:
            resp = await client.post(run_url, json=payload, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()["data"]
            run_id = data["id"]
            dataset_id = data["defaultDatasetId"]
        except Exception as exc:
            logger.error("TwitterScraper: failed to start Apify run: %s", exc)
            return []

        # Wait for completion
        if not await self._wait_for_run(client, token, run_id):
            return []

        # Fetch dataset
        raw_items = await self._fetch_dataset(client, token, dataset_id)
        entries = []
        for raw in raw_items:
            if isinstance(raw, dict) and raw.get("noResults"):
                continue
            parsed = self._parse_item(raw)
            if parsed:
                entries.append(parsed)

        logger.info("TwitterScraper: fetched %d tweets", len(entries))
        return entries

    async def _wait_for_run(self, client: httpx.AsyncClient, token: str, run_id: str) -> bool:
        url = f"{_APIFY_BASE}/actor-runs/{run_id}?token={token}"
        elapsed = 0.0
        while elapsed < _MAX_WAIT:
            try:
                resp = await client.get(url, timeout=10.0)
                resp.raise_for_status()
                status = resp.json()["data"]["status"]
                if status == "SUCCEEDED":
                    return True
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.error("TwitterScraper: Apify run %s status=%s", run_id, status)
                    return False
            except Exception as exc:
                logger.warning("TwitterScraper: poll error for %s: %s", run_id, exc)
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
        logger.warning("TwitterScraper: run %s timed out after %ds", run_id, _MAX_WAIT)
        return False

    async def _fetch_dataset(self, client: httpx.AsyncClient, token: str, dataset_id: str) -> list:
        url = f"{_APIFY_BASE}/datasets/{dataset_id}/items?token={token}"
        try:
            resp = await client.get(url, timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("TwitterScraper: failed to fetch dataset %s: %s", dataset_id, exc)
            return []

    @staticmethod
    def _parse_item(raw: dict) -> dict[str, Any] | None:
        """Parse a single tweet from Apify/scweet output."""
        try:
            created_at_str = raw.get("created_at")
            if not created_at_str:
                return None

            try:
                from dateutil.parser import isoparse

                published_at = isoparse(created_at_str)
            except Exception:
                from datetime import datetime as _dt

                published_at = _dt.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")

            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            published_at = published_at

            text = raw.get("full_text") or raw.get("text") or ""
            if not text:
                return None
            text = unescape(text)

            user = raw.get("user") or {}
            screen_name = (
                user.get("screen_name") or user.get("username") or user.get("handle") or raw.get("handle") or "unknown"
            )
            author = user.get("name") or screen_name

            tweet_id = str(raw.get("id_str") or raw.get("id") or "")
            if tweet_id.startswith("tweet-"):
                tweet_id = tweet_id[6:]

            url = raw.get("url") or f"https://twitter.com/{screen_name}/status/{tweet_id}"

            title_body = text[:50].replace("\n", " ").strip()
            if len(text) > 50:
                title_body += "..."

            return {
                "title": f"@{screen_name}: {title_body}",
                "url": url,
                "author": author,
                "summary": text[:300],
                "raw_content": text,
                "tags": [],
                "published_at": published_at,
                "cover_url": None,
                "metadata": {
                    "tweet_id": tweet_id,
                    "favorite_count": raw.get("favorite_count", 0),
                    "retweet_count": raw.get("retweet_count", 0),
                    "reply_count": raw.get("reply_count", 0),
                    "view_count": raw.get("view_count"),
                },
            }
        except Exception as exc:
            logger.debug("TwitterScraper: failed to parse tweet: %s", exc)
            return None
