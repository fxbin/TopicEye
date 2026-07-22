"""阅读记录服务层。

职责：
1. report_session: 幂等 upsert 一次阅读会话——已有记录则累加，否则新建（带偏好快照）。
2. list_history: 查询用户阅读历史。
3. cleanup_old_records: 按保留期（180 天）清理过期记录，供 scheduler 调用。

事务边界：本服务只 flush，commit 由 api 层 get_db 依赖或 scheduler wrapper 控制。
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.read_record import ReadDepth, ReadRecord
from app.repositories.read_record_repo import ReadRecordRepository
from app.schemas.read_record import ReadRecordReport

logger = logging.getLogger(__name__)

# 阅读记录保留期：180 天。
# 弱于监控快照（7 天），强于永不清理的报告数据。
# 半年窗口足够覆盖偏好建模的回溯需求。
READ_RECORD_RETENTION_DAYS = 180

# 深度阅读阈值：累计时长超过该值视为 deep_read（第一版简单阈值，后续可结合 max_progress）。
DEEP_READ_THRESHOLD_MS = 60_000  # 60 秒


def _derive_depth(read_count: int, accumulated_ms: int) -> ReadDepth:
    """根据累计指标派生阅读深度（第一版仅按时长+次数）。"""
    if read_count >= 3 or accumulated_ms >= DEEP_READ_THRESHOLD_MS:
        return ReadDepth.DEEP_READ
    return ReadDepth.READ


async def report_session(db: AsyncSession, user_id: int, data: ReadRecordReport) -> ReadRecord:
    """幂等上报一次阅读会话。

    已有记录：累加 read_count / accumulated_ms，刷新 last_read_at，重算 depth。
    无记录：新建，落库偏好快照（topic_keywords/category）。

    返回最新记录实例（已 flush，调用方负责 commit）。
    """
    repo = ReadRecordRepository(db)
    existing = await repo.find_existing(user_id, data.target_type, data.target_key)

    if existing is not None:
        await repo.merge_session(
            existing,
            duration_ms=data.duration_ms,
            topic_keywords=data.topic_keywords,
            category=data.category,
        )
        # 重算 depth（基于累计指标）
        existing.depth = _derive_depth(existing.read_count, existing.accumulated_ms)
        await db.flush()
        logger.info(
            "read_record merged user=%s target=%s/%s count=%d ms=%d",
            user_id, data.target_type, data.target_key, existing.read_count, existing.accumulated_ms,
        )
        return existing

    record = repo.add_new(
        user_id=user_id,
        target_type=data.target_type,
        target_key=data.target_key,
        target_id=data.target_id,
        duration_ms=data.duration_ms,
        topic_keywords=data.topic_keywords,
        category=data.category,
    )
    await db.flush()
    logger.info(
        "read_record created user=%s target=%s/%s",
        user_id, data.target_type, data.target_key,
    )
    return record


async def list_history(
    db: AsyncSession,
    user_id: int,
    target_type: str | None = None,
    limit: int = 100,
) -> Sequence:
    """查询用户阅读历史（按 last_read_at DESC）。"""
    repo = ReadRecordRepository(db)
    return await repo.list_by_user(user_id, target_type=target_type, limit=limit)


async def cleanup_old_records(db: AsyncSession, days: int = READ_RECORD_RETENTION_DAYS) -> int:
    """删除 last_read_at 早于保留期的记录，返回删除行数。

    供 scheduler cleanup job 调用，wrapper 负责 commit。
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    repo = ReadRecordRepository(db)
    removed = await repo.delete_older_than(cutoff)
    logger.info("read_record cleanup: removed %d records older than %d days", removed, days)
    return removed
