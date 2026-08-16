from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.feedback import submit_feedback
from app.core.database import Base
from app.models.content import ContentItem, ContentStatus
from app.schemas.feedback import FeedbackCreate
from app.services.duckdb_service import LATEST_FEEDBACK_SCORES_CTE
from app.services.feedback_signal import get_feedback_scores


def feedback_content(content_id: int = 1) -> ContentItem:
    return ContentItem(
        id=content_id,
        title=f"反馈样本 {content_id}",
        url=f"https://example.com/feedback/{content_id}",
        source_name="测试信源",
        source_type="RSS",
        status=ContentStatus.ANALYZED,
    )


def test_duckdb_feedback_scores_use_latest_per_user_votes():
    assert "PARTITION BY f.content_id, f.user_id" in LATEST_FEEDBACK_SCORES_CTE
    assert "ORDER BY f.created_at DESC, f.id DESC" in LATEST_FEEDBACK_SCORES_CTE
    assert "WHERE feedback_rank = 1" in LATEST_FEEDBACK_SCORES_CTE


def test_duckdb_feedback_scores_cte_executes_latest_per_user_votes():
    import duckdb

    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE SCHEMA oltp_db")
        conn.execute("""
            CREATE TABLE oltp_db.user_feedback (
                id INTEGER,
                content_id INTEGER,
                user_id INTEGER,
                score_delta DOUBLE,
                created_at TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO oltp_db.user_feedback VALUES
                (1, 1, 1, 20.0, '2026-01-01 00:00:00'),
                (2, 1, 1, -20.0, '2026-01-02 00:00:00'),
                (3, 1, 2, 10.0, '2026-01-01 00:00:00')
        """)

        score = conn.execute(f"""
            WITH {LATEST_FEEDBACK_SCORES_CTE}
            SELECT feedback_score
            FROM feedback_scores
            WHERE content_id = 1
        """).fetchone()[0]
    finally:
        conn.close()

    assert score == -10.0


@pytest.mark.asyncio
async def test_feedback_aggregates_multiple_users_and_updates_own_vote():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(feedback_content(1))
        await db.flush()

        first = await submit_feedback(
            FeedbackCreate(content_id=1, feedback_type="great_pick", comment="up"),
            db,
            SimpleNamespace(id=1),
        )
        second = await submit_feedback(
            FeedbackCreate(content_id=1, feedback_type="like", comment="also useful"),
            db,
            SimpleNamespace(id=2),
        )
        revised = await submit_feedback(
            FeedbackCreate(content_id=1, feedback_type="not_relevant", comment="down"),
            db,
            SimpleNamespace(id=1),
        )

        assert revised.id == first.id
        assert revised.user_id == 1
        assert revised.score_delta == -20.0
        assert second.id != first.id
        assert second.user_id == 2
        assert second.score_delta == 10.0

        scores = await get_feedback_scores(db, [1])
        assert scores == {1: -10.0}

    await engine.dispose()


@pytest.mark.asyncio
async def test_feedback_overwrite_keeps_one_record_per_user_content_pair():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(feedback_content(1))
        await db.flush()
        first = await submit_feedback(
            FeedbackCreate(content_id=1, feedback_type="like", comment="first"),
            db,
            SimpleNamespace(id=1),
        )
        second = await submit_feedback(
            FeedbackCreate(content_id=1, feedback_type="great_pick", comment="second"),
            db,
            SimpleNamespace(id=1),
        )

        scores = await get_feedback_scores(db, [1])
        assert first.id == second.id
        assert scores == {1: 20.0}

    await engine.dispose()


@pytest.mark.asyncio
async def test_feedback_rejects_missing_content():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            await submit_feedback(
                FeedbackCreate(content_id=404, feedback_type="great_pick", comment="missing"),
                db,
                SimpleNamespace(id=1),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Content not found"

    await engine.dispose()
