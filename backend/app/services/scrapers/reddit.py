"""
Reddit scraper — direct .json API, no OAuth required.

Uses Reddit's public .json endpoints via **curl subprocess** to bypass
TLS fingerprinting that blocks httpx/requests.  Reddit's WAF detects
Python HTTP libraries' TLS fingerprints and returns 403; curl's TLS
fingerprint matches real browsers.

source_url format:  "<subreddit>"   (e.g. "LocalLLaMA", "MachineLearning")
source_config (JSON via Source.source_config):
    sort:           "hot" | "new" | "top" | "rising"   (default "hot")
    fetch_limit:    int  1-100  (default 25)
    min_score:      int  skip posts below this score   (default 0)
    time_filter:    "hour"|"day"|"week"|"month"|"year"|"all" (default "day", only for top/rising)
    fetch_comments: int  0-20, how many top comments to grab (default 0)
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from datetime import datetime, timezone, UTC
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from . import BaseScraper, register_scraper

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
_COMMENT_SEMAPHORE = asyncio.Semaphore(2)


# ── curl-based HTTP helper ──────────────────────────────────────────


async def _curl_get(url: str, params: dict[str, Any] | None = None) -> Any | None:
    """Run curl subprocess to fetch JSON from Reddit, bypassing TLS fingerprinting."""
    full_url = f"{url}?{urlencode(params)}" if params else url

    cmd = [
        "curl",
        "-sS",
        "--max-time",
        "20",
        "-H",
        f"User-Agent: {USER_AGENT}",
        "-H",
        "Accept: application/json,text/plain,*/*",
        "-H",
        "Accept-Language: en-US,en;q=0.9",
        "-H",
        f"Referer: {REDDIT_BASE}/",
    ]

    # Add proxy if available
    import os

    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy:
        cmd.extend(["--proxy", proxy])

    cmd.append(full_url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25)

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:200]
            logger.warning("curl failed (rc=%d) for %s: %s", proc.returncode, full_url, err_msg)
            return None

        text = stdout.decode(errors="replace")
        if not text:
            return None

        # Detect HTML error pages (Reddit returns these as 403)
        text_stripped = text.strip()
        if text_stripped.startswith("<!"):
            logger.warning("Reddit returned HTML instead of JSON for %s", full_url)
            return None

        return json.loads(text)

    except TimeoutError:
        logger.warning("curl timeout for %s", full_url)
        return None
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON from %s: %s", full_url, e)
        return None
    except Exception as e:
        logger.warning("curl error for %s: %s", full_url, e)
        return None


@register_scraper("REDDIT")
class RedditScraper(BaseScraper):
    """
    Fetch posts (and optionally top comments) from a Reddit subreddit
    via the public ``.json`` endpoint using curl to bypass TLS fingerprinting.
    """

    def __init__(self, source_url: str, source_config: dict | None = None):
        super().__init__(source_url, source_config or {})
        # source_url is the subreddit name (without /r/)
        self.subreddit = source_url.strip().strip("/").removeprefix("r/")
        self.sort = self.config.get("sort", "hot")
        self.fetch_limit = min(self.config.get("fetch_limit", 25), 100)
        self.min_score = self.config.get("min_score", 0)
        self.time_filter = self.config.get("time_filter", "day")
        self.fetch_comments = min(self.config.get("fetch_comments", 0), 20)

    # ── Public entry ────────────────────────────────────────────────

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Fetch subreddit posts and return normalised entry dicts.

        NOTE: The ``client`` parameter is accepted for BaseScraper interface
        compatibility but is NOT used — all HTTP calls go through curl subprocess
        to bypass Reddit's TLS fingerprinting.
        """
        params: dict[str, Any] = {"limit": self.fetch_limit, "raw_json": 1}
        if self.sort in ("top", "controversial"):
            params["t"] = self.time_filter

        url = f"{REDDIT_BASE}/r/{self.subreddit}/{self.sort}.json"
        data = await _curl_get(url, params)
        if not data:
            return []

        posts = [child["data"] for child in data.get("data", {}).get("children", []) if child.get("kind") == "t3"]

        # Optionally fetch top comments for each qualifying post
        comment_futures: list[asyncio.Task] = []
        valid_posts: list[dict] = []

        for post in posts:
            if post.get("score", 0) < self.min_score:
                continue
            if post.get("stickied"):
                continue
            if post.get("over_18"):
                continue
            valid_posts.append(post)
            if self.fetch_comments > 0:
                comment_futures.append(
                    asyncio.ensure_future(
                        self._fetch_top_comments(
                            post.get("subreddit", self.subreddit),
                            post["id"],
                        )
                    )
                )
            else:
                comment_futures.append(asyncio.ensure_future(_empty()))

        if not valid_posts:
            return []

        all_comments = await asyncio.gather(*comment_futures, return_exceptions=True)

        entries: list[dict[str, Any]] = []
        for post, raw_comments in zip(valid_posts, all_comments):
            comments: list[dict] = [] if isinstance(raw_comments, Exception) else raw_comments  # type: ignore[assignment]
            entry = self._parse_post(post, comments)
            if entry:
                entries.append(entry)

        logger.info(
            "Reddit r/%s: fetched %d posts (%d with comments)",
            self.subreddit,
            len(entries),
            self.fetch_comments,
        )
        return entries

    # ── Comment fetching ────────────────────────────────────────────

    async def _fetch_top_comments(self, subreddit: str, post_id: str) -> list[dict]:
        url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
        params = {
            "limit": self.fetch_comments,
            "depth": 1,
            "sort": "top",
            "raw_json": 1,
        }

        async with _COMMENT_SEMAPHORE:
            data = await _curl_get(url, params)

        if not data or not isinstance(data, list) or len(data) < 2:
            return []

        comments: list[dict] = []
        for child in data[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            if c.get("body") and c.get("distinguished") != "moderator":
                comments.append(c)

        comments.sort(key=lambda c: c.get("score", 0), reverse=True)
        return comments[: self.fetch_comments]

    # ── Parse ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_post(post: dict, comments: list[dict]) -> dict[str, Any] | None:
        post_id = post["id"]
        title = post.get("title", "")
        is_self = post.get("is_self", False)
        subreddit = post.get("subreddit", "")
        permalink = post.get("permalink", "")
        discussion_url = f"https://www.reddit.com{permalink}"

        # For link posts use external URL; for self posts use discussion
        url = discussion_url if is_self else post.get("url", discussion_url)
        author = post.get("author", "unknown")
        created_utc = post.get("created_utc", 0)
        published_at = datetime.fromtimestamp(created_utc, tz=UTC)

        # Build content body
        parts: list[str] = []
        selftext = post.get("selftext", "")
        if selftext:
            if len(selftext) > 1500:
                selftext = selftext[:1497] + "..."
            parts.append(selftext)

        if comments:
            parts.append("\n--- Top Comments ---")
            for c in comments:
                commenter = c.get("author", "anon")
                body = c.get("body", "").strip()
                if len(body) > 500:
                    body = body[:497] + "..."
                score = c.get("score", 0)
                parts.append(f"[{commenter} ({score} pts)]: {body}")

        raw_content = "\n\n".join(parts)

        # Build summary from selftext (truncated)
        summary = selftext[:300] if selftext else title

        # Tags from flair
        tags: list[str] = []
        flair = post.get("link_flair_text")
        if flair:
            tags.append(flair)
        domain = post.get("domain", "")
        if domain and domain != f"self.{subreddit}":
            tags.append(domain)

        return {
            "title": title,
            "url": url,
            "author": author,
            "summary": summary,
            "raw_content": raw_content,
            "tags": tags,
            "published_at": published_at,
            "cover_url": None,
            # Reddit-specific metadata stored for scoring engine
            "_reddit_meta": {
                "score": post.get("score", 0),
                "upvote_ratio": post.get("upvote_ratio"),
                "num_comments": post.get("num_comments", 0),
                "subreddit": subreddit,
                "subreddit_subscribers": post.get("subreddit_subscribers", 0),
                "is_self": is_self,
                "flair": flair,
                "discussion_url": discussion_url,
                "domain": domain,
            },
        }


async def _empty() -> list:
    """Placeholder coroutine when comment fetching is disabled."""
    return []
