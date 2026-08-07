import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.db_backend import create_database_profile

logger = logging.getLogger(__name__)

database_profile = create_database_profile(settings.DATABASE_URL)

engine = create_async_engine(
    database_profile.url,
    echo=False,
    pool_pre_ping=True,
)


# PG session 强制 UTC, 保证 aware datetime 写入/读取行为可预测
@event.listens_for(engine.sync_engine, "connect")
def set_pg_timezone(dbapi_connection, connection_record):
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
