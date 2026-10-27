"""content_enrichment：入库前全文补全（fail-open、限速、按域名命中）。"""

from __future__ import annotations

import pytest

from app.models.content import ContentItem
from app.services import article_reader, content_enrichment
from app.services.article_reader import ExtractedArticle


def _article_with_structure() -> ExtractedArticle:
    return ExtractedArticle(
        canonical_url="https://juejin.cn/post/1",
        title="掘金文章",
        byline=None,
        published_at=None,
        excerpt=None,
        text_content="正文。",
        content_blocks=[
            {"type": "paragraph", "text": "开场段落。"},
            {"type": "heading", "text": "签名钥匙", "level": 2},
            {"type": "code", "text": "paySig = hmac(AppKey, signData)"},
            {"type": "list_item", "text": "钥匙不下发前端"},
            {"type": "quote", "text": "AI 写代码，人懂原理。"},
            {"type": "image", "src": "https://p.example/a.png", "alt": "示意图"},
        ],
        extraction_method="http",
    )


@pytest.fixture(autouse=True)
def _reset_throttle():
    content_enrichment._last_fetch_monotonic = 0.0
    yield
    content_enrichment._last_fetch_monotonic = 0.0


@pytest.mark.asyncio
async def test_enrich_skips_non_target_hosts_and_entries_with_full_text(monkeypatch):
    fetch_calls: list[str] = []

    async def tracking_fetch(url):
        fetch_calls.append(url)
        return _article_with_structure(), "httpx"

    monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", tracking_fetch)
    long_raw = "x" * content_enrichment._MIN_RAW_CONTENT_CHARS

    entries = [
        {"url": "https://github.blog/news", "raw_content": "短摘要"},
        {"url": "https://juejin.cn/post/1", "raw_content": long_raw},
    ]

    assert await content_enrichment.enrich_new_entries(entries) == 0
    assert fetch_calls == []
    assert entries[0]["raw_content"] == "短摘要"
    assert entries[1]["raw_content"] == long_raw


@pytest.mark.asyncio
async def test_enrich_fills_juejin_entry_and_survives_ingested_roundtrip(monkeypatch):
    async def fake_tiered(url):
        return _article_with_structure(), "httpx"

    monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", fake_tiered)

    entry = {"url": "https://juejin.cn/post/1", "title": "掘金文章", "raw_content": "90 字摘要"}
    assert await content_enrichment.enrich_new_entries([entry]) == 1

    raw = entry["raw_content"]
    assert "<h2>签名钥匙</h2>" in raw
    assert "<pre><code>paySig = hmac(AppKey, signData)</code></pre>" in raw
    assert '<img src="https://p.example/a.png" alt="示意图">' in raw

    # 入库正文经 ingested 路径可还原结构块（含 trafilatura 丢结构时的回退）
    item = ContentItem(id=1, title="掘金文章", url="https://juejin.cn/post/1", raw_content=raw)
    extracted = article_reader._extract_from_ingested_content(item)
    assert extracted is not None
    types = {block["type"] for block in extracted.content_blocks}
    assert {"paragraph", "heading", "code", "list_item", "quote"} <= types


@pytest.mark.asyncio
async def test_enrich_escapes_hostile_text_in_reconstructed_html(monkeypatch):
    async def fake_tiered(url):
        return (
            ExtractedArticle(
                canonical_url=url,
                title="t",
                byline=None,
                published_at=None,
                excerpt=None,
                text_content="正文。",
                content_blocks=[
                    {"type": "paragraph", "text": "<script>alert(1)</script>"},
                    {"type": "image", "src": 'https://x/a.png" onerror="alert(1)', "alt": "a"},
                ],
                extraction_method="http",
            ),
            "httpx",
        )

    monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", fake_tiered)
    entry = {"url": "https://juejin.cn/post/2", "raw_content": ""}
    assert await content_enrichment.enrich_new_entries([entry]) == 1
    assert "<script>" not in entry["raw_content"]
    assert "&lt;script&gt;" in entry["raw_content"]
    assert 'onerror="' not in entry["raw_content"]


@pytest.mark.asyncio
async def test_enrich_fails_open_when_fetch_errors(monkeypatch):
    async def blocked(url):
        raise article_reader.ArticleReaderError("anti_bot_challenge", "受限", 503)

    monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", blocked)
    entry = {"url": "https://juejin.cn/post/3", "raw_content": "原有摘要"}
    assert await content_enrichment.enrich_new_entries([entry]) == 0
    assert entry["raw_content"] == "原有摘要"


@pytest.mark.asyncio
async def test_enrich_respects_per_sync_cap(monkeypatch):
    calls: list[str] = []

    async def fake_tiered(url):
        calls.append(url)
        return _article_with_structure(), "httpx"

    monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", fake_tiered)
    monkeypatch.setattr(content_enrichment.settings, "INGEST_FULLTEXT_MAX_PER_SYNC", 2)

    entries = [{"url": f"https://juejin.cn/post/{i}", "raw_content": ""} for i in range(4)]
    assert await content_enrichment.enrich_new_entries(entries) == 2
    assert len(calls) == 2
    assert entries[2]["raw_content"] == ""


@pytest.mark.asyncio
async def test_enrich_disabled_when_hosts_empty(monkeypatch):
    fetch_calls: list[str] = []

    async def tracking_fetch(url):
        fetch_calls.append(url)
        return _article_with_structure(), "httpx"

    monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", tracking_fetch)
    monkeypatch.setattr(content_enrichment.settings, "INGEST_FULLTEXT_HOSTS", "")

    entry = {"url": "https://juejin.cn/post/9", "raw_content": ""}
    assert await content_enrichment.enrich_new_entries([entry]) == 0
    assert fetch_calls == []
    assert entry["raw_content"] == ""
