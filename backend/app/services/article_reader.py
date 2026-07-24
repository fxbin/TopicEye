"""Safe, on-demand reader-mode extraction for content items.

This service intentionally models only the safe half of a browser-fetching
system: one public URL already associated with a visible content item, bounded
HTTP fetches, no cookies, no proxy / CAPTCHA / stealth escalation, and text-only
snapshots.  Dynamic or protected pages fail closed to the original-source link.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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
_MIN_READER_TEXT_CHARS = 60
_WORDS_PER_MINUTE = 300  # Chinese characters or space-delimited words: deliberately conservative.
_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "code")


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
    # 图片 block 没有 text 字段，跳过它们（不计入正文、阅读时长与内容 hash）
    return "\n\n".join(str(block["text"]) for block in blocks if block.get("text"))


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


def _resolve_img_src(node, base_url: str) -> str | None:
    """Resolve an <img> to a single absolute http(s) URL.

    Handles common lazy-loading attributes and srcset, and rejects inline
    data: URIs (usually spacers / placeholders) and non-http schemes.
    """
    raw = (
        node.get("src")
        or node.get("data-src")
        or node.get("data-original")
        or node.get("data-actualsrc")
        or node.get("data-lazy-src")
    )
    if not raw:
        srcset = node.get("srcset") or node.get("data-srcset")
        if isinstance(srcset, str) and srcset.strip():
            raw = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    if raw.startswith("data:"):
        return None
    try:
        absolute = urljoin(base_url, raw)
    except ValueError:
        return None
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute[:2048]


def _image_block(node, base_url: str) -> dict[str, str | int] | None:
    """Build an image block from an <img>, resolving URL and caption.

    Skips 1px tracking pixels; falls back to a wrapping <figure> caption when
    the image itself carries no alt text.
    """
    for dim in ("width", "height"):
        value = node.get(dim)
        if isinstance(value, str):
            digits = value.strip().rstrip("px").strip()
            if digits.isdigit() and int(digits) <= 1:
                return None
    src = _resolve_img_src(node, base_url)
    if not src:
        return None
    alt_attr = node.get("alt")
    alt = _clean_inline_text(alt_attr) if isinstance(alt_attr, str) else ""
    if not alt:
        figure = node.find_parent("figure")
        caption = figure.find("figcaption") if figure is not None else None
        if caption is not None:
            alt = _clean_inline_text(caption.get_text(" ", strip=True))
    block: dict[str, str | int] = {"type": "image", "src": src}
    if alt:
        block["alt"] = alt[:300]
    return block


def _extract_semantic_blocks(root: BeautifulSoup, base_url: str = "") -> list[dict[str, str | int]]:
    """Extract visible editorial structure, never publisher markup.

    Nested block tags are skipped so a list item containing a paragraph, for
    example, renders once.  ``<img>`` is captured in document order and is
    exempt from the nested-skip rule (which only governs text blocks) so inline
    article 图片 survive extraction.  The frontend can then style the resulting
    safe primitives without inheriting third-party CSS or scripts.
    """
    blocks: list[dict[str, str | int]] = []
    for node in root.find_all(_BLOCK_TAGS + ("img",)):
        if node.name == "img":
            image_block = _image_block(node, base_url)
            if image_block and (not blocks or blocks[-1] != image_block):
                blocks.append(image_block)
            continue
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
        elif node.name in ("pre", "code"):
            # 代码块：用空分隔符提取（不在标签边界插换行），保留代码原始换行
            code_text = node.get_text("", strip=False)
            # 规范化：行首尾去空、行内连续空格压缩、多余空行合并
            lines = [re.sub(r"[ \t]+", " ", line).strip() for line in code_text.splitlines()]
            code_text = "\n".join(lines).strip()
            # 连续空行压缩为单个
            code_text = re.sub(r"\n{3,}", "\n\n", code_text)
            block = {"type": "code", "text": code_text}
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
    import trafilatura

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

    # 解析相对图片地址的基准：优先 <base href>，否则用实际抓取到的 URL
    base_url = final_url
    base_tag = soup.find("base", href=True)
    if base_tag is not None:
        base_href = base_tag.get("href")
        if isinstance(base_href, str) and base_href.strip():
            try:
                base_url = urljoin(final_url, base_href.strip())
            except ValueError:
                base_url = final_url

    # Use trafilatura for high-quality boilerplate removal; fall back to
    # manual BeautifulSoup extraction when trafilatura returns nothing.
    blocks: list[dict[str, str | int]]
    try:
        clean_html = trafilatura.extract(
            payload,
            output_format="html",
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
    except Exception:
        clean_html = None

    if clean_html:
        soup_clean = BeautifulSoup(clean_html, "html.parser")
        blocks = _without_duplicate_title(_extract_semantic_blocks(soup_clean, base_url), title)
    else:
        article = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
        blocks = _without_duplicate_title(_extract_semantic_blocks(article, base_url), title)

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
    import trafilatura

    raw = (content.raw_content or "").strip()
    if len(raw) < _MIN_READER_TEXT_CHARS:
        return None
    blocks: list[dict[str, str | int]]
    if "<" in raw and ">" in raw:
        # Try trafilatura for better boilerplate removal on HTML content
        try:
            clean_html = trafilatura.extract(
                raw,
                output_format="html",
                include_comments=False,
                include_tables=True,
                favor_precision=True,
            )
        except Exception:
            clean_html = None

        if clean_html:
            soup = BeautifulSoup(clean_html, "html.parser")
            blocks = _extract_semantic_blocks(soup, content.url or "")
        else:
            soup = BeautifulSoup(raw, "html.parser")
            for node in soup(["script", "style", "noscript", "template", "svg", "canvas", "iframe", "form", "nav", "footer", "aside"]):
                node.decompose()
            blocks = _extract_semantic_blocks(soup, content.url or "")
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


def _is_chinese_text(text: str, sample_size: int = 500) -> bool:
    """判断文本是否主要为中文（CJK 字符占比 > 30%）。"""
    sample = text[:sample_size]
    cjk = sum(1 for c in sample if "\u4e00" <= c <= "\u9fff")
    latin = sum(1 for c in sample if c.isascii() and c.isalpha())
    return cjk > 0 and cjk / max(cjk + latin, 1) > 0.3


async def translate_snapshot(db: AsyncSession, content: ContentItem) -> ArticleSnapshot:
    """翻译 snapshot 正文为中文。已有缓存直接返回；原文已中文则标记跳过。"""
    snapshot = await db.scalar(
        select(ArticleSnapshot).where(ArticleSnapshot.content_id == content.id)
    )
    if snapshot is None:
        raise RuntimeError("正文快照不存在，请先打开原文阅读")

    # 已有翻译缓存 → 直接返回
    if snapshot.text_content_zh:
        return snapshot

    # 原文已是中文 → 标记跳过（用原文填 zh 字段，前端切换时两者相同）
    if _is_chinese_text(snapshot.text_content):
        snapshot.text_content_zh = snapshot.text_content
        snapshot.content_blocks_zh = snapshot.content_blocks
        await db.commit()
        return snapshot

    # 调 LLM 翻译 content_blocks（保留结构）
    from app.services.llm.provider import call_llm_json

    original_blocks = snapshot.content_blocks or []
    if not original_blocks:
        # fallback：翻译纯文本
        result = await call_llm_json(
            [
                {"role": "system", "content": "你是专业翻译。把英文翻译成流畅的中文，保留技术术语和专有名词原文。只输出译文，不要解释。"},
                {"role": "user", "content": snapshot.text_content[:8000]},
            ],
            scene="reader_translate",
            temperature=0.3,
            max_tokens=6000,
        )
        translated_text = result.get("translation") or result.get("text") or result.get("raw_response") or ""
        # call_llm_json 返回的不是 JSON 而是纯文本时的兜底
        if not translated_text and "raw_response" not in result:
            translated_text = str(result)
        snapshot.text_content_zh = translated_text[:settings.ARTICLE_READER_MAX_TEXT_CHARS]
    else:
        # 逐块翻译，保留 block 结构
        blocks_for_llm = [{"i": i, "type": b.get("type"), "text": b.get("text", "")} for i, b in enumerate(original_blocks) if b.get("text")]
        result = await call_llm_json(
            [
                {"role": "system", "content": "你是专业翻译。把英文 block 数组翻译成中文，保留 type/level 结构。技术术语和专有名词保留英文原文。输出 JSON 数组 [{\"i\":0,\"text\":\"中文\"},...]。只输出 JSON。"},
                {"role": "user", "content": json.dumps(blocks_for_llm, ensure_ascii=False)[:8000]},
            ],
            scene="reader_translate",
            temperature=0.3,
            max_tokens=6000,
        )
        translated_blocks = []
        if isinstance(result, list):
            trans_map = {item.get("i"): item.get("text", "") for item in result if isinstance(item, dict)}
        elif isinstance(result, dict) and "translations" in result:
            trans_map = {item.get("i"): item.get("text", "") for item in result["translations"] if isinstance(item, dict)}
        else:
            trans_map = {}
        for i, b in enumerate(original_blocks):
            tb = dict(b)
            if i in trans_map and trans_map[i]:
                tb["text"] = trans_map[i]
            translated_blocks.append(tb)
        snapshot.content_blocks_zh = translated_blocks
        snapshot.text_content_zh = "\n\n".join(str(b.get("text", "")) for b in translated_blocks if b.get("text"))

    await db.commit()
    return snapshot


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
