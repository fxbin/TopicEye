from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - registers every ORM table on Base.metadata
from app.api.v1 import auth as auth_api, contents as contents_api
from app.core.database import Base
from app.models.article_reader_event import ArticleReaderEvent
from app.models.article_snapshot import ArticleSnapshot
from app.models.content import ContentItem, ContentStatus
from app.services import article_reader


@pytest.mark.asyncio
async def test_reader_creates_text_snapshot_and_keeps_private_content_hidden(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    public_text = "这是已由 RSS 采集到的正文。" * 30
    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="公开阅读样本",
                    url="https://example.com/public-reader",
                    source_name="测试信源",
                    source_type="RSS",
                    raw_content=public_text,
                    status=ContentStatus.ANALYZED,
                ),
                ContentItem(
                    id=2,
                    title="私有阅读样本",
                    url="https://example.com/private-reader",
                    source_name="私有测试信源",
                    source_type="RSS",
                    owner_user_id=99,
                    raw_content=public_text,
                    status=ContentStatus.ANALYZED,
                ),
            ]
        )
        await db.commit()

    app = FastAPI()
    app.include_router(contents_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/contents/1/reader")
        second = await client.post("/contents/1/reader")
        private = await client.post("/contents/2/reader")

    assert first.status_code == 200
    assert first.json()["extraction_method"] == "ingested"
    assert first.json()["text_content"] == public_text
    assert first.json()["content_blocks"] == [
        {"type": "paragraph", "text": public_text, "level": None, "src": None, "alt": None}
    ]
    assert first.json()["cache_status"] == "miss"
    assert second.status_code == 200
    assert second.json()["cache_status"] == "hit"
    assert private.status_code == 404

    async with session_factory() as db:
        snapshot = await db.scalar(select(ArticleSnapshot).where(ArticleSnapshot.content_id == 1))
        assert snapshot is not None
        assert snapshot.content_blocks == [{"type": "paragraph", "text": public_text}]
        events = (await db.scalars(select(ArticleReaderEvent).order_by(ArticleReaderEvent.id))).all()
        # 事件序列：首读 miss 由服务层记 success、API 层记 ready；命中只记 cache_hit
        assert [event.outcome for event in events] == ["success", "ready", "cache_hit"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_reader_records_a_failure_before_returning_the_source_fallback(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=3,
                title="无法读取的公开内容",
                url="https://example.com/protected-reader",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()

    async def fail_fetch(url: str):
        raise article_reader.ArticleReaderError("robots_disallowed", "该来源不允许站内阅读。", 403)

    monkeypatch.setattr(article_reader, "_fetch_remote_article", fail_fetch)
    app = FastAPI()
    app.include_router(contents_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/contents/3/reader")

    assert response.status_code == 403
    async with session_factory() as db:
        # 失败请求会产生服务层 error + API 层 failed 两条事件，取首条断言
        event = await db.scalar(
            select(ArticleReaderEvent)
            .where(ArticleReaderEvent.content_id == 3)
            .order_by(ArticleReaderEvent.id)
            .limit(1)
        )
        assert event is not None
        assert event.outcome == "error"
        assert event.error_code == "robots_disallowed"
    await engine.dispose()


def test_extract_html_strips_unsafe_markup_and_ignores_invalid_canonical_url():
    article_body = "公开正文内容。" * 40
    extracted = article_reader._extract_from_html(
        f"""
        <html><head>
          <title>备用标题</title>
          <meta property="og:title" content="文章标题">
          <meta name="author" content="作者">
          <meta name="description" content="文章摘要">
          <link rel="canonical" href="javascript:alert(1)">
          <script>window.secret = '不应出现';</script>
        </head><body><nav>导航不应出现</nav><article><h1>文章标题</h1><p>{article_body}</p></article></body></html>
        """.encode(),
        "https://example.com/source",
    )

    assert extracted.title == "文章标题"
    assert extracted.byline == "作者"
    assert extracted.canonical_url == "https://example.com/source"
    assert "导航不应出现" not in extracted.text_content
    assert "不应出现" not in extracted.text_content
    assert article_body in extracted.text_content
    assert extracted.content_blocks == [{"type": "paragraph", "text": article_body}]


def test_extract_html_excludes_header_boilerplate_on_structure_fallback():
    """结构回退（手工提取）时，header 内的导航列表不得混入正文块。"""
    extracted = article_reader._extract_from_html(
        """
        <article>
          <header><h1>结构化阅读</h1><nav><ul><li>导航甲</li><li>导航乙</li></ul></nav></header>
          <p>这是足够长的开场正文。{opening}</p>
          <h2>关键要点</h2>
          <ul><li>第一项</li><li>第二项</li></ul>
        </article>
        """.format(opening="内容。" * 70).encode(),
        "https://example.com/header-demo",
    )

    # h2+ul 被 trafilatura 丢弃 → 触发手工提取回退；header 已 decompose
    assert extracted.title == "结构化阅读"
    texts = [b.get("text") for b in extracted.content_blocks]
    assert "第一项" in texts and "第二项" in texts
    assert "导航甲" not in texts and "导航乙" not in texts


def test_extract_html_preserves_headings_quotes_and_lists():
    extracted = article_reader._extract_from_html(
        """
        <article>
          <h1>结构化阅读</h1>
          <p>这是足够长的开场正文。{opening}</p>
          <h2>关键要点</h2>
          <ul><li>第一项</li><li>第二项</li></ul>
          <blockquote>需要强调的观点。</blockquote>
        </article>
        """.format(opening="内容。" * 70).encode(),
        "https://example.com/structured",
    )

    assert extracted.content_blocks[0] == {"type": "paragraph", "text": "这是足够长的开场正文。" + "内容。" * 70}
    assert {"type": "heading", "text": "关键要点", "level": 2} in extracted.content_blocks
    assert {"type": "list_item", "text": "第一项"} in extracted.content_blocks
    assert {"type": "quote", "text": "需要强调的观点。"} in extracted.content_blocks


def test_extract_html_captures_inline_images_with_absolute_urls():
    body = "配图说明正文内容。" * 30
    extracted = article_reader._extract_from_html(
        f"""
        <html><head></head><body><article>
          <p>{body}</p>
          <figure><img src="/media/pic.png" alt="示意图"><figcaption>图注</figcaption></figure>
          <p><img src="https://cdn.example.com/a.jpg"></p>
          <img src="/pixel-art-guide.jpg" alt="像素艺术教程配图">
          <img src="/blank-template-cover.png">
          <img src="data:image/gif;base64,AAAA">
          <img src="/tracker.gif" width="1" height="1">
        </article></body></html>
        """.encode(),
        "https://news.example.com/post/1",
    )

    image_blocks = [b for b in extracted.content_blocks if b["type"] == "image"]
    # 相对地址按抓取 URL 解析为绝对地址，并保留 alt
    assert {"type": "image", "src": "https://news.example.com/media/pic.png", "alt": "示意图"} in image_blocks
    assert {"type": "image", "src": "https://cdn.example.com/a.jpg"} in image_blocks
    # data: URI 与 1px 追踪像素被丢弃
    assert all(not str(b["src"]).startswith("data:") for b in image_blocks)
    assert all("tracker.gif" not in str(b["src"]) for b in image_blocks)
    # 词干恰为追踪词的正常命名图片不得误杀（pixel-art-guide 等）
    image_srcs = {b["src"] for b in image_blocks}
    assert "https://news.example.com/pixel-art-guide.jpg" in image_srcs
    assert "https://news.example.com/blank-template-cover.png" in image_srcs
    # 图片不计入正文文本
    assert "pic.png" not in extracted.text_content


@pytest.mark.asyncio
async def test_reader_rejects_private_network_targets():
    with pytest.raises(article_reader.ArticleReaderError) as exc_info:
        await article_reader._validate_public_url("http://127.0.0.1:8080/internal")

    assert exc_info.value.code == "blocked_url"


@pytest.mark.asyncio
async def test_reader_accepts_configured_proxy_fake_ip_dns_result(monkeypatch):
    async def fake_getaddrinfo(host, port):
        return [(None, None, None, None, ("198.18.11.159", 0))]

    monkeypatch.setattr(article_reader.asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(article_reader.settings, "SSRF_FAKE_IP_PROXY_CIDR", "198.18.0.0/15")

    assert await article_reader._validate_public_url("https://example.com/story") == "https://example.com/story"
    with pytest.raises(article_reader.ArticleReaderError, match="该原文地址不允许站内读取"):
        await article_reader._validate_public_url("http://198.18.11.159/internal")


@pytest.mark.asyncio
async def test_reader_still_blocks_unconfigured_private_dns_result(monkeypatch):
    async def fake_getaddrinfo(host, port):
        return [(None, None, None, None, ("10.0.0.5", 0))]

    monkeypatch.setattr(article_reader.asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(article_reader.settings, "SSRF_FAKE_IP_PROXY_CIDR", "198.18.0.0/15")

    with pytest.raises(article_reader.ArticleReaderError) as exc_info:
        await article_reader._validate_public_url("https://example.com/story")
    assert exc_info.value.code == "blocked_url"


# 字节 WAF JS 挑战空壳页的精简样本：真实拦截响应约 2.5KB，保留签名特征
_BYTEDANCE_WAF_CHALLENGE_HTML = (
    b'<!DOCTYPE html><html lang="en"><head><script nonce="argus-csp-token" '
    b'src="https://lf-waf-js.byted-static.com/obj/waf-jschallenge/out-sha256.js">'
    b'</script></head><body><script nonce="argus-csp-token">var wci="_wafchallengeid";'
    b"</script>Please wait...</body></html>"
)

_CLOUDFLARE_CHALLENGE_HTML = (
    b"<!DOCTYPE html><html><head><title>Just a moment...</title>"
    b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
    b"</head><body></body></html>"
)


def test_bot_challenge_detection_matches_known_waf_signatures():
    assert article_reader._looks_like_bot_challenge(_BYTEDANCE_WAF_CHALLENGE_HTML)
    assert article_reader._looks_like_bot_challenge(_CLOUDFLARE_CHALLENGE_HTML)
    # 正常 SSR 文章页不得误判
    normal_page = (
        "<html><body><article><h1>标题</h1><p>" + "正文内容。" * 40 + "</p></article></body></html>"
    ).encode()
    assert not article_reader._looks_like_bot_challenge(normal_page)
    # 讨论反爬的正文中出现挑战词干：整页体积远超空壳上限，不按挑战处理
    large_article_with_marker = (
        "<html><body><article><p>如何识别 waf_jschallenge 空壳页。</p><p>"
        + "正文内容。" * 20_000
        + "</p></article></body></html>"
    ).encode()
    assert len(large_article_with_marker) > article_reader._BOT_CHALLENGE_MAX_BYTES
    assert not article_reader._looks_like_bot_challenge(large_article_with_marker)


@pytest.mark.asyncio
async def test_remote_reader_classifies_waf_challenge_as_anti_bot(monkeypatch):
    async def allow_url(url: str) -> str:
        return url

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=_BYTEDANCE_WAF_CHALLENGE_HTML,
        )

    monkeypatch.setattr(article_reader, "_validate_public_url", allow_url)
    with pytest.raises(article_reader.ArticleReaderError) as exc_info:
        await article_reader._fetch_remote_article(
            "https://reader-test.example/post/1",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.code == "anti_bot_challenge"
    assert exc_info.value.status_code == 503
    assert "暂时限制" in exc_info.value.message


@pytest.mark.asyncio
async def test_tiered_fetch_still_tries_curl_cffi_on_anti_bot_challenge(monkeypatch):
    """TLS 指纹型挑战换 curl_cffi 仍可能通过：anti_bot_challenge 不得进 _no_retry。"""
    tier_calls: list[str] = []

    async def challenged_httpx(url):
        tier_calls.append("httpx")
        raise article_reader.ArticleReaderError("anti_bot_challenge", "受限", 503)

    async def successful_curl(url):
        tier_calls.append("curl_cffi")
        return article_reader.ExtractedArticle(
            canonical_url=url,
            title="文章",
            byline=None,
            published_at=None,
            excerpt=None,
            text_content="可阅读的正文。" * 20,
            content_blocks=[],
            extraction_method="curl_cffi",
        )

    monkeypatch.setattr(article_reader, "_fetch_remote_article", challenged_httpx)
    monkeypatch.setattr(article_reader, "_fetch_with_curl_cffi", successful_curl)
    monkeypatch.setattr(article_reader.settings, "ARTICLE_READER_CURL_CFFI_FALLBACK", True)

    article, tier = await article_reader._fetch_remote_article_tiered("https://example.com/story")
    assert tier == "curl_cffi"
    assert tier_calls == ["httpx", "curl_cffi"]


@pytest.mark.asyncio
async def test_remote_reader_follows_safe_redirect_and_extracts_article(monkeypatch):
    async def allow_url(url: str) -> str:
        return url

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/article"})
        if request.url.path == "/article":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=f"<html><body><article><h1>远程文章</h1><p>{'正文。' * 100}</p></article></body></html>",
            )
        return httpx.Response(404)

    monkeypatch.setattr(article_reader, "_validate_public_url", allow_url)
    extracted = await article_reader._fetch_remote_article(
        "https://reader-test.example/start",
        transport=httpx.MockTransport(handler),
    )

    assert extracted.canonical_url == "https://reader-test.example/article"
    assert extracted.title == "远程文章"
    assert extracted.extraction_method == "http"


@pytest.mark.asyncio
async def test_reader_retries_transport_error_with_curl_cffi(monkeypatch):
    async def failed_httpx(url):
        raise httpx.ConnectError("connection failed")

    article = article_reader.ExtractedArticle(
        canonical_url="https://example.com/story",
        title="文章",
        byline=None,
        published_at=None,
        excerpt=None,
        text_content="可阅读的正文。" * 20,
        content_blocks=[],
        extraction_method="curl_cffi",
    )

    async def successful_curl(url):
        return article

    monkeypatch.setattr(article_reader, "_fetch_remote_article", failed_httpx)
    monkeypatch.setattr(article_reader, "_fetch_with_curl_cffi", successful_curl)
    monkeypatch.setattr(article_reader.settings, "ARTICLE_READER_CURL_CFFI_FALLBACK", True)

    assert await article_reader._fetch_remote_article_tiered("https://example.com/story") == (article, "curl_cffi")


@pytest.mark.asyncio
async def test_reader_reports_both_transport_failures_as_source_error(monkeypatch):
    from curl_cffi.curl import CurlError

    async def failed_httpx(url):
        raise httpx.ConnectError("connection failed")

    async def failed_curl(url):
        raise CurlError("connection failed")

    monkeypatch.setattr(article_reader, "_fetch_remote_article", failed_httpx)
    monkeypatch.setattr(article_reader, "_fetch_with_curl_cffi", failed_curl)
    monkeypatch.setattr(article_reader.settings, "ARTICLE_READER_CURL_CFFI_FALLBACK", True)

    with pytest.raises(article_reader.ArticleReaderError) as exc_info:
        await article_reader._fetch_remote_article_tiered("https://example.com/story")
    assert exc_info.value.code == "upstream_unavailable"
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_curl_fallback_validates_redirect_before_following(monkeypatch):
    from types import SimpleNamespace

    import curl_cffi.requests

    requested: list[str] = []

    class FakeSession:
        def __init__(self, **kwargs):
            assert kwargs["allow_redirects"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            requested.append(url)
            return SimpleNamespace(status_code=302, headers={"location": "http://127.0.0.1/private"})

    async def validate(url):
        if article_reader.hostname_is_blocked(article_reader.urlparse(url).hostname):
            raise article_reader.ArticleReaderError("blocked_url", "该原文地址不允许站内读取。")
        return url

    monkeypatch.setattr(curl_cffi.requests, "AsyncSession", FakeSession)
    monkeypatch.setattr(article_reader, "_validate_public_url", validate)

    with pytest.raises(article_reader.ArticleReaderError) as exc_info:
        await article_reader._fetch_with_curl_cffi("https://example.com/story")
    assert exc_info.value.code == "blocked_url"
    assert requested == ["https://example.com/story"]


async def _cooldown_test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_reader_failure_cooldown_suppresses_repeat_fetches(monkeypatch):
    engine, session_factory = await _cooldown_test_session()
    article_reader._failure_cooldown.clear()
    monkeypatch.setattr(article_reader.settings, "ARTICLE_READER_FAILURE_COOLDOWN_SECONDS", 120)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=701,
                title="冷却样本",
                url="https://example.com/cooldown",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()
        content = await db.scalar(select(ContentItem).where(ContentItem.id == 701))

        fetch_calls: list[str] = []

        async def challenged(url: str):
            fetch_calls.append(url)
            raise article_reader.ArticleReaderError(
                "anti_bot_challenge", "该来源暂时限制了访问，请稍后重试或打开原文查看。", 503
            )

        monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", challenged)

        for _ in range(2):
            with pytest.raises(article_reader.ArticleReaderError) as exc_info:
                await article_reader.read_or_create_snapshot(db, content)
            assert exc_info.value.code == "anti_bot_challenge"

        # 冷却期内第二次读取直接重抛缓存错误，没有第二次外呼
        assert fetch_calls == ["https://example.com/cooldown"]

        # refresh=true 绕过冷却，允许用户强制重试
        with pytest.raises(article_reader.ArticleReaderError):
            await article_reader.read_or_create_snapshot(db, content, refresh=True)
        assert len(fetch_calls) == 2

    article_reader._failure_cooldown.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_reader_failure_cooldown_clears_on_success(monkeypatch):
    engine, session_factory = await _cooldown_test_session()
    article_reader._failure_cooldown.clear()
    monkeypatch.setattr(article_reader.settings, "ARTICLE_READER_FAILURE_COOLDOWN_SECONDS", 120)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=702,
                title="恢复样本",
                url="https://example.com/recovered",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()
        content = await db.scalar(select(ContentItem).where(ContentItem.id == 702))

        fetch_calls = 0

        async def flaky(url: str):
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls == 1:
                raise article_reader.ArticleReaderError("anti_bot_challenge", "受限", 503)
            return (
                article_reader.ExtractedArticle(
                    canonical_url=url,
                    title="恢复后的文章",
                    byline=None,
                    published_at=None,
                    excerpt=None,
                    text_content="恢复后的正文。" * 30,
                    content_blocks=[],
                    extraction_method="http",
                ),
                "httpx",
            )

        monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", flaky)

        with pytest.raises(article_reader.ArticleReaderError):
            await article_reader.read_or_create_snapshot(db, content)

        # 第二次抓取成功（refresh 绕过冷却强制重试）→ 快照落库、冷却清除
        snapshot, cache_status = await article_reader.read_or_create_snapshot(db, content, refresh=True)
        assert cache_status == "miss"
        assert snapshot.fetch_status == "ready"

        # 冷却已清除：再次失败会真实外呼（fetch_calls 递增）而非重抛旧错误
        fetch_calls_force_fail = {"n": 2}

        async def always_fail(url: str):
            fetch_calls_force_fail["n"] += 1
            raise article_reader.ArticleReaderError("upstream_unavailable", "来源不可用", 502)

        monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", always_fail)
        with pytest.raises(article_reader.ArticleReaderError) as exc_info:
            await article_reader.read_or_create_snapshot(db, content, refresh=True)
        assert exc_info.value.code == "upstream_unavailable"
        assert fetch_calls_force_fail["n"] == 3

    article_reader._failure_cooldown.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_reader_failure_cooldown_disabled_at_zero(monkeypatch):
    engine, session_factory = await _cooldown_test_session()
    article_reader._failure_cooldown.clear()
    monkeypatch.setattr(article_reader.settings, "ARTICLE_READER_FAILURE_COOLDOWN_SECONDS", 0)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=703,
                title="零冷却样本",
                url="https://example.com/no-cooldown",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()
        content = await db.scalar(select(ContentItem).where(ContentItem.id == 703))

        fetch_calls = 0

        async def failing(url: str):
            nonlocal fetch_calls
            fetch_calls += 1
            raise article_reader.ArticleReaderError("anti_bot_challenge", "受限", 503)

        monkeypatch.setattr(article_reader, "_fetch_remote_article_tiered", failing)

        for _ in range(2):
            with pytest.raises(article_reader.ArticleReaderError):
                await article_reader.read_or_create_snapshot(db, content)

        # 冷却关闭：每次读取都真实外呼
        assert fetch_calls == 2
        assert article_reader._failure_cooldown == {}

    await engine.dispose()
