"""受管后台任务注册表回归（#72 / D-9）。

钉死三条契约：
- 异常任务由 done callback 记 error 日志并自动注销（不再静默丢失）；
- drain 取消并等待全部受管任务，注册表清空；
- drain 超时的残留任务记 warning 且不抛出。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.core import task_registry
from app.core.task_registry import drain_tracked_tasks, track_background_task


@pytest.fixture(autouse=True)
def _clean_registry():
    task_registry._tasks.clear()
    yield
    task_registry._tasks.clear()


@pytest.mark.asyncio
async def test_failed_task_is_logged_and_discarded(caplog):
    async def boom():
        raise RuntimeError("bg exploded")

    task = track_background_task(boom(), name="boom-task")
    with caplog.at_level(logging.ERROR, logger="app.core.task_registry"):
        await asyncio.wait({task})  # 不直接 await：那会把任务异常重抛进用例

    assert task not in task_registry._tasks
    assert any("bg exploded" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_drain_cancels_and_clears_pending_tasks():
    async def sleeper():
        await asyncio.sleep(60)

    task = track_background_task(sleeper(), name="sleeper")
    await drain_tracked_tasks(timeout=1.0)

    assert task.cancelled() or task.done()
    assert not task_registry._tasks


@pytest.mark.asyncio
async def test_drain_timeout_warns_and_does_not_raise(caplog):
    async def stubborn():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # 吞掉取消再短暂收尾，模拟不可及时取消的任务
            await asyncio.sleep(0.05)

    task = track_background_task(stubborn(), name="stubborn")
    await asyncio.sleep(0)  # 让任务真正起跑：未启动即 cancel 会直接终态 cancelled
    with caplog.at_level(logging.WARNING, logger="app.core.task_registry"):
        await drain_tracked_tasks(timeout=0.01)

    assert any("outlived shutdown drain" in r.getMessage() for r in caplog.records)
    assert not task_registry._tasks
    # 给残留任务机会收尾，避免泄漏到后续用例
    await asyncio.wait([task], timeout=5)


@pytest.mark.asyncio
async def test_drain_empty_registry_is_noop():
    await drain_tracked_tasks()  # 不应抛出
