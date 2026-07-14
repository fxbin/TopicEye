"""Safe, on-demand reader-mode extraction for content items.

This service intentionally models only the safe half of a browser-fetching
system: one public URL already associated with a visible content item, bounded
HTTP fetches, no cookies, no proxy / CAPTCHA / stealth escalation, and text-only
snapshots.  Dynamic or protected pages fail closed to the original-source link.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib import robotparser
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.core.config import settings
from app.models.article_reader_event import ArticleReaderEvent
from app.models.article_snapshot import ArticleSnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.content import ContentItem


logger = logging.getLogger(__name__)

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
_MIN_READER_TEXT_CHARS = 160
_WORDS_PER_MINUTE = 300  # Chinese characters or space-delimited words: deliberately conservative.
_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote")


class ArticleReaderError(Exception):
    """A user-safe reader failure with an HTTP status suitable for the API."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class ExtractedArticle:
    canonical_url: str
    title: str
    byline: str | None
    published_at: datetime | None
    excerpt: str | None
    text_content: str
    content_blocks: list[dict[str, str | int]]
    extraction_method: str


_refresh_locks: dict[int, asyncio.Lock] = {}
_refresh_locks_guard: asyncio.Lock | None = None
_robots_cache: dict[str, tuple[datetime, robotparser.RobotFileParser | None, bool]] = {}


async def _refresh_lock_for(content_id: int) -> asyncio.Lock:
    """Return a per-content lock so concurrent readers do not stampede a source.

    This is the useful part of Fortress's shared-browser pattern applied to this
    much smaller service: share and bound the expensive external operation,
    while retaining per-content concurrency.
    """
    global _refresh_locks_guard
    if _refresh_locks_guard is None:
        _refresh_locks_guard = asyncio.Lock()
    async with _refresh_locks_guard:
        return _refresh_locks.setdefault(content_id, asyncio.Lock())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetime reads to the application's UTC contract."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ArticleReaderError("unsupported_url", "仅支持公开的 HTTP(S) 原文链接。")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ArticleReaderError("invalid_url", "原文链接格式不支持站内阅读。")
    return urlunparse((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def _is_private_address(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _allowed_hosts() -> tuple[str, ...]:
    return tuple(host.strip().lower() for host in settings.ARTICLE_READER_ALLOWED_HOSTS.split(",") if host.strip())


async def _validate_public_url(url: str) -> str:
    normalized = _normalized_url(url)
    host = (urlparse(normalized).hostname or "").rstrip(".").lower()
    if host in {"localhost", "metadata.google.internal"} or _is_private_address(host):
        raise ArticleReaderError("blocked_url", "该原文地址不允许站内读取。")

    allowlist = _allowed_hosts()
    if allowlist and not any(host == allowed or host.endswith(f".{allowed}") for allowed in allowlist):
        raise ArticleReaderError("host_not_allowed", "该来源尚未加入站内阅读范围。")

    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError as exc:
        raise ArticleReaderError("unresolvable_host", "原文地址暂时无法解析，请稍后打开原文。", 502) from exc

    if any(_is_private_address(info[4][0]) for info in infos):
        raise ArticleReaderError("blocked_url", "该原文地址不允许站内读取。")
    return normalized


async def _read_limited(response: httpx.Response) -> bytes:
    declared_length = response.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > settings.ARTICLE_READER_MAX_RESPONSE_BYTES:
                raise ArticleReaderError("response_too_large", "原文过大，请打开来源网站查看。", 413)
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > settings.ARTICLE_READER_MAX_RESPONSE_BYTES:
            raise ArticleReaderError("response_too_large", "原文过大，请打开来源网站查看。", 413)
        chunks.append(chunk)
    return b"".join(chunks)


async def _robots_allowed(client: httpx.AsyncClient, url: str) -> bool:
    """Respect a site's crawl policy when it is available.

    A temporary network error does not turn a single user-requested read into a
    hard failure; an explicit 401/403 or a parsed disallow rule does.  The
    result is cached briefly per origin to avoid a robots request for every
    reader click.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    cached = _robots_cache.get(origin)
    now = _utcnow()
    if cached and cached[0] > now:
        parser, fallback_allowed = cached[1], cached[2]
        return parser.can_fetch(settings.ARTICLE_READER_USER_AGENT, url) if parser is not None else fallback_allowed

    robots_url = f"{origin}/robots.txt"
    parser: robotparser.RobotFileParser | None = None
    fallback_allowed = True
    try:
        async with client.stream("GET", robots_url) as response:
            if response.status_code in {401, 403}:
                fallback_allowed = False
            elif response.status_code == 200:
                payload = await _read_limited(response)
                parser = robotparser.RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(payload.decode(response.encoding or "utf-8", errors="replace").splitlines())
    except (httpx.HTTPError, ArticleReaderError) as exc:
        logger.info("Article reader robots check skipped for %s: %s", origin, exc)

    _robots_cache[origin] = (
        now + timedelta(seconds=settings.ARTICLE_READER_ROBOTS_CACHE_SECONDS),
        parser,
        fallback_allowed,
    )
    return parser.can_fetch(settings.ARTICLE_READER_USER_AGENT, url) if parser is not None else fallback_allowed


def _first_meta(soup: BeautifulSoup, *keys: tuple[str, str]) -> str | None:
    for attr, value in keys:
        node = soup.find("meta", attrs={attr: value})
        content = node.get("content") if node else None
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\t \f\v]+", " ", value)
    value = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", value)
    return value.strip()


def _clean_inline_text(value: str) -> str:
    """Collapse a single semantic block without joining it to its neighbours."""
    return re.sub(r"\s+", " ", value).strip()


def _blocks_to_text(blocks: list[dict[str, str | int]]) -> str:
    return "\n\n".join(str(block["text"]) for block in blocks)


def blocks_from_text(value: str) -> list[dict[str, str | int]]:
    """Best-effort compatibility blocks for snapshots created before rich extraction.

    Old snapshots store a clean text string only.  When blank lines are absent,
    treating every non-empty line as a paragraph is less elegant than fresh
    extraction, but importantly avoids one unreadably large wall of text.
    """
    normalized = _clean_text(value)
    if not normalized:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n+", normalized) if part.strip()]
    if len(parts) <= 1 and "\n" in normalized:
        parts = [line.strip() for line in normalized.splitlines() if line.strip()]
    return [
        {"type": "paragraph", "text": _clean_inline_text(part)}
        for part in parts
        if _clean_inline_text(part)
    ]


def _extract_semantic_blocks(root: BeautifulSoup) -> list[dict[str, str | int]]:
    """Extract visible editorial structure, never publisher markup.

    Nested block tags are skipped so a list item containing a paragraph, for
    example, renders once.  The frontend can then style the resulting safe
    primitives without inheriting third-party CSS or scripts.
    """
    blocks: list[dict[str, str | int]] = []
    for node in root.find_all(_BLOCK_TAGS):
        if any(parent is not root and parent.name in _BLOCK_TAGS for parent in node.parents):
            continue
        text = _clean_inline_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if node.name and node.name.startswith("h"):
            block: dict[str, str | int] = {
                "type": "heading",
                "text": text,
                "level": min(4, int(node.name[1])),
            }
        elif node.name == "blockquote":
            block = {"type": "quote", "text": text}
        elif node.name == "li":
            block = {"type": "list_item", "text": text}
        else:
            block = {"type": "paragraph", "text": text}
        if not blocks or blocks[-1] != block:
            blocks.append(block)

    if blocks:
        return blocks
    return blocks_from_text(root.get_text("\n", strip=True))


def _without_duplicate_title(
    blocks: list[dict[str, str | int]], title: str
) -> list[dict[str, str | int]]:
    if not blocks or blocks[0].get("type") != "heading":
        return blocks
    if _clean_inline_text(str(blocks[0]["text"])).casefold() == _clean_inline_text(title).casefold():
        return blocks[1:]
    return blocks


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _extract_from_html(payload: bytes, final_url: str) -> ExtractedArticle:
    soup = BeautifulSoup(payload, "html.parser")
    for node in soup(["script", "style", "noscript", "template", "svg", "canvas", "iframe", "form", "nav", "footer", "aside"]):
        node.decompose()

    canonical = soup.find("link", rel=lambda values: values and "canonical" in values)
    canonical_href = canonical.get("href") if canonical else None
    canonical_url = final_url
    if isinstance(canonical_href, str) and canonical_href:
        try:
            canonical_url = _normalized_url(urljoin(final_url, canonical_href))
        except ArticleReaderError:
            # Canonical is publisher-supplied metadata; never expose a custom
            # scheme from it as a link in our UI.
            canonical_url = final_url
    title = _first_meta(soup, ("property", "og:title"), ("name", "twitter:title"))
    if not title:
        heading = soup.find("h1")
        title = _clean_text(heading.get_text(" ", strip=True)) if heading else None
    if not title and soup.title:
        title = _clean_text(soup.title.get_text(" ", strip=True))
    title = title or "未命名原文"

    byline = _first_meta(soup, ("name", "author"), ("property", "article:author"))
    published_at = _parse_datetime(_first_meta(soup, ("property", "article:published_time"), ("name", "date")))
    excerpt = _first_meta(soup, ("name", "description"), ("property", "og:description"))

    article = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    blocks = _without_duplicate_title(_extract_semantic_blocks(article), title)
    text_content = _blocks_to_text(blocks)
    if len(text_content) < _MIN_READER_TEXT_CHARS:
        raise ArticleReaderError("not_readerable", "该页面没有可提取的正文，请打开来源网站查看。")
    if not excerpt:
        excerpt = text_content[:240].rstrip() + ("…" if len(text_content) > 240 else "")
    return ExtractedArticle(
        canonical_url=canonical_url,
        title=title[:500],
        byline=byline[:255] if byline else None,
        published_at=published_at,
        excerpt=excerpt[:500] if excerpt else None,
        text_content=text_content[: settings.ARTICLE_READER_MAX_TEXT_CHARS],
        content_blocks=blocks,
        extraction_method="http",
    )


def _extract_from_ingested_content(content: ContentItem) -> ExtractedArticle | None:
    raw = (content.raw_content or "").strip()
    if len(raw) < _MIN_READER_TEXT_CHARS:
        return None
    blocks: list[dict[str, str | int]]
    if "<" in raw and ">" in raw:
        soup = BeautifulSoup(raw, "html.parser")
        for node in soup(["script", "style", "noscript", "template", "svg", "canvas", "iframe", "form", "nav", "footer", "aside"]):
            node.decompose()
        blocks = _extract_semantic_blocks(soup)
    else:
        blocks = blocks_from_text(raw)
    blocks = _without_duplicate_title(blocks, content.title or "")
    text_content = _blocks_to_text(blocks)
    if len(text_content) < _MIN_READER_TEXT_CHARS:
        return None
    return ExtractedArticle(
        canonical_url=_normalized_url(content.url),
        title=(content.title or "未命名原文")[:500],
        byline=(content.author or None),
        published_at=content.published_at,
        excerpt=(content.summary or text_content[:240]).strip()[:500] or None,
        text_content=text_content[: settings.ARTICLE_READER_MAX_TEXT_CHARS],
        content_blocks=blocks,
        extraction_method="ingested",
    )


async def _fetch_remote_article(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ExtractedArticle:
    current_url = await _validate_public_url(url)
    visited = {current_url}
    timeout = httpx.Timeout(settings.ARTICLE_READER_FETCH_TIMEOUT_SECONDS)
    headers = {
        "User-Agent": settings.ARTICLE_READER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    }

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        trust_env=False,
        transport=transport,
    ) as client:
        if not await _robots_allowed(client, current_url):
            raise ArticleReaderError("robots_disallowed", "该来源不允许站内阅读，请打开原文。", 403)

        for _ in range(settings.ARTICLE_READER_MAX_REDIRECTS + 1):
            async with client.stream("GET", current_url) as response:
                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise ArticleReaderError("invalid_redirect", "原文跳转地址无效，请打开原文。", 502)
                    next_url = await _validate_public_url(urljoin(current_url, location))
                    if next_url in visited:
                        raise ArticleReaderError("redirect_loop", "原文跳转异常，请打开原文。", 502)
                    if not await _robots_allowed(client, next_url):
                        raise ArticleReaderError("robots_disallowed", "该来源不允许站内阅读，请打开原文。", 403)
                    visited.add(next_url)
                    current_url = next_url
                    continue
                if response.status_code >= 400:
                    raise ArticleReaderError("upstream_unavailable", "来源网站暂时无法提供正文，请打开原文。", 502)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    raise ArticleReaderError("unsupported_content", "该原文不是可阅读的网页内容。")
                payload = await _read_limited(response)
                if content_type == "text/plain":
                    text = _clean_text(payload.decode(response.encoding or "utf-8", errors="replace"))
                    if len(text) < _MIN_READER_TEXT_CHARS:
                        raise ArticleReaderError("not_readerable", "该页面没有可提取的正文，请打开来源网站查看。")
                    return ExtractedArticle(
                        canonical_url=current_url,
                        title="原文内容",
                        byline=None,
                        published_at=None,
                        excerpt=text[:240] + ("…" if len(text) > 240 else ""),
                        text_content=text[: settings.ARTICLE_READER_MAX_TEXT_CHARS],
                        content_blocks=blocks_from_text(text),
                        extraction_method="http",
                    )
                return _extract_from_html(payload, current_url)

    raise ArticleReaderError("too_many_redirects", "原文跳转次数过多，请打开原文。", 502)


def _snapshot_is_fresh(snapshot: ArticleSnapshot, now: datetime) -> bool:
    return snapshot.fetch_status == "ready" and as_utc(snapshot.expires_at) > now


async def read_or_create_snapshot(
    db: AsyncSession,
    content: ContentItem,
    *,
    refresh: bool = False,
) -> tuple[ArticleSnapshot, str]:
    """Return a cached reader snapshot or safely generate a fresh one."""
    now = _utcnow()
    existing = await db.scalar(select(ArticleSnapshot).where(ArticleSnapshot.content_id == content.id))
    if existing and not refresh and _snapshot_is_fresh(existing, now):
        return existing, "hit"

    lock = await _refresh_lock_for(content.id)
    async with lock:
        # A second reader may have refreshed while this request waited.
        existing = await db.scalar(select(ArticleSnapshot).where(ArticleSnapshot.content_id == content.id))
        now = _utcnow()
        if existing and not refresh and _snapshot_is_fresh(existing, now):
            return existing, "hit"

        if not settings.ARTICLE_READER_ENABLED:
            raise ArticleReaderError("reader_disabled", "站内阅读暂未启用。", 503)

        extracted = _extract_from_ingested_content(content)
        if extracted is None:
            extracted = await _fetch_remote_article(content.url)

        reading_minutes = max(1, (len(extracted.text_content) + _WORDS_PER_MINUTE - 1) // _WORDS_PER_MINUTE)
        expires_at = now + timedelta(seconds=settings.ARTICLE_READER_SNAPSHOT_TTL_SECONDS)
        values = {
            "canonical_url": extracted.canonical_url[:1024],
            "fetch_status": "ready",
            "extraction_method": extracted.extraction_method,
            "title": extracted.title,
            "byline": extracted.byline,
            "published_at": extracted.published_at,
            "excerpt": extracted.excerpt,
            "text_content": extracted.text_content,
            "content_blocks": extracted.content_blocks,
            "content_hash": hashlib.sha256(extracted.text_content.encode("utf-8")).hexdigest(),
            "reading_minutes": reading_minutes,
            "fetched_at": now,
            "expires_at": expires_at,
        }
        if existing is None:
            existing = ArticleSnapshot(content_id=content.id, **values)
            db.add(existing)
        else:
            for field, value in values.items():
                setattr(existing, field, value)
        await db.flush()
        return existing, "miss"


async def record_reader_event(
    db: AsyncSession,
    *,
    content_id: int,
    outcome: str,
    duration_ms: int,
    extraction_method: str | None = None,
    error_code: str | None = None,
) -> None:
    """Persist enough evidence to decide whether browser rendering is justified."""
    db.add(
        ArticleReaderEvent(
            content_id=content_id,
            outcome=outcome,
            error_code=error_code,
            extraction_method=extraction_method,
            duration_ms=max(0, duration_ms),
        )
    )
    await db.flush()
