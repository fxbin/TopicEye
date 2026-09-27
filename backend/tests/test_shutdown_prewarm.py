"""停机预热任务回收回归（#73 / D-10）。

钉死 _shutdown_prewarm_tasks 的三条契约：
- 缓存预热任务带非 CancelledError 异常结束时：记 warning、不向调用方抛出
  （否则会跳过调度器停机 / DuckDB 关闭 / engine.dispose 全部余下清理）；
- jieba 预热超时：wait_for 兜底返回，不挂死停机；
- 正常/已取消路径静默通过。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.main import _shutdown_prewarm_tasks


@pytest.mark.asyncio
async def test_cache_task_error_does_not_propagate(caplog):
    async def boom():
        raise ValueError("warmup exploded")

    cache = asyncio.create_task(boom())
    jieba = asyncio.create_task(asyncio.sleep(0))
    await asyncio.wait({cache})  # 让异常先发生（未启动即 cancel 只会得到 CancelledError）

    with caplog.at_level(logging.WARNING):
        await _shutdown_prewarm_tasks(cache, jieba)  # 不应抛出

    assert any("Cache warmup task ended with error" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_jieba_timeout_does_not_hang():
    async def stuck():
        await asyncio.sleep(60)

    cache = None
    jieba = asyncio.create_task(stuck())

    # 0.05s 超时：若 wait_for 缺失或失效，本用例会挂到全局超时
    await asyncio.wait_for(
        _shutdown_prewarm_tasks(cache, jieba, jieba_timeout=0.05),
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_normal_and_cancelled_paths_pass_quietly():
    done_cache = asyncio.create_task(asyncio.sleep(0))
    await done_cache
    cancelled_jieba = asyncio.create_task(asyncio.sleep(60))
    cancelled_jieba.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_jieba

    await _shutdown_prewarm_tasks(done_cache, cancelled_jieba)  # 不抛即通过
    await _shutdown_prewarm_tasks(None, None)  # None 容忍
