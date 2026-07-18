from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.db_backend import (
    async_database_url,
    create_database_profile,
    database_backend,
    database_diagnostics,
    duckdb_attach_sql,
    duckdb_extension_name,
    ensure_aware_utc,
    redact_database_secrets,
    sqlite_domain_urls,
    sync_database_url,
)
from app.core.time import naive_utc_now


def test_sqlite_profile_and_duckdb_attach_sql(tmp_path):
    db_path = tmp_path / "topiceye.db"
    url = f"sqlite:///{db_path}"

    profile = create_database_profile(url)

    assert database_backend(url) == "sqlite"
    assert profile.is_sqlite
    assert profile.url.startswith("sqlite+aiosqlite:///")
    assert async_database_url(url).startswith("sqlite+aiosqlite:///")
    assert profile.sync_url.startswith("sqlite:///")
    assert profile.sqlite_path == str(db_path)
    assert duckdb_extension_name(profile) == "sqlite"
    assert duckdb_attach_sql(profile) == f"ATTACH '{db_path}' AS oltp_db (TYPE SQLITE, READ_ONLY)"

    diagnostics = database_diagnostics(profile)
    assert diagnostics["oltp"] == {
        "backend": "sqlite",
        "async_driver": "aiosqlite",
        "sync_driver": "sqlite",
        "sqlite_path": str(db_path),
        "sqlite_domain_split_enabled": False,
        "sqlite_domain_count": 0,
    }
    assert diagnostics["analytics"] == {
        "backend": "duckdb",
        "attach_source": "sqlite",
        "attach_mode": "read_only",
        "extension": "sqlite",
    }


def test_postgresql_profile_and_duckdb_attach_sql():
    url = "postgresql://topiceye:secret@localhost:5432/topiceye"

    profile = create_database_profile(url)

    assert database_backend(url) == "postgresql"
    assert profile.is_postgresql
    assert profile.url == "postgresql+asyncpg://topiceye:***@localhost:5432/topiceye".replace("***", "secret")
    assert async_database_url(url) == profile.url
    assert sync_database_url(url).startswith("postgresql+psycopg://")
    assert duckdb_extension_name(profile) == "postgres"
    attach_sql = duckdb_attach_sql(profile)
    assert "TYPE postgres" in attach_sql
    assert "READ_ONLY" in attach_sql
    assert "dbname=topiceye" in attach_sql
    assert "user=topiceye" in attach_sql
    assert "password=secret" in attach_sql

    diagnostics = database_diagnostics(profile)
    assert diagnostics["oltp"]["backend"] == "postgresql"
    assert diagnostics["oltp"]["async_driver"] == "asyncpg"
    assert diagnostics["oltp"]["sync_driver"] == "postgresql+psycopg"
    assert diagnostics["oltp"]["sqlite_path"] is None
    assert diagnostics["analytics"] == {
        "backend": "duckdb",
        "attach_source": "postgresql",
        "attach_mode": "read_only",
        "extension": "postgres",
    }
    assert "secret" not in str(diagnostics)


def test_postgres_alias_profile_uses_asyncpg_and_duckdb_postgres_attach():
    url = "postgres://topiceye:secret@localhost:5432/topiceye"

    profile = create_database_profile(url)

    assert database_backend(url) == "postgresql"
    assert profile.url == "postgresql+asyncpg://topiceye:secret@localhost:5432/topiceye"
    assert profile.sync_url == "postgresql+psycopg://topiceye:secret@localhost:5432/topiceye"
    assert profile.async_driver == "asyncpg"
    assert duckdb_extension_name(profile) == "postgres"
    assert "TYPE postgres" in duckdb_attach_sql(profile)


def test_database_secret_redaction_covers_urls_conninfo_and_attach_sql():
    url = "postgresql+asyncpg://topiceye:s3 cr'et@localhost:5432/topiceye"
    profile = create_database_profile(url)
    attach_sql = duckdb_attach_sql(profile)
    raw_error = f"failed for {url}; conninfo password='s3 cr\\'et'; attach={attach_sql}"

    redacted = redact_database_secrets(raw_error, profile)

    assert redacted is not None
    assert "s3 cr'et" not in redacted
    assert "password=***" in redacted
    assert "postgresql+asyncpg://topiceye:***@localhost:5432/topiceye" in redacted


def test_sqlite_domain_urls_are_explicit_opt_in(tmp_path):
    url = "sqlite+aiosqlite:///./topiceye.db"

    default_profile = create_database_profile(url, sqlite_domain_split_enabled=False)
    split_profile = create_database_profile(
        url,
        sqlite_domain_split_enabled=True,
        sqlite_domain_dir=str(tmp_path),
    )

    assert default_profile.sqlite_domain_urls == {}
    assert set(split_profile.sqlite_domain_urls) >= {"content", "topics", "trending", "webnovel", "ops"}
    assert sqlite_domain_urls(url, str(tmp_path))["content"].endswith("topiceye_content.db")


def test_database_profile_rejects_unsupported_backend():
    url = "mysql+aiomysql://topiceye:secret@localhost:3306/topiceye"

    assert database_backend(url) == "unknown"

    try:
        create_database_profile(url)
    except ValueError as exc:
        assert "Unsupported database backend for DATABASE_URL" in str(exc)
        assert "sqlite+aiosqlite://" in str(exc)
        assert "postgresql+asyncpg://" in str(exc)
    else:
        raise AssertionError("unsupported database backend should be rejected")


# ── 回归测试:naive/aware 混用 ──────────────────────────────
# 起因:content_repo.py 的 list_pending_or_stale 等函数用 datetime.now(UTC) 当
# SQL bind param,SQLite + aiosqlite 拒收 aware datetime,导致 scheduler 分析
# job 每次都抛 TypeError,间接导致 today_picks 永远空(无新内容入库)。
# 修复:统一用 naive_utc_now() 做 SQL bind,DB 读出用 ensure_aware_utc() 做
# Python 层比较。下列测试钉死这两个 helper 的契约。


def test_naive_utc_now_is_naive_and_close_to_now():
    """naive_utc_now 必须返回 naive datetime(无 tzinfo),且贴近 wall clock now()。"""
    before = datetime.now(UTC).replace(tzinfo=None)
    out = naive_utc_now()
    after = datetime.now(UTC).replace(tzinfo=None)

    assert out.tzinfo is None, "SQL bind param 必须 naive,aiosqlite 拒收 aware"
    # 1 秒容差,避免 wall clock 漂移
    assert before - timedelta(seconds=1) <= out <= after + timedelta(seconds=1)


def test_naive_utc_now_does_not_leak_local_timezone():
    """跨时区机器(开发机 vs 腾讯云 UTC)值应一致。naive_utc_now 是 UTC 时刻
    去掉 tzinfo,不是 wall clock 本地时间。"""
    naive = naive_utc_now()
    aware_utc = datetime.now(UTC)

    # naive 与 aware_utc 去掉 tzinfo 后差值应 < 1 秒(同一时刻)
    assert abs((naive - aware_utc.replace(tzinfo=None)).total_seconds()) < 1


def test_ensure_aware_utc_none_passthrough():
    assert ensure_aware_utc(None) is None


def test_ensure_aware_utc_naive_assumes_utc():
    """SQLite 读出的 DateTime(timezone=True) 是 naive(无 tzinfo),helper
    必须把它当 UTC 处理,不能当本地时间。"""
    naive = datetime(2026, 6, 20, 12, 0, 0)  # 无 tzinfo
    out = ensure_aware_utc(naive)
    assert out.tzinfo is not None
    assert out.utcoffset() == timedelta(0)
    assert out.year == 2026 and out.hour == 12


def test_ensure_aware_utc_aware_converts_to_utc():
    """从 PG 读出的 aware datetime 转 UTC(可能原是其他时区)。"""
    # 假设某模块写入 +08:00 时刻(应当避免,但需兼容)
    east8 = timezone(timedelta(hours=8))
    aware = datetime(2026, 6, 20, 20, 0, 0, tzinfo=east8)
    out = ensure_aware_utc(aware)
    assert out.utcoffset() == timedelta(0)
    assert out.hour == 12, "20:00 +08:00 应当转 12:00 UTC"


def test_ensure_aware_utc_round_trip_with_naive_utc_now():
    """最常用场景:DB 读出 naive(假设 UTC)→ ensure_aware_utc → 与 now(UTC) 比较不抛错。"""
    t = naive_utc_now()
    aware = ensure_aware_utc(t)
    # 不应该抛 TypeError
    assert (aware - datetime.now(UTC)) < timedelta(seconds=1)


@pytest.mark.asyncio
async def test_content_repo_list_pending_or_stale_works_on_sqlite_with_naive_cutoff():
    """用户线上报错的核心场景:list_pending_or_stale 用 naive cutoff 作为
    SQL bind param,SQLite 必须能跑通。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.models.content import ContentItem, ContentStatus
    from app.repositories.content_repo import ContentRepo

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        # 一条 PENDING 记录(应被命中)
        db.add(
            ContentItem(
                title="待分析",
                url="https://x/1",
                source_id=1,
                source_type="RSS",
                crawled_at=naive_utc_now() - timedelta(hours=2),
                category="AI",
                status=ContentStatus.PENDING,
            )
        )
        await db.commit()

        repo = ContentRepo(db)
        # 这一调用之前会抛 TypeError(aware datetime 给 aiosqlite)
        items = await repo.list_pending_for_analysis(limit=10, hours=48)

    await engine.dispose()
    assert len(items) == 1
    assert items[0].title == "待分析"
