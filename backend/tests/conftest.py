"""共享 pytest fixtures。

设计原则：向后兼容。现有 70 个测试各自搭建 in-memory DB，不强制迁移；
新测试可按需 ``Depends`` 这些 fixture 减少样板。

提供：
- ``test_engine`` / ``test_session_factory``：in-memory SQLite 引擎与会话工厂，
  schema 已 create_all，等价于各测试里的内联写法。
- ``db``：单测试作用域的 AsyncSession（已绑定到上述工厂）。

注意：每个测试函数拿到的是**独立**的内存库（function scope），避免跨用例
状态污染——这也是当前测试套件隐含的约定。

未做 autouse 全局缓存清理：经实测会破坏依赖缓存状态的用例
（test_cache_warmup 等）。如需清缓存，请在测试内部显式调用
``invalidate_*_cache()``。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base


@pytest_asyncio.fixture
async def test_engine():
    """内存 SQLite 引擎，schema 已初始化。每个测试独立一份。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session_factory(test_engine) -> async_sessionmaker[AsyncSession]:
    """绑定到 test_engine 的会话工厂，与生产 async_session 同构。"""
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(test_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """单次测试用 AsyncSession，自动 commit/rollback。"""
    async with test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
