"""信源批量导入解析。

从 sources.py 抽出的纯函数模块，支持：
- OPML (XML) 格式：<outline xmlUrl="..." />
- JSON 树：任意嵌套 dict/list，自动寻找 url 字段
- Markdown 链接：[name](url)
- 纯文本 URL（每行一个）

公共入口：_parse_source_batch(content, category) -> list[dict]
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.source_repo import SourceRepository
from app.schemas.source import normalize_source_url_value
from app.models.source import SourceType


# ─── Request schemas ────────────────────────────────────────────────────

class SourceBatchImportRequest(BaseModel):
    content: str = Field(..., min_length=1)
    category: str = "批量导入"
    enabled: bool = True
    weight: int = Field(default=3, ge=1, le=5)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        category = value.strip()
        return category or "批量导入"


class SourceBatchImportItem(BaseModel):
    name: str
    url: str
    source_type: str
    category: str
    platform: str | None = None
    duplicate: bool = False


# ─── Guess helpers ──────────────────────────────────────────────────────

def _guess_source_type(url: str) -> SourceType:
    lower = url.lower()
    if "/api/" in lower or lower.endswith(".json"):
        return SourceType.API
    if "xgo.ing" in lower or "twitter.com" in lower or "x.com/" in lower:
        return SourceType.TWITTER_RSS if "xgo.ing" in lower else SourceType.X
    if "rsshub" in lower:
        return SourceType.RSSHub
    if "reddit.com" in lower:
        return SourceType.REDDIT
    if "youtube.com" in lower or "youtu.be" in lower:
        return SourceType.YOUTUBE
    if "zhihu.com" in lower:
        return SourceType.ZHIHU
    if "/feed" in lower or lower.endswith((".xml", ".rss", ".atom")) or "rss" in lower:
        return SourceType.RSS
    return SourceType.WEBSITE


def _guess_platform(url: str) -> str | None:
    lower = url.lower()
    if "github.com" in lower:
        return "GitHub"
    if "x.com" in lower or "twitter.com" in lower or "xgo.ing" in lower:
        return "X"
    if "reddit.com" in lower:
        return "Reddit"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "YouTube"
    if "zhihu.com" in lower:
        return "知乎"
    if "rsshub" in lower:
        return "RSSHub"
    return None


# ─── Parsing ────────────────────────────────────────────────────────────

def _as_source_item(raw: Any, default_category: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url = (
        raw.get("url")
        or raw.get("feed")
        or raw.get("rss")
        or raw.get("rss_url")
        or raw.get("feedUrl")
        or raw.get("feed_url")
        or raw.get("xmlUrl")
        or raw.get("href")
    )
    if not isinstance(url, str):
        return None
    try:
        normalized_url = normalize_source_url_value(url)
    except ValueError:
        return None
    name = (
        raw.get("name")
        or raw.get("title")
        or raw.get("label")
        or raw.get("site")
        or raw.get("source")
        or normalized_url
    )
    category = raw.get("category") or raw.get("group") or raw.get("type") or default_category
    source_type = raw.get("source_type") or raw.get("sourceType")
    try:
        parsed_type = SourceType(source_type) if source_type else _guess_source_type(normalized_url)
    except ValueError:
        parsed_type = _guess_source_type(normalized_url)
    return {
        "name": str(name).strip()[:255] or normalized_url,
        "url": normalized_url,
        "source_type": parsed_type,
        "category": str(category).strip()[:100] or default_category,
        "platform": raw.get("platform") or _guess_platform(normalized_url),
    }


def _walk_json_sources(value: Any, default_category: str) -> list[dict]:
    found: list[dict] = []
    item = _as_source_item(value, default_category)
    if item:
        found.append(item)
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_walk_json_sources(child, default_category))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json_sources(child, default_category))
    return found


def _parse_source_batch(content: str, default_category: str) -> list[dict]:
    text = content.strip()
    sources: list[dict] = []

    if text.startswith("<"):
        try:
            root = ET.fromstring(text.encode())
            for outline in root.findall(".//outline[@xmlUrl]"):
                try:
                    url = normalize_source_url_value(outline.get("xmlUrl", ""))
                except ValueError:
                    continue
                sources.append(
                    {
                        "name": (outline.get("title") or outline.get("text") or url).strip()[:255],
                        "url": url,
                        "source_type": _guess_source_type(url),
                        "category": outline.get("category") or default_category,
                        "platform": _guess_platform(url),
                    }
                )
        except ET.ParseError:
            pass

    try:
        parsed = json.loads(text)
        sources.extend(_walk_json_sources(parsed, default_category))
    except json.JSONDecodeError:
        pass

    markdown_link_re = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
    for name, url in markdown_link_re.findall(text):
        url = normalize_source_url_value(url)
        sources.append(
            {
                "name": name.strip()[:255],
                "url": url,
                "source_type": _guess_source_type(url),
                "category": default_category,
                "platform": _guess_platform(url),
            }
        )

    line_url_re = re.compile(r"(?P<url>https?://[^\s)\]\"']+)", re.IGNORECASE)
    for line in text.splitlines():
        clean_line = line.strip(" -\t")
        match = line_url_re.search(clean_line)
        if not match:
            continue
        raw_url = match.group("url").rstrip(".,;")
        url = normalize_source_url_value(raw_url)
        name = clean_line.replace(raw_url, "").strip(" :-—|") or url
        sources.append(
            {
                "name": name[:255],
                "url": url,
                "source_type": _guess_source_type(url),
                "category": default_category,
                "platform": _guess_platform(url),
            }
        )

    deduped: dict[str, dict] = {}
    for item in sources:
        url = item["url"].strip()
        if url and url not in deduped:
            deduped[url] = item
    return list(deduped.values())


async def _preview_source_batch_items(db: AsyncSession, content: str, category: str) -> list[SourceBatchImportItem]:
    parsed = _parse_source_batch(content, category)
    if not parsed:
        return []
    urls = [item["url"] for item in parsed]
    repo = SourceRepository(db)
    existing_urls = await repo.find_existing_urls(urls)
    return [
        SourceBatchImportItem(
            name=item["name"],
            url=item["url"],
            source_type=item["source_type"].value,
            category=item["category"],
            platform=item.get("platform"),
            duplicate=item["url"] in existing_urls,
        )
        for item in parsed
    ]