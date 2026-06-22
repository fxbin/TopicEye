"""Alembic migration environment for TopicEye.

The migration URL is derived from settings.DATABASE_URL (sync form), so the
same env.py works for both SQLite and PostgreSQL. Autogenerate relies on the
full model metadata, so every ORM module must be imported here — mirroring the
imports in app/main.py that register tables onto Base.metadata.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── Make `app.*` importable when alembic runs from the backend dir ──────────
# alembic.ini sets prepend_sys_path = . (the backend dir), but be defensive.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Register every ORM table onto Base.metadata (must match app/main.py imports
# so autogenerate sees the full schema and create_all parity holds).
import app.models  # noqa: F401, E402  — triggers models/__init__.py
import app.models.analysis_job  # noqa: F401, E402
import app.models.category  # noqa: F401, E402
import app.models.daily_report  # noqa: F401, E402
import app.models.fanqie  # noqa: F401, E402
import app.models.favorite  # noqa: F401, E402
import app.models.feedback  # noqa: F401, E402
import app.models.llm_model  # noqa: F401, E402
import app.models.monthly_digest  # noqa: F401, E402
import app.models.mother_topic  # noqa: F401, E402
import app.models.notification  # noqa: F401, E402
import app.models.product_feedback  # noqa: F401, E402
import app.models.qimao  # noqa: F401, E402
import app.models.scheduled_job  # noqa: F401, E402
import app.models.trending  # noqa: F401, E402
import app.models.user  # noqa: F401, E402
import app.models.user_integration  # noqa: F401, E402
import app.models.weekly_digest  # noqa: F401, E402
import app.models.zhihu  # noqa: F401, E402
from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.db_backend import create_database_profile  # noqa: E402

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
# 关键:disable_existing_loggers=False。
# 默认 True 会把所有不在 alembic.ini [loggers] 里的 logger 标 disabled
# (包括 app.services.* 全部)。Alembic 在 lifespan startup / 测试 / CLI
# 调用 env.py 时,会让后续整个进程的 app logger 全 mute,导致:
# - pytest caplog.text 永远空(test_source_api / test_today_picks 失败)
# - 生产环境跑迁移后日志突然消失
# 改成 False 是 logging 最佳实践,不影响 alembic 自己的 logger 输出。
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Derive a sync URL from the configured DATABASE_URL. Alembic runs synchronously.
_profile = create_database_profile(
    settings.DATABASE_URL,
    sqlite_domain_split_enabled=settings.DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED,
    sqlite_domain_dir=settings.DATABASE_SQLITE_DOMAIN_DIR,
)
target_metadata = Base.metadata
_is_sqlite = _profile.is_sqlite


def _resolve_url() -> str:
    """Return the sync database URL for migrations."""
    return _profile.sync_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite lacks most ALTER forms; batch mode rebuilds tables instead.
        render_as_batch=_is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live engine)."""
    cfg_section = config.get_section(config.config_ini_section, {}) or {}
    cfg_section["sqlalchemy.url"] = _resolve_url()

    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
