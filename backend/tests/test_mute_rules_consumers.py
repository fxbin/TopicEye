"""静音规则在消费链路的集成测试（#171）。

- /api/v1/contents 列表：keyword / source / domain 三类规则默认排除命中项，
  无规则用户不受影响，与 ignored_items（个人不感兴趣）叠加生效；
- today_picks：沿 ignored_items 的用户口径注入点，mute 命中并入排除集
  （DuckDB 候选用 monkeypatch 固定，断言服务端过滤行为）。

domain 规则的 SQL 匹配用了 PG 的 split_part/regexp_replace（host 归一），
因此本文件全部用例走 conftest 管理的一次性 PostgreSQL（DATABASE_URL）。
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, contents as contents_api, mute_rules as mute_rules_api
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.source import Source
from app.repositories.content_event_consumption_repo import ContentEventConsumptionRepository
from app.services import today_picks
from app.services.auth_service import create_session, create_user
from app.services.content_read_cache import invalidate_content_read_caches

Setup = tuple[
    httpx.AsyncClient, dict[str, str], async_sessionmaker[AsyncSession], dict[str, int], dict[str, int], dict[str, int]
]


def _clear_process_caches() -> None:
    # 列表/精选缓存按 user_id 作为缓存键；不同用例的库里 user id 会重叠
    invalidate_content_read_caches()


async def _make_setup() -> AsyncGenerator[Setup, None]:
    _clear_process_caches()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tokens: dict[str, str] = {}
    user_ids: dict[str, int] = {}
    async with session_factory() as db:
        for name in ("alice", "bob"):
            user = await create_user(db, email=f"{name}@example.com", password="Password123")
            token, _ = await create_session(db, user)
            tokens[name] = token
            user_ids[name] = user.id

        source_ids: dict[str, int] = {}
        for key, domain in (("main", "example.com"), ("noise", "noisy-source.com")):
            source = Source(name=f"Source-{key}", url=f"https://{domain}/feed", source_type="RSS", status="active")
            db.add(source)
            await db.flush()
            source_ids[key] = source.id

        now = datetime.now(UTC)
        crawled = now - timedelta(hours=1)
        # source_key=None → source_id 为 NULL 的行（sources 删除走 SET NULL，真实存在）；
        # summary=None → 无摘要的行（keyword NULL 三值逻辑回归用）
        specs = {
            "keyword_hit": {"title": "AI 大模型发布会", "url": "https://example.com/c1", "source_key": "main"},
            "domain_hit": {"title": "普通快讯", "url": "https://www.noisy.example.com/c2", "source_key": "main"},
            "source_hit": {"title": "行业周报", "url": "https://example.com/c3", "source_key": "noise"},
            "clean": {"title": "值得写的选题", "url": "https://example.com/c4", "source_key": "main"},
            "null_summary": {
                "title": "无摘要的存量条目",
                "url": "https://example.com/c5",
                "source_key": "main",
                "summary": None,
            },
            "null_source": {"title": "外部转载条目", "url": "https://example.com/c6", "source_key": None},
        }
        content_ids: dict[str, int] = {}
        for key, spec in specs.items():
            source_key = spec["source_key"]
            item = ContentItem(
                title=spec["title"],
                url=spec["url"],
                summary=spec.get("summary", f"{spec['title']} 的摘要"),
                source_id=source_ids[source_key] if source_key else None,
                source_name=f"Source-{source_key}" if source_key else "External",
                source_type="RSS",
                status="analyzed",
                content_hash=f"hash-{key}",
                crawled_at=crawled,
                published_at=crawled,
                created_at=crawled,
                updated_at=crawled,
            )
            db.add(item)
            await db.flush()
            content_ids[key] = item.id
            db.add(
                AiAnalysis(
                    content_id=item.id,
                    quality_score=80.0,
                    hot_score=75.0,
                    freshness_score=90.0,
                    creator_score=86.0,
                    viral_score=70.0,
                    risk_score=15.0,
                    curation_score=88.0,
                    info_density=82.0,
                    actionability=78.0,
                    summary=f"{spec['title']} AI 摘要",
                    tags=["AI"],
                    created_at=now,
                )
            )
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(contents_api.router)
    app.include_router(mute_rules_api.router)

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
    app.dependency_overrides[mute_rules_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tokens, session_factory, content_ids, source_ids, user_ids

    await engine.dispose()
    _clear_process_caches()


@pytest_asyncio.fixture
async def mute_filter_setup() -> AsyncGenerator[Setup, None]:
    async for setup in _make_setup():
        yield setup


def _ids(resp: httpx.Response) -> set[int]:
    return {item["id"] for item in resp.json()["items"]}


async def _add_rule(client: httpx.AsyncClient, token: str, rule_type: str, value: str) -> httpx.Response:
    return await client.post(
        "/mute-rules",
        json={"rule_type": rule_type, "value": value},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_contents_without_rules_unaffected(mute_filter_setup: Setup):
    client, tokens, _, ids, _, _ = mute_filter_setup
    for name in ("alice", "bob"):
        resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens[name]}"})
        assert resp.status_code == 200
        assert _ids(resp) == set(ids.values()), f"{name} 无规则时应看到全部内容"


@pytest.mark.asyncio
async def test_mute_rules_exclude_only_owner(mute_filter_setup: Setup):
    client, tokens, _, ids, source_ids, _ = mute_filter_setup

    # 三类规则一起开：keyword / domain（输入带协议与 www，验证端到端归一）/ source
    responses = (
        await _add_rule(client, tokens["alice"], "keyword", "大模型"),
        await _add_rule(client, tokens["alice"], "domain", "https://www.noisy.example.com/article"),
        await _add_rule(client, tokens["alice"], "source", str(source_ids["noise"])),
    )
    assert {resp.status_code for resp in responses} == {201}, [resp.text for resp in responses]

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['alice']}"})
    assert resp.status_code == 200
    survivors = {ids["clean"], ids["null_summary"], ids["null_source"]}
    assert _ids(resp) == survivors, "三类规则各自命中一项；NULL 摘要/NULL 信源的行不得被误杀"
    assert resp.json()["total"] == 3

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['bob']}"})
    assert _ids(resp) == set(ids.values()), "bob 无规则不受影响"

    resp = await client.get("/contents")
    assert _ids(resp) == set(ids.values()), "匿名访问不受任何用户静音规则影响"


@pytest.mark.asyncio
async def test_keyword_rule_is_case_insensitive_and_covers_summary(mute_filter_setup: Setup):
    client, tokens, _, ids, _, _ = mute_filter_setup

    resp = await _add_rule(client, tokens["alice"], "keyword", "QUICK")
    assert resp.status_code == 201

    # summary 命中：标题不含关键词、摘要含（大小写不敏感）
    async with mute_filter_setup[2]() as db:
        item = await db.get(ContentItem, ids["clean"])
        item.summary = "a Quick summary in english"
        await db.commit()

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['alice']}"})
    assert ids["clean"] not in _ids(resp), "summary 大小写不敏感命中应排除"
    assert ids["keyword_hit"] in _ids(resp)


@pytest.mark.asyncio
async def test_curation_score_sort_path_applies_mute_rules(mute_filter_setup: Setup):
    client, tokens, _, ids, _, _ = mute_filter_setup

    assert (await _add_rule(client, tokens["alice"], "keyword", "大模型")).status_code == 201

    resp = await client.get(
        "/contents?sort_by=curation_score",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 200
    assert ids["keyword_hit"] not in _ids(resp), "评分排序路径同样应用静音规则"


@pytest.mark.asyncio
async def test_null_summary_survives_keyword_rules_both_sort_paths(mute_filter_setup: Setup):
    """回归（Verifier 阻断 1）：summary 为 NULL 的行在 keyword 规则下不得被三值逻辑丢弃。

    旧行为 ``NOT (title ILIKE p OR summary ILIKE p)`` 在 summary 为 NULL 时
    求值为 NULL → 整行被丢弃；修复后 NULL 列视为「未命中」，两条排序路径都钉住。
    """
    client, tokens, _, ids, _, _ = mute_filter_setup

    assert (await _add_rule(client, tokens["alice"], "keyword", "大模型")).status_code == 201

    for query in ("/contents", "/contents?sort_by=curation_score"):
        resp = await client.get(query, headers={"Authorization": f"Bearer {tokens['alice']}"})
        assert resp.status_code == 200, query
        visible = _ids(resp)
        assert ids["keyword_hit"] not in visible, f"{query}：命中的内容应被排除"
        assert ids["null_summary"] in visible, f"{query}：summary 为 NULL 的行不得被 keyword 规则误杀"


@pytest.mark.asyncio
async def test_null_source_survives_source_rules(mute_filter_setup: Setup):
    """回归（Verifier 阻断 2）：source_id 为 NULL 的行在 source 规则下不得被 ``NULL NOT IN`` 误杀。"""
    client, tokens, _, ids, source_ids, _ = mute_filter_setup

    assert (await _add_rule(client, tokens["alice"], "source", str(source_ids["noise"]))).status_code == 201

    for query in ("/contents", "/contents?sort_by=curation_score"):
        resp = await client.get(query, headers={"Authorization": f"Bearer {tokens['alice']}"})
        assert resp.status_code == 200, query
        visible = _ids(resp)
        assert ids["source_hit"] not in visible, f"{query}：命中信源的内容应被排除"
        assert ids["null_source"] in visible, f"{query}：source_id 为 NULL 的行不得被 source 规则误杀"


@pytest.mark.asyncio
async def test_group_events_path_applies_mute_rules(mute_filter_setup: Setup):
    """group_events 折叠路径与普通列表同口径：mute 命中排除、NULL 行保留。"""
    client, tokens, _, ids, source_ids, _ = mute_filter_setup

    assert (await _add_rule(client, tokens["alice"], "keyword", "大模型")).status_code == 201
    assert (await _add_rule(client, tokens["alice"], "source", str(source_ids["noise"]))).status_code == 201

    resp = await client.get(
        "/contents?group_events=true",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 200
    visible = _ids(resp)
    assert ids["keyword_hit"] not in visible, "group_events 路径应排除 keyword 命中项"
    assert ids["source_hit"] not in visible, "group_events 路径应排除 source 命中项"
    assert ids["null_summary"] in visible and ids["null_source"] in visible, "group_events 路径不得误杀 NULL 行"


@pytest.mark.asyncio
async def test_mute_stacks_with_personal_ignore(mute_filter_setup: Setup):
    client, tokens, _, ids, _, _ = mute_filter_setup

    assert (await _add_rule(client, tokens["alice"], "keyword", "大模型")).status_code == 201
    resp = await client.post(
        f"/contents/{ids['clean']}/ignore",
        headers={"Authorization": f"Bearer {tokens['alice']}"},
    )
    assert resp.status_code == 200

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['alice']}"})
    assert _ids(resp) == {
        ids["domain_hit"],
        ids["source_hit"],
        ids["null_summary"],
        ids["null_source"],
    }, "静音规则与个人忽略叠加生效；NULL 摘要/NULL 信源的行不受影响"

    resp = await client.get("/contents", headers={"Authorization": f"Bearer {tokens['bob']}"})
    assert _ids(resp) == set(ids.values()), "叠加排除只作用于规则归属用户"


@pytest.mark.asyncio
async def test_today_picks_excludes_muted_rows(mute_filter_setup: Setup, monkeypatch):
    """today_picks：mute 命中并入排除集（沿 ignored 的注入点与用户口径）。"""
    client, tokens, session_factory, ids, source_ids, user_ids = mute_filter_setup

    assert (await _add_rule(client, tokens["alice"], "keyword", "大模型")).status_code == 201
    assert (await _add_rule(client, tokens["alice"], "domain", "noisy.example.com")).status_code == 201
    assert (await _add_rule(client, tokens["alice"], "source", str(source_ids["noise"]))).status_code == 201

    # 固定 DuckDB 候选（真实候选来自 DuckDB；这里验证服务端 mute 排除逻辑）
    async with session_factory() as db:
        rows = []
        for key in ("keyword_hit", "domain_hit", "source_hit", "clean"):
            item = await db.get(ContentItem, ids[key])
            rows.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "source_id": item.source_id,
                    "source_name": item.source_name,
                    "source_type": "RSS",
                    "summary": item.summary,
                    "category": "AI",
                    "content_type": None,
                    "tags": ["AI"],
                    "status": "analyzed",
                    "published_at": item.published_at.isoformat(),
                    "crawled_at": item.crawled_at.isoformat(),
                    "curation_score": 88.0,
                    "info_density": 82.0,
                    "actionability": 78.0,
                    "analysis_source_weight": 72.0,
                    "creator_score": 86.0,
                    "viral_score": 70.0,
                    "risk_score": 15.0,
                    "quality_score": 80.0,
                    "hot_score": 75.0,
                    "freshness_score": 90.0,
                    "source_weight_db": 3,
                    "feedback_score": 0,
                    "summary_source": "llm_lite",
                    "ai_tags": ["AI"],
                    "analysis_id": ids[key] * 10,
                    "analysis_created_at": datetime.now(UTC).isoformat(),
                }
            )
        muted = {ids["keyword_hit"], ids["domain_hit"], ids["source_hit"]}

        monkeypatch.setattr(today_picks, "query_today_picks", lambda **_kwargs: rows)
        monkeypatch.setattr(today_picks, "query_topics", lambda: [])

        async def _no_assignments(_self, _ids, *, visible_user_id):
            return {}

        async def _no_groups(_self, _group_ids, *, visible_user_id, member_limit, representatives):
            return {}

        monkeypatch.setattr(ContentEventConsumptionRepository, "resolve_today_pick_assignments", _no_assignments)
        monkeypatch.setattr(ContentEventConsumptionRepository, "load_display_groups", _no_groups)

        payload_alice = await today_picks.build_today_picks(db, owner_user_id=user_ids["alice"])
        visible_alice = {item["id"] for item in payload_alice["items"]}
        assert visible_alice & muted == set(), "alice 的三类静音规则应从精选中排除命中项"
        assert visible_alice, "非命中候选不应被静音规则清空"

        payload_bob = await today_picks.build_today_picks(db, owner_user_id=user_ids["bob"])
        visible_bob = {item["id"] for item in payload_bob["items"]}
        # 评分门与 mute 无关（percentile 阈值随候选池变化，两边入选集不可直接比），
        # 只断言用户口径：bob 不受 alice 规则影响，命中项对 bob 保持可见。
        assert visible_bob & muted, "bob 无规则，alice 静音命中的候选对 bob 应保持可见"
