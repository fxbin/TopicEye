from app.core.db_backend import (
    async_database_url,
    create_database_profile,
    database_backend,
    database_diagnostics,
    duckdb_attach_sql,
    duckdb_extension_name,
    redact_database_secrets,
    sqlite_domain_urls,
    sync_database_url,
)


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
