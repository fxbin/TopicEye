"""cleanup_expired_codes 的服务级测试。

回归背景：该函数曾是死代码——没有任何调度或 API 调用方，
email_verification_codes 表随时间无限增长。2026-09-05 起由每日
03:50 的调度任务调用。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.email_verification import EmailVerificationCode
from app.services.email_verification_service import cleanup_expired_codes


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


def _code(email: str, *, expires_at: datetime) -> EmailVerificationCode:
    return EmailVerificationCode(email=email, code_hash="x" * 64, expires_at=expires_at)


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_codes(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add_all(
            [
                _code("expired@example.com", expires_at=now - timedelta(hours=3)),
                _code("fresh@example.com", expires_at=now + timedelta(minutes=10)),
            ]
        )
        await db.commit()

        removed = await cleanup_expired_codes(db)
        await db.commit()
        assert removed == 1

        remaining = (await db.execute(select(EmailVerificationCode))).scalars().all()
        assert [row.email for row in remaining] == ["fresh@example.com"]


@pytest.mark.asyncio
async def test_cleanup_recently_expired_within_retention_is_kept(session_factory):
    """清理窗口为 1 小时：刚过期不足 1 小时的记录应保留。"""
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(_code("just-expired@example.com", expires_at=now - timedelta(minutes=30)))
        await db.commit()

        removed = await cleanup_expired_codes(db)
        await db.commit()
        assert removed == 0
