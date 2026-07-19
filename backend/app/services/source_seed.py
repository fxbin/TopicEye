from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source, SourceStatus, SourceType
from app.schemas.source import normalize_api_source_config_value, normalize_source_url_value

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_SEED_PATH = Path(__file__).with_name("default_sources.json")


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_type(value: Any) -> SourceType:
    if isinstance(value, SourceType):
        return value
    text = str(value or SourceType.RSS.value).strip()
    aliases = {
        "REDDIT": SourceType.REDDIT,
        "TWITTER_RSS": SourceType.TWITTER_RSS,
        "RSSHUB": SourceType.RSSHub,
        "WEBSITE": SourceType.WEBSITE,
        "ZHIHU": SourceType.ZHIHU,
        "DOUYIN_HOT": SourceType.DOUYIN_HOT,
    }
    if text.upper() in aliases:
        return aliases[text.upper()]
    return SourceType(text)


def load_default_sources(path: Path = DEFAULT_SOURCE_SEED_PATH) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)
    if not isinstance(raw, list):
        raise ValueError("Default source seed must be a JSON array")
    return [item for item in raw if isinstance(item, dict)]


def normalize_seed_source(raw: dict[str, Any]) -> dict[str, Any]:
    source_type = _source_type(raw.get("source_type"))
    url = _clean_text(raw.get("url"))
    if not url:
        raise ValueError("Default source url is required")
    if source_type != SourceType.RSSHub:
        url = normalize_source_url_value(url)

    keyword = _clean_text(raw.get("keyword"))
    if source_type == SourceType.API:
        keyword = normalize_api_source_config_value(keyword)

    enabled = bool(raw.get("enabled", True))
    return {
        "name": _clean_text(raw.get("name")) or url,
        "source_type": source_type,
        "url": url,
        "keyword": keyword,
        "platform": _clean_text(raw.get("platform")),
        "category": _clean_text(raw.get("category")) or "内置",
        "weight": int(raw.get("weight", 3)),
        "fetch_interval_minutes": int(raw.get("fetch_interval_minutes", 60)),
        "enabled": enabled,
        "status": SourceStatus.ACTIVE if enabled else SourceStatus.DISABLED,
        "last_sync_at": datetime.now(UTC),
    }


async def seed_default_sources(db: AsyncSession, *, seed_path: Path = DEFAULT_SOURCE_SEED_PATH) -> int:
    sources = [normalize_seed_source(item) for item in load_default_sources(seed_path)]
    if not sources:
        return 0

    urls = [item["url"] for item in sources]
    existing_result = await db.execute(select(Source).where(Source.url.in_(urls)))
    existing_sources = list(existing_result.scalars().all())
    existing_urls = {source.url for source in existing_sources}

    max_order = int(await db.scalar(select(func.max(Source.sort_order))) or 0)
    next_order = max_order + 10
    created = 0
    seeded_at = datetime.now(UTC)
    for source in existing_sources:
        if source.last_sync_at is None:
            source.last_sync_at = seeded_at

    for item in sources:
        if item["url"] in existing_urls:
            continue
        item["last_sync_at"] = seeded_at
        db.add(Source(**item, sort_order=next_order))
        next_order += 10
        created += 1

    if created:
        await db.flush()
    logger.info("Default sources seeded (%d new)", created)
    return created
