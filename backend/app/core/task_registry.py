"""受管后台任务注册表。

fire-and-forget 的 `create_task` 若不保存引用、不收集异常，会静默丢任务
（issue #72），且可能在优雅停机后仍与 `engine.dispose()` 竞争打开中的
session。本模块集中提供：

- `track_background_task(coro, *, name)`：创建任务并注册，done callback
  自动注销并在异常时记 error 日志（CancelledError 除外）；
- `drain_tracked_tasks(timeout)`：停机时统一 cancel + 等待，超时的残留
  任务记 warning 后放行（不强杀，避免打断不可取消的清理逻辑）。

兴趣向量重建（`interest_vector_service._rebuild_tasks`）是仓内同模式的
既有范例，本模块将其通用化。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def _detach(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task %s failed: %s", task.get_name(), exc, exc_info=exc)


def track_background_task(coro: Coroutine, *, name: str) -> asyncio.Task:
    """创建并注册受管后台任务；异常由 done callback 记日志，不再静默。"""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_detach)
    return task


async def drain_tracked_tasks(timeout: float = 30.0) -> None:
    """优雅停机：取消全部受管任务并在 timeout 内等待结束。"""
    if not _tasks:
        return
    for task in list(_tasks):
        task.cancel()
    done, pending = await asyncio.wait(set(_tasks), timeout=timeout)
    for task in pending:
        logger.warning("Background task %s outlived shutdown drain (timeout=%.0fs)", task.get_name(), timeout)
    _tasks.clear()
