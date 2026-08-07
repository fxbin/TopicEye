"""共享 pytest fixtures。

设计原则：向后兼容。现有测试各自搭建 in-memory DB，不强制迁移；
新测试可按需 ``Depends`` 这些 fixture 减少样板。

提供：
- ``test_engine`` / ``test_session_factory``：in-memory SQLite 引擎与会话工厂，
  schema 已 create_all，等价于各测试里的内联写法。用于纯业务逻辑单元测试。
- ``db``：单测试作用域的 AsyncSession（已绑定到上述工厂）。
- ``_ensure_test_db_schema`` (autouse session)：为集成测试在
  PostgreSQL 上建好 schema，绕开"DuckDB ATTACH 成功但表不存在"。

注意：每个测试函数拿到的是**独立**的内存库（function scope），避免跨用例
状态污染——这也是当前测试套件隐含的约定。

集成测试通过 ``async_session`` 访问的 PG 数据库由 ``clean_tables`` fixture
在每个测试前 TRUNCATE 清理。
"""

from __future__ import annotations

import asyncio
import os

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models.analysis_job  # noqa: F401
import app.models.app_setting  # noqa: F401
import app.models.category  # noqa: F401
import app.models.creation  # noqa: F401
import app.models.daily_report  # noqa: F401
import app.models.fanqie  # noqa: F401
import app.models.favorite  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.llm_model  # noqa: F401
import app.models.monthly_digest  # noqa: F401
import app.models.mother_topic  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.prompt_registry  # noqa: F401
import app.models.read_record  # noqa: F401
import app.models.source  # noqa: F401
import app.models.user  # noqa: F401
import app.models.user_integration  # noqa: F401
import app.models.weekly_digest  # noqa: F401
import app.models.zhihu  # noqa: F401
from app.core.database import Base


@pytest_asyncio.fixture
async def test_engine():
    """内存 SQLite 引擎，schema 已初始化。每个测试独立一份。

    用于纯业务逻辑单元测试——SQLite 在这里是快速的测试后端，
    不影响生产代码（生产代码已移除所有 SQLite 专属分支）。
    """
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


# ── Session-scoped fixture: 为集成测试在 PG 上建好 schema ──
@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db_schema():
    """一次性建好测试 DB 的 schema（PostgreSQL）。autouse=True 自动对所有 session 跑。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _init():
        engine = create_async_engine(os.environ["DATABASE_URL"])
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_init())
    yield
    # session 结束不删 schema(下个 session 复用,启动时 create_all 是 no-op)


# ── Function-scoped cleanup: 每个测试后清表(防止脏数据跨测试)──
# autouse=True 让所有测试在执行前先清表,避免 test 间的 state pollution。
@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    """每个测试前清空所有 ORM 表（PostgreSQL TRUNCATE CASCADE）。"""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        from sqlalchemy import text

        # TRUNCATE 所有表,PostgreSQL 支持 CASCADE 自动清理外键依赖
        table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
    await engine.dispose()
    yield


@pytest_asyncio.fixture(autouse=True)
async def reset_llm_provider_state():
    """每个测试前重置 LLM provider 模块级 state + logging 配置。

    LLM state:见下方注释。
    logging:某些测试(或导入的 app.main lifespan)会调 configure_logging,
    把 root logger 的 handler 改了,导致后续测试的 caplog.text 是空。
    autouse 在每个测试前重置 root logger 的 propagate=True,并把 handler
    恢复到 logging 默认状态(只有 caplog 自己的 handler 在最终被 pytest
    加上),保证 caplog 能抓到日志。
    """
    # ── 1. logging 重置 ──
    import logging

    root = logging.getLogger()
    # propagate 必须是 True,caplog handler 才能从子 logger 收到事件
    root.propagate = True
    # 清掉之前测试 configure_logging 加的非 pytest handler
    # (留 caplog 在 fixture setup 时挂的 handler,但 setup 还没跑,这里是空)
    for h in list(root.handlers):
        # pytest 的 caplog handler 类名包含 "_CapturingHandler",保留
        if "CapturingHandler" not in type(h).__name__ and "LogCapture" not in type(h).__name__:
            root.removeHandler(h)
    """每个测试前重置 LLM provider 模块级 state。

    test_llm_provider_routing 系列测试 monkeypatch.setattr(provider,
    '_call_with_retry', fake_call) 替换模块级 async 函数,且会调
    provider._failover.on_failure(...) 直接改 _failover 内部 dict。
    这些不是 monkeypatch 管理的 state,teardown 不会自动恢复,
    会污染下一个测试(导致 _model_cache / _failover 跨测试残留)。

    autouse 在每个测试前:
    1. await invalidate_model_cache() 清 _model_cache / _failover / rate_limiters
    2. del _call_with_retry(防 monkeypatch 没 revert,虽然实际它会)
    """
    try:
        from app.services.llm.provider import invalidate_model_cache

        await invalidate_model_cache()
        # 清 LLM response cache —— 这是 test_llm_provider_routing 跨测试污染的
        # 真正根因。call_llm_with_metadata 先查 response cache,测试 1/2 写的
        # cached response 会被测试 3 读到(命中相同 messages + temperature)。
        # invalidate_model_cache 不管 response cache,要单独清。
        from app.services.llm.response_cache import get_llm_cache

        get_llm_cache().clear()
    except Exception:
        pass

    # 显式删 _call_with_retry 等动态属性,防 monkeypatch 残留。
    # 注意:_call_with_retry 是模块级 async def,delattr 后 call_llm 内部
    # 直接 NameError。但 monkeypatch.setattr 在测试 setup 时会重建它。
    # 如果 delattr 时它本来就是原始函数,测试不 patch 它,call_llm 调用
    # 走原始路径,需要保留。所以只删 __module__ 不是 provider 的(=fake)。
    try:
        from app.services.llm import provider as provider_module

        for attr_name in ("_call_with_retry", "_call_with_metadata", "_call_completion"):
            current = getattr(provider_module, attr_name, None)
            if current is None:
                continue
            cur_mod = getattr(current, "__module__", None)
            # 拆分后 _call_with_retry 等的 __module__ 是 app.services.llm._call_engine
            # 等子模块（合法实现），只有 __module__ 不属于 app.services.llm 的才是
            # monkeypatch 注入的 fake_call 残留，需要删掉。
            if not (cur_mod or "").startswith("app.services.llm"):
                try:
                    delattr(provider_module, attr_name)
                except AttributeError:
                    pass
    except Exception:
        pass

    yield
