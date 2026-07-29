from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.content import ContentItem, ContentStatus
from app.models.content_event import ContentEventGroup, ContentEventMember
from app.models.content_event_run import (
    ContentEventNormalizationLease,
    ContentEventNormalizationRun,
)
from app.repositories.content_event_normalization_repo import (
    ContentEventNormalizationRepository,
)
from app.services import content_event_normalization as normalization
from app.services.content_event_normalization import (
    normalize_recent_events_with_lease,
)
from app.services.content_event_service import (
    ContentEventConflictError,
    ContentEventService,
)


@pytest_asyncio.fixture
async def normalization_db(tmp_path, monkeypatch):
    path = tmp_path / "normalization.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(normalization, "async_session", factory)
    yield factory
    await engine.dispose()


async def _content(
    db,
    title: str,
    *,
    hour: int,
    source_name: str,
    owner_user_id: int | None = None,
) -> ContentItem:
    moment = datetime(2026, 7, 29, 8, tzinfo=UTC) + timedelta(hours=hour)
    content = ContentItem(
        title=title,
        url=f"https://example.com/{source_name}/{hour}",
        source_name=source_name,
        source_type="rss",
        owner_user_id=owner_user_id,
        status=ContentStatus.ANALYZED,
        published_at=moment,
        crawled_at=moment,
        created_at=moment,
    )
    db.add(content)
    await db.flush()
    return content


@pytest.mark.asyncio
async def test_shadow_uses_local_fast_path_without_event_mutation(
    normalization_db,
    monkeypatch,
):
    async with normalization_db() as db:
        first = await _content(
            db,
            "模型池提升推理吞吐",
            hour=0,
            source_name="AIHOT",
        )
        second = await _content(
            db,
            "模型池提升推理吞吐",
            hour=1,
            source_name="AIHOT",
        )
        await db.commit()

        async def fail_llm(*args, **kwargs):
            raise AssertionError("exact local match must not call the LLM")

        monkeypatch.setattr(normalization, "call_llm_json", fail_llm)
        result = await normalize_recent_events_with_lease(
            db,
            hours=720,
            mode="shadow",
            owner_user_id=None,
            idempotency_key="shadow-local",
        )
        await db.commit()

        assert result["scanned"] == 2
        assert result["standalone"] == 1
        assert result["matched"] == 1
        assert result["created_events"] == 0
        assert result["created_members"] == 0
        assert (
            await db.scalar(select(func.count()).select_from(ContentEventGroup))
        ) == 0
        assert (
            await db.scalar(select(func.count()).select_from(ContentEventMember))
        ) == 0
        await db.refresh(first)
        await db.refresh(second)
        assert first.duplicate_of is None
        assert second.duplicate_of is None


@pytest.mark.asyncio
async def test_write_recalls_historical_canonical_and_replays_idempotently(
    normalization_db,
    monkeypatch,
):
    async with normalization_db() as db:
        canonical = await _content(
            db,
            "Codex 重置限额优化",
            hour=0,
            source_name="AIHOT",
        )
        group = await ContentEventService(db).create_event(
            [canonical.id],
            owner_user_id=None,
        )
        incoming = await _content(
            db,
            "Codex 重置限额优化",
            hour=2,
            source_name="AIHOT",
        )
        await db.commit()

        async def fail_llm(*args, **kwargs):
            raise AssertionError("historical exact match must stay on local path")

        monkeypatch.setattr(normalization, "call_llm_json", fail_llm)
        first_result = await normalize_recent_events_with_lease(
            db,
            hours=720,
            mode="write",
            owner_user_id=None,
            idempotency_key="historical-write",
        )
        await db.commit()
        replay_result = await normalize_recent_events_with_lease(
            db,
            hours=720,
            mode="write",
            owner_user_id=None,
            idempotency_key="historical-write",
        )

        member = await db.scalar(
            select(ContentEventMember).where(
                ContentEventMember.content_id == incoming.id
            )
        )
        assert member is not None
        assert member.event_group_id == group.id
        assert first_result["created_members"] == 1
        assert replay_result["run_id"] == first_result["run_id"]
        assert replay_result["replayed"] is True
        assert replay_result["mode"] == "write"
        assert replay_result["created_members"] == 1
        assert (
            await db.scalar(
                select(func.count()).select_from(ContentEventNormalizationRun)
            )
        ) == 1

        with pytest.raises(ContentEventConflictError, match="different mode or hours"):
            await normalize_recent_events_with_lease(
                db,
                hours=720,
                mode="shadow",
                owner_user_id=None,
                idempotency_key="historical-write",
            )
        with pytest.raises(ContentEventConflictError, match="different mode or hours"):
            await normalize_recent_events_with_lease(
                db,
                hours=1,
                mode="write",
                owner_user_id=None,
                idempotency_key="historical-write",
            )


@pytest.mark.asyncio
async def test_llm_failure_and_cap_create_pending_without_projection(
    normalization_db,
    monkeypatch,
):
    monkeypatch.setattr(
        normalization.settings,
        "EVENT_NORMALIZATION_MAX_BOUNDARY_LLM_CALLS",
        1,
    )
    calls = 0

    async def unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("pool unavailable")

    monkeypatch.setattr(normalization, "call_llm_json", unavailable)
    async with normalization_db() as db:
        first = await _content(
            db,
            "GLM 5.2 发布模型池能力",
            hour=0,
            source_name="Publisher-A",
        )
        second = await _content(
            db,
            "GLM 5.2 发布模型池能力",
            hour=1,
            source_name="Publisher-B",
        )
        third = await _content(
            db,
            "GLM 5.2 发布模型池能力",
            hour=2,
            source_name="Publisher-C",
        )
        await db.commit()

        result = await normalize_recent_events_with_lease(
            db,
            hours=720,
            mode="write",
            owner_user_id=None,
            idempotency_key="llm-cap",
        )
        await db.commit()

        assert calls == 1
        assert result["llm_calls"] == 1
        assert result["pending"] == 2
        assert result["created_events"] == 1
        assert result["created_members"] == 2
        for content in (first, second, third):
            await db.refresh(content)
            assert content.duplicate_of is None


@pytest.mark.asyncio
async def test_public_scope_never_reads_private_content(normalization_db):
    async with normalization_db() as db:
        await _content(
            db,
            "公共消息",
            hour=0,
            source_name="public",
        )
        await _content(
            db,
            "公共消息",
            hour=1,
            source_name="private",
            owner_user_id=88,
        )
        await db.commit()

        result = await normalize_recent_events_with_lease(
            db,
            hours=720,
            mode="shadow",
            owner_user_id=None,
            idempotency_key="public-isolation",
        )
        await db.commit()

        assert result["scanned"] == 1
        run = await db.scalar(select(ContentEventNormalizationRun))
        assert run is not None
        assert run.scope_key == "public"
        assert run.owner_user_id is None


@pytest.mark.asyncio
async def test_only_analyzed_content_enters_normalization(normalization_db):
    async with normalization_db() as db:
        analyzed = await _content(
            db,
            "已分析内容",
            hour=0,
            source_name="ready",
        )
        pending = await _content(
            db,
            "待处理内容",
            hour=1,
            source_name="pending",
        )
        analyzing = await _content(
            db,
            "分析中内容",
            hour=2,
            source_name="analyzing",
        )
        failed = await _content(
            db,
            "失败内容",
            hour=3,
            source_name="failed",
        )
        pending.status = ContentStatus.PENDING
        analyzing.status = ContentStatus.ANALYZING
        failed.status = ContentStatus.ERROR
        await db.commit()
        analyzed_id = analyzed.id

        result = await normalize_recent_events_with_lease(
            db,
            hours=720,
            mode="shadow",
            owner_user_id=None,
            idempotency_key="analyzed-only",
        )
        await db.commit()

        assert result["scanned"] == 1
        run = await db.get(ContentEventNormalizationRun, result["run_id"])
        assert run is not None
        await db.refresh(run)
        assert [item["content_id"] for item in run.predictions] == [analyzed_id]


@pytest.mark.asyncio
async def test_stale_fencing_token_cannot_release_new_lease(normalization_db):
    moment = datetime.now(UTC)
    async with normalization_db() as first_db:
        first_repo = ContentEventNormalizationRepository(first_db)
        await first_repo.begin_claim_transaction()
        first_fence = await first_repo.claim_lease(
            scope_key="public",
            lease_token="old",
            now=moment,
            expires_at=moment - timedelta(seconds=1),
        )
        await first_db.commit()

    async with normalization_db() as second_db:
        second_repo = ContentEventNormalizationRepository(second_db)
        await second_repo.begin_claim_transaction()
        second_fence = await second_repo.claim_lease(
            scope_key="public",
            lease_token="new",
            now=moment,
            expires_at=moment + timedelta(minutes=5),
        )
        await second_db.commit()

    async with normalization_db() as stale_db:
        stale_repo = ContentEventNormalizationRepository(stale_db)
        released = await stale_repo.release_lease(
            scope_key="public",
            lease_token="old",
            fencing_token=int(first_fence),
            now=moment,
        )
        await stale_db.commit()
        assert released is False
        lease = await stale_db.get(ContentEventNormalizationLease, "public")
        assert lease is not None
        assert lease.lease_token == "new"
        assert second_fence == int(first_fence) + 1


@pytest.mark.asyncio
async def test_expired_lease_cannot_finish_without_being_reclaimed(
    normalization_db,
):
    moment = datetime.now(UTC)
    async with normalization_db() as db:
        repo = ContentEventNormalizationRepository(db)
        await repo.begin_claim_transaction()
        fencing_token = await repo.claim_lease(
            scope_key="public",
            lease_token="expired-owner",
            now=moment,
            expires_at=moment + timedelta(seconds=1),
        )
        await db.commit()

        assert fencing_token == 1
        assert await repo.lock_current_lease(
            scope_key="public",
            lease_token="expired-owner",
            fencing_token=1,
            now=moment + timedelta(seconds=2),
        ) is False


@pytest.mark.asyncio
async def test_active_scope_lease_rejects_competing_run(normalization_db):
    limits = normalization._limits()
    first = await normalization._claim_run(
        owner_user_id=None,
        idempotency_key="lease-first",
        mode="shadow",
        hours=24,
        limits=limits,
    )
    with pytest.raises(ContentEventConflictError, match="lease is active"):
        await normalization._claim_run(
            owner_user_id=None,
            idempotency_key="lease-second",
            mode="shadow",
            hours=24,
            limits=limits,
        )
    await normalization._fail_claim(first, RuntimeError("test cleanup"))


@pytest.mark.asyncio
async def test_scheduler_off_has_no_database_or_service_side_effect(monkeypatch):
    from app import scheduler as scheduler_module

    monkeypatch.setattr(
        scheduler_module.settings,
        "EVENT_NORMALIZATION_ROLLOUT_MODE",
        "off",
    )

    class FailSessionFactory:
        def __call__(self):
            raise AssertionError("off mode must not open a database session")

    monkeypatch.setattr(
        scheduler_module,
        "async_session",
        FailSessionFactory(),
    )
    result = await scheduler_module._normalize_content_events()
    assert result == {"status": "off", "scanned": 0}


def test_prediction_audit_respects_default_json_byte_limit(monkeypatch):
    predictions = [
        {
            "content_id": index,
            "reason": "中文边界判断" * 20,
        }
        for index in range(5)
    ]
    for configured_cap in (2, 32, 128, 512):
        truncated = normalization._truncate_predictions(
            predictions,
            max_bytes=configured_cap,
        )
        assert len(json.dumps(truncated).encode("utf-8")) <= max(
            2,
            configured_cap,
        )

    monkeypatch.setattr(
        normalization.settings,
        "EVENT_NORMALIZATION_PREDICTION_AUDIT_MAX_BYTES",
        1,
    )
    assert normalization._limits().audit_max_bytes == 2
    assert normalization._truncate_predictions(
        predictions,
        max_bytes=1,
    ) == []


def test_run_model_matches_migration_contract():
    run_table = ContentEventNormalizationRun.__table__
    lease_table = ContentEventNormalizationLease.__table__
    assert {"scope_key", "idempotency_key", "fencing_token", "predictions"} <= set(
        run_table.columns.keys()
    )
    assert {"scope_key", "fencing_token", "lease_token", "lease_expires_at"} == set(
        lease_table.columns.keys()
    ) - {"updated_at"}
    assert any(
        constraint.name == "uq_content_event_normalization_runs_scope_key"
        for constraint in run_table.constraints
    )
