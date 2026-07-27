"""
启动时 PG sequence 同步自检。

背景：历史数据导入（COPY/INSERT 显式指定 id）会让 SERIAL sequence
停留在旧值，而表里已有更大的 id。后续 INSERT 让 PG 用 sequence
生成 id 时会撞到已存在的行 → UniqueViolationError → 事务 abort
→ 整个写入路径挂掉（content_pipeline 抓取全部失败的根因）。

本模块在启动 migration 之后遍历所有有 SERIAL sequence 的表，
把 sequence 推进到 max(id)。SQLite 跳过（INTEGER PRIMARY KEY
自动管理 rowid，无此问题）。

幂等：sequence 已经 >= max(id) 时不做任何事。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.core.database import async_session, database_profile

logger = logging.getLogger(__name__)


async def ensure_sequences_synced() -> list[str]:
    """检查并修复所有 PG SERIAL sequence。

    Returns: 修复了的 ``table.column`` 列表（空 = 全部正常）。
    """
    if not database_profile.is_postgresql:
        # SQLite 无 sequence 概念，INTEGER PRIMARY KEY 自动管理
        return []

    fixed: list[str] = []

    async with async_session() as db:
        # 发现所有有 SERIAL sequence 的 (table, column)
        rows = await db.execute(
            text("""
            SELECT c.relname AS table_name,
                   a.attname AS column_name
            FROM pg_class c
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE c.relkind = 'r'
              AND c.relnamespace = 'public'::regnamespace
              AND a.attisdropped = false
              AND pg_get_serial_sequence(c.relname::text, a.attname) IS NOT NULL
        """)
        )

        candidates = [(r[0], r[1]) for r in rows]
        if not candidates:
            return []

        for table_name, column_name in candidates:
            # 系统表名/列名来自 PG catalog，不是用户输入，无注入风险
            pg_get_serial_value(db, table_name, column_name)
            max_id = await get_max_id(db, table_name, column_name)
            curr_val = await get_seq_last_value(db, table_name, column_name)

            if curr_val is not None and max_id is not None and curr_val < max_id:
                await db.execute(
                    text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{column_name}'), {max_id}, true)")
                )
                fixed.append(f"{table_name}.{column_name}: {curr_val} → {max_id}")

        if fixed:
            await db.commit()
            logger.warning(
                "Sequences resynced at startup (%d tables): %s",
                len(fixed),
                fixed,
            )
        else:
            logger.info("Startup sequence check: all %d sequences in sync", len(candidates))

    return fixed


async def get_max_id(db, table_name: str, column_name: str):
    result = await db.execute(text(f"SELECT COALESCE(MAX({column_name}), 0) FROM {table_name}"))
    return result.scalar()


async def get_seq_last_value(db, table_name: str, column_name: str):
    """获取 sequence 的 last_value。表为空时 sequence 可能未初始化。"""
    seq_name = f"{table_name}_{column_name}_seq"
    try:
        result = await db.execute(text(f"SELECT last_value FROM {seq_name}"))
        return result.scalar()
    except Exception:
        return None


def pg_get_serial_value(db, table_name: str, column_name: str):
    """Placeholder for potential future use."""
    return None
