from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.core.config import settings
from app.core.db_backend import create_database_profile, sqlalchemy_connect_args
import logging

logger = logging.getLogger(__name__)

database_profile = create_database_profile(
    settings.DATABASE_URL,
    sqlite_domain_split_enabled=settings.DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED,
    sqlite_domain_dir=settings.DATABASE_SQLITE_DOMAIN_DIR,
)

engine = create_async_engine(
    database_profile.url,
    echo=False,
    pool_pre_ping=True,
    connect_args=sqlalchemy_connect_args(database_profile),
)


# Enable WAL mode for SQLite to reduce lock contention
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if not database_profile.is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# PG session 强制 UTC, 保证 aware datetime 写入/读取行为可预测
@event.listens_for(engine.sync_engine, "connect")
def set_pg_timezone(dbapi_connection, connection_record):
    if not database_profile.is_postgresql:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
