"""Interest-vector rebuild task lifecycle tests.

Tests that ``trigger_vector_rebuild`` creates tracked, deduplicated
tasks and that ``drain_rebuild_tasks`` cancels and awaits them.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.interest_vector_service import (
    _rebuild_tasks,
    _rebuild_user_dedup,
    drain_rebuild_tasks,
    trigger_vector_rebuild,
)


@pytest.mark.asyncio
async def test_trigger_creates_tracked_task():
    """trigger_vector_rebuild registers the task in _rebuild_tasks."""
    _rebuild_tasks.clear()
    _rebuild_user_dedup.clear()

    trigger_vector_rebuild(999)

    assert len(_rebuild_tasks) == 1
    assert 999 in _rebuild_user_dedup

    # Let the task run (it will fail to connect to DB, which is fine)
    await asyncio.sleep(0.1)

    # Task should self-remove from registry on completion
    assert len(_rebuild_tasks) == 0
    assert 999 not in _rebuild_user_dedup


@pytest.mark.asyncio
async def test_dedup_cancels_existing_task():
    """Repeated trigger for same user cancels the old task."""
    _rebuild_tasks.clear()
    _rebuild_user_dedup.clear()

    trigger_vector_rebuild(888)
    old_task = _rebuild_user_dedup.get(888)
    assert old_task is not None

    trigger_vector_rebuild(888)
    new_task = _rebuild_user_dedup.get(888)
    assert new_task is not None
    assert new_task is not old_task

    # Old task should be cancelled
    await asyncio.sleep(0.05)
    assert old_task.cancelled() or old_task.done()

    # Clean up
    await drain_rebuild_tasks(timeout=1.0)


@pytest.mark.asyncio
async def test_drain_cancels_and_clears():
    """drain_rebuild_tasks cancels all in-flight tasks and clears registries."""
    _rebuild_tasks.clear()
    _rebuild_user_dedup.clear()

    # Create tasks for multiple users
    for uid in (100, 200, 300):
        trigger_vector_rebuild(uid)

    assert len(_rebuild_tasks) == 3

    await drain_rebuild_tasks(timeout=5.0)

    assert len(_rebuild_tasks) == 0
    assert len(_rebuild_user_dedup) == 0


@pytest.mark.asyncio
async def test_drain_with_no_tasks_is_noop():
    """drain_rebuild_tasks is a no-op when no tasks are registered."""
    _rebuild_tasks.clear()
    _rebuild_user_dedup.clear()

    await drain_rebuild_tasks(timeout=1.0)

    assert len(_rebuild_tasks) == 0
