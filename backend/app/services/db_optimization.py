"""
数据库性能优化迁移脚本。
修复缺失索引、批量写入、连接复用等瓶颈。

执行方式:
    cd backend && ./venv/bin/python -m app.services.db_optimization
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from app.config import settings
from app.core.db_backend import create_database_profile

logger = logging.getLogger(__name__)


def get_db_path() -> str:
    profile = create_database_profile(
        settings.DATABASE_URL,
        sqlite_domain_split_enabled=settings.DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED,
        sqlite_domain_dir=settings.DATABASE_SQLITE_DOMAIN_DIR,
    )
    if not profile.sqlite_path:
        raise RuntimeError("SQLite database path is only available for SQLite backends")
    return profile.sqlite_path


def get_sync_engine():
    """Get a synchronous engine for migration scripts."""
    from sqlalchemy import create_engine

    profile = create_database_profile(
        settings.DATABASE_URL,
        sqlite_domain_split_enabled=settings.DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED,
        sqlite_domain_dir=settings.DATABASE_SQLITE_DOMAIN_DIR,
    )
    return create_engine(profile.sync_url, echo=False)


def add_indexes(conn: sqlite3.Connection) -> None:
    """Add missing performance indexes."""

    indexes = [
        # content_items: crawled_at 用于所有时间范围查询
        (
            "content_items",
            "ix_content_items_crawled_at",
            "CREATE INDEX IF NOT EXISTS ix_content_items_crawled_at ON content_items(crawled_at)",
        ),
        # content_items: status + crawled_at 用于评分流、精选、统计等状态时间窗口查询
        (
            "content_items",
            "ix_content_items_status_crawled_at",
            "CREATE INDEX IF NOT EXISTS ix_content_items_status_crawled_at ON content_items(status, crawled_at DESC)",
        ),
        # content_items: source_id 用于 JOIN + 分组统计
        (
            "content_items",
            "ix_content_items_source_id",
            "CREATE INDEX IF NOT EXISTS ix_content_items_source_id ON content_items(source_id)",
        ),
        # content_items: topic_id 用于话题聚合查询
        (
            "content_items",
            "ix_content_items_topic_id",
            "CREATE INDEX IF NOT EXISTS ix_content_items_topic_id ON content_items(topic_id)",
        ),
        # ai_analyses: content_id 是最重要的 JOIN 键
        (
            "ai_analyses",
            "ix_ai_analyses_content_id",
            "CREATE INDEX IF NOT EXISTS ix_ai_analyses_content_id ON ai_analyses(content_id)",
        ),
        # ai_analyses: risk_score 用于过滤低质量分析结果
        (
            "ai_analyses",
            "ix_ai_analyses_risk_score",
            "CREATE INDEX IF NOT EXISTS ix_ai_analyses_risk_score ON ai_analyses(risk_score)",
        ),
        # ai_analyses: curation_score 用于排序和阈值筛选
        (
            "ai_analyses",
            "ix_ai_analyses_curation_score",
            "CREATE INDEX IF NOT EXISTS ix_ai_analyses_curation_score ON ai_analyses(curation_score)",
        ),
        # trending_items: crawled_at 用于时间范围筛选
        (
            "trending_items",
            "ix_trending_items_crawled_at",
            "CREATE INDEX IF NOT EXISTS ix_trending_items_crawled_at ON trending_items(crawled_at)",
        ),
        # trending_snapshots: snapshot_date 用于历史查询
        (
            "trending_snapshots",
            "ix_trending_snapshots_date",
            "CREATE INDEX IF NOT EXISTS ix_trending_snapshots_snapshot_date ON trending_snapshots(snapshot_date)",
        ),
    ]

    logger.info("开始添加索引...")
    added = 0
    for table, idx_name, sql in indexes:
        try:
            t0 = time.time()
            conn.execute(sql)
            elapsed = time.time() - t0
            logger.info(f"  + {idx_name} on {table} ({elapsed:.2f}s)")
            added += 1
        except sqlite3.OperationalError as e:
            if "already exists" in str(e) or "duplicate" in str(e).lower():
                logger.info(f"  = {idx_name} already exists, skipped")
            else:
                logger.error(f"  ✗ {idx_name}: {e}")

    logger.info(f"索引添加完成: {added} 新增")
    conn.commit()


def analyze_tables(conn: sqlite3.Connection) -> None:
    """Run ANALYZE to update SQLite query planner statistics."""
    logger.info("Running ANALYZE on all tables...")
    conn.execute("ANALYZE")
    conn.commit()
    logger.info("ANALYZE complete.")


def get_current_indexes(conn: sqlite3.Connection) -> dict:
    """Show current index status for all tables."""
    tables = ["content_items", "ai_analyses", "sources", "trending_items", "trending_snapshots"]
    result = {}
    for t in tables:
        cur = conn.execute(f"PRAGMA index_list({t})")
        result[t] = [r[1] for r in cur.fetchall()]
    return result


def optimize_pragmas(conn: sqlite3.Connection) -> None:
    """Apply performance-oriented PRAGMA settings."""
    pragmas = [
        ("cache_size", -64000),  # 64MB page cache (negative = KB)
        ("temp_store", "MEMORY"),  # Temp tables in memory
        ("mmap_size", 268435456),  # 256MB memory-mapped I/O
        ("threads", 4),  # Enable multi-threading
    ]

    for name, value in pragmas:
        try:
            conn.execute(f"PRAGMA {name}={value}")
            logger.info(f"PRAGMA {name}={value} applied")
        except Exception as e:
            logger.warning(f"PRAGMA {name} failed: {e}")


def run_migration() -> None:
    profile = create_database_profile(
        settings.DATABASE_URL,
        sqlite_domain_split_enabled=settings.DATABASE_SQLITE_DOMAIN_SPLIT_ENABLED,
        sqlite_domain_dir=settings.DATABASE_SQLITE_DOMAIN_DIR,
    )
    if not profile.is_sqlite:
        logger.info(
            "db_optimization currently contains SQLite PRAGMA/index maintenance only; skip for backend=%s",
            profile.backend,
        )
        return

    db_path = get_db_path()
    db_path = str(Path(db_path).resolve())
    logger.info(f"Database: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    # Show before
    logger.info("\n=== 优化前索引状态 ===")
    before = get_current_indexes(conn)
    for t, idxs in before.items():
        logger.info(f"  {t}: {idxs or '(no indexes)'}")

    file_size = Path(db_path).stat().st_size / 1024 / 1024
    logger.info(f"\nDB size: {file_size:.1f} MB")

    # Run optimizations
    logger.info("\n=== 添加索引 ===")
    add_indexes(conn)

    logger.info("\n=== 优化 PRAGMA 参数 ===")
    optimize_pragmas(conn)

    logger.info("\n=== 更新查询计划统计 ===")
    analyze_tables(conn)

    # Show after
    logger.info("\n=== 优化后索引状态 ===")
    after = get_current_indexes(conn)
    for t, idxs in after.items():
        logger.info(f"  {t}: {idxs}")

    conn.close()
    logger.info("\n优化完成 ✓")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_migration()
