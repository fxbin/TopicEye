"""模块级 engine 跨事件循环隔离的回归测试(#97)。

pytest-asyncio 为每个测试创建新事件循环;``app.core.database.engine`` 是
模块级单例,其连接池若把上一个循环创建的 asyncpg 连接留给下一个测试复用,
后者一执行真实 SQL 就报 "Future ... attached to a different loop",并引发
后续 PG 测试连环 mass-E。conftest 的 ``dispose_module_engine_connections``
fixture 在每个测试后清空连接池。

下面两个**顺序敏感**的测试各自从模块 engine checkout 并执行真实 SQL:
若跨循环隔离回归(比如 fixture 被移除),第二个测试必然失败——这就是本
缺陷的机器化回归锚点。请保持它们为两个独立测试函数、文件内字母序执行。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.database import async_session


@pytest.mark.asyncio
async def test_loop_a_checkout_and_release():
    """第一个循环:从模块 engine 拿连接、执行、归还池中。"""
    async with async_session() as db:
        val = (await db.execute(text("SELECT 41 + 1"))).scalar()
    assert val == 42


@pytest.mark.asyncio
async def test_loop_b_checkout_after_previous_loop():
    """第二个循环:若复用上一循环留在池里的连接即报 different loop。"""
    async with async_session() as db:
        val = (await db.execute(text("SELECT 43 - 1"))).scalar()
    assert val == 42
