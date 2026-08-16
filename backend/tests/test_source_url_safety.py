"""信源 URL 的 SSRF 防护测试。

覆盖四层：
- ``app.utils.url_safety``：字面量 + DNS 解析判定。
- ``schemas/source``：创建/导入入口拒绝内网字面量与 RSSHub 内网实例（Pydantic ValidationError）。
- ``scraper_http._ssrf_request_guard``：重定向目标逐跳拦截。
- ``content_pipeline.ingest_from_source``：抓取入口拦截（含 DNS 解析到内网的场景）。
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.source import Source, SourceStatus, SourceType
from app.schemas.source import SourceCreate
from app.services import content_pipeline
from app.utils import url_safety
from app.utils.url_safety import (
    UnsafeUrlError,
    ensure_public_hostname,
    hostname_is_blocked,
)

# ── 字面量判定 ──


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/feed",
        "http://LOCALHOST/feed",
        "http://localhost.:8080/feed",
        "http://127.0.0.1/feed",
        "http://10.0.0.5/api",
        "http://192.168.1.10/rss",
        "http://172.16.0.1/rss",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/feed",
        "http://[fe80::1]/feed",
        "http://metadata.google.internal/computeMetadata/v1/",
        "https://0.0.0.0/x",
    ],
)
def test_hostname_is_blocked_private_literals(url):
    from urllib.parse import urlparse

    assert hostname_is_blocked(urlparse(url).hostname)


@pytest.mark.parametrize(
    "hostname",
    ["example.com", "rss.example.com", "8.8.8.8", "1.1.1.1", "news.ycombinator.com", None, ""],
)
def test_hostname_is_blocked_allows_public(hostname):
    assert not hostname_is_blocked(hostname)


@pytest.mark.asyncio
async def test_ensure_public_hostname_blocks_resolved_private(monkeypatch):
    async def fake_resolve(host):
        return ["203.0.113.10", "10.1.2.3"]

    monkeypatch.setattr(url_safety, "_resolve_host", fake_resolve)
    with pytest.raises(UnsafeUrlError):
        await ensure_public_hostname("https://rebind.example.com/feed")


@pytest.mark.asyncio
async def test_ensure_public_hostname_allows_resolved_public(monkeypatch):
    async def fake_resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_host", fake_resolve)
    await ensure_public_hostname("https://example.com/feed")


@pytest.mark.asyncio
async def test_ensure_public_hostname_treats_dns_failure_as_neutral(monkeypatch):
    async def failing_resolve(host):
        raise OSError("offline")

    monkeypatch.setattr(url_safety, "_resolve_host", failing_resolve)
    # DNS 解析失败交给抓取层按常规网络错误处理，不在此拦截。
    await ensure_public_hostname("https://unresolvable.example.com/feed")


@pytest.mark.asyncio
async def test_ensure_public_hostname_literal_check_needs_no_dns(monkeypatch):
    async def exploding_resolve(host):
        raise AssertionError("literal check must not resolve DNS")

    monkeypatch.setattr(url_safety, "_resolve_host", exploding_resolve)
    with pytest.raises(UnsafeUrlError):
        await ensure_public_hostname("http://169.254.169.254/latest/meta-data/")


# ── 创建入口（schema validator，覆盖 create/update/OPML/批量导入）──


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/feed",
        "http://127.0.0.1:8080/rss",
        "http://10.1.1.1/api",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/feed",
        "http://metadata.google.internal/x",
    ],
)
def test_source_create_rejects_private_url(url):
    with pytest.raises(ValidationError):
        SourceCreate(name="内网信源", url=url, source_type=SourceType.RSS)


def test_source_create_accepts_public_url():
    data = SourceCreate(name="公网信源", url="  https://Example.com/RSS.xml  ", source_type=SourceType.RSS)
    assert data.url == "https://example.com/RSS.xml"


@pytest.mark.parametrize("url", ["http://2130706433/x", "http://0x7f000001/x", "http://3232235521/x"])
def test_source_create_rejects_non_dotted_ip_notation(url):
    # 2130706433 == 127.0.0.1；0x7f000001 == 127.0.0.1；3232235521 == 192.168.0.1
    with pytest.raises(ValidationError):
        SourceCreate(name="整数 IP", url=url, source_type=SourceType.RSS)


# ── RSSHub 实例（keyword JSON 用户可控向量）──


def test_rsshub_source_rejects_private_instance():
    keyword = '{"instances": ["https://rsshub.app", "http://169.254.169.254/"], "timeout": 15}'
    with pytest.raises(ValidationError):
        SourceCreate(
            name="RSSHub", url="https://rsshub.app/xiaohongshu/user/1", source_type=SourceType.RSSHub, keyword=keyword
        )


def test_rsshub_source_rejects_non_url_instance():
    with pytest.raises(ValidationError):
        SourceCreate(
            name="RSSHub",
            url="https://rsshub.app/xiaohongshu/user/1",
            source_type=SourceType.RSSHub,
            keyword='{"instances": ["not-a-url"]}',
        )


def test_rsshub_source_accepts_public_instances_and_legacy_keyword():
    keyword = '{"instances": ["https://rsshub.app"], "timeout": 15}'
    data = SourceCreate(
        name="RSSHub", url="https://rsshub.app/xiaohongshu/user/1", source_type=SourceType.RSSHub, keyword=keyword
    )
    assert '"https://rsshub.app"' in data.keyword
    # 旧格式 / 非 instances JSON 原样放行，交给抓取层钩子兜底
    legacy = SourceCreate(
        name="RSSHub", url="https://rsshub.app/xiaohongshu/user/1", source_type=SourceType.RSSHub, keyword="随便备注"
    )
    assert legacy.keyword == "随便备注"


# ── 重定向跟随（scraper client request 钩子）──


@pytest.mark.asyncio
async def test_scraper_client_blocks_redirect_to_internal(monkeypatch):
    """公网信源 302 到内网时，request 钩子必须拦截，不得真正发起内网请求。"""
    from app.services.scraper_http import build_scraper_client_kwargs

    async def fake_resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_host", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        raise AssertionError(f"内网请求不应发出: {request.url}")

    kwargs = build_scraper_client_kwargs("https://example.com/feed")
    kwargs["transport"] = httpx.MockTransport(handler)
    async with httpx.AsyncClient(**kwargs) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("https://example.com/feed")


@pytest.mark.asyncio
async def test_scraper_client_allows_normal_fetch_and_same_host_redirect(monkeypatch):
    from app.services.scraper_http import build_scraper_client_kwargs

    async def fake_resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_host", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"Location": "https://example.com/feed"})
        return httpx.Response(200, text="<rss/>")

    kwargs = build_scraper_client_kwargs("https://example.com/feed")
    kwargs["transport"] = httpx.MockTransport(handler)
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.get("https://example.com/moved")
        assert resp.status_code == 200
        assert resp.text == "<rss/>"


# ── 抓取入口（ingest_from_source 最终防线）──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["http://169.254.169.254/latest/meta-data/", "http://localhost/x", "http://10.0.0.9/api"]
)
async def test_ingest_blocks_private_source_without_network(monkeypatch, url):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def exploding_resolve(host):
        raise AssertionError("private literal must be rejected before DNS")

    monkeypatch.setattr(url_safety, "_resolve_host", exploding_resolve)

    async with session_factory() as db:
        source = Source(name="内网", url=url, source_type=SourceType.API)
        db.add(source)
        await db.commit()

        stats = await content_pipeline.ingest_from_source(source, db)

        assert stats == {"fetched": 0, "new": 0, "duplicates": 0}
        await db.refresh(source)
        assert source.status == SourceStatus.ERROR
        assert source.sync_error

    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_blocks_domain_resolving_to_private(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def fake_resolve(host):
        return ["10.9.9.9"]

    monkeypatch.setattr(url_safety, "_resolve_host", fake_resolve)

    async with session_factory() as db:
        source = Source(name="Rebind", url="https://rebind.example.com/api", source_type=SourceType.API)
        db.add(source)
        await db.commit()

        stats = await content_pipeline.ingest_from_source(source, db)

        assert stats == {"fetched": 0, "new": 0, "duplicates": 0}
        await db.refresh(source)
        assert source.status == SourceStatus.ERROR

    await engine.dispose()
