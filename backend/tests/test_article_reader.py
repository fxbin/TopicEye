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
    # 图片不计入正文文本
    assert "pic.png" not in extracted.text_content


@pytest.mark.asyncio
async def test_reader_rejects_private_network_targets():
    with pytest.raises(article_reader.ArticleReaderError) as exc_info:
        await article_reader._validate_public_url("http://127.0.0.1:8080/internal")

    assert exc_info.value.code == "blocked_url"


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
