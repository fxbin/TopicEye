"""降级内容补分析（requeue）——#90 的核心修复。

LLM 降级路径（熔断 / 内容过滤 / 预算三种触发源）曾把内容写成
``ANALYZED`` 终态后永久结疤（假分 61-64 窄带、无任何消费者捡起）。
本模块在触发原因消除后把 ``summary_source='local_fallback'`` 的内容
重置回 PENDING，让既有分析队列重新拿真实 LLM 分析——把「永久疤」
变成「一过性」。

门控与限速（防预算临界值附近的反复横跳）：

- **预算余量门控**：最紧启用窗口余量 < 30% 时不发起（fail-closed，
  见 budget_guard.budget_headroom_ok）；
- **冷却**：降级落库后至少等 60 分钟才可回收；
- **限量**：每轮最多 50 条，最旧优先。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.content_repo import ContentRepo
from app.services.llm.budget_guard import budget_headroom_ok

logger = logging.getLogger(__name__)


async def requeue_local_fallback_content(
    db: AsyncSession,
    *,
    limit: int = 50,
    cooldown_minutes: int = 60,
) -> int:
    """预算余量充足时，把降级内容重置回待分析。返回重置条数。"""
    if not await budget_headroom_ok(min_ratio=0.3):
        logger.info("Analysis requeue: LLM budget headroom insufficient, deferring")
        return 0

    count = await ContentRepo(db).reset_local_fallback_for_reanalysis(
        limit=limit,
        cooldown_minutes=cooldown_minutes,
    )
    if count:
        # 恢复是用户可感知的质量事件，按 warning 级别留痕（不是静默修复）
        logger.warning("Analysis requeue: reset %d local_fallback content item(s) back to PENDING", count)
    return count
