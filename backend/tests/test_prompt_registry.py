import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.llm_model import LlmCallLog
from app.models.prompt_registry import PromptRegistry
from app.services.prompt_registry_service import (
    _PROMPT_CATALOG,
    _import_prompt_content,
    list_prompt_catalog,
    prompt_catalog_detail,
    sync_prompt_registry,
)


@pytest.mark.asyncio
async def test_catalog_repairs_metadata_and_counts_each_scene_once():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            content = _import_prompt_content("app.services.llm.prompts.analysis", "SYSTEM_PROMPT")
            old = PromptRegistry(
                name="analysis_system",
                scene="analysis",
                description="old",
                full_content=content,
                version_hash=hashlib.md5(content.encode()).hexdigest(),
            )
            retired = PromptRegistry(name="retired_template", scene="legacy")
            db.add_all([old, retired])
            db.add_all(
                [
                    LlmCallLog(
                        request_id=f"test_{i}",
                        scene="content_analysis",
                        status=status,
                        total_cost=0.1,
                        input_tokens=10,
                        output_tokens=2,
                    )
                    for i, status in enumerate(["DONE", "FAILED", "DONE"])
                ]
            )
            db.add(LlmCallLog(request_id="custom", scene="evaluation:custom", status="FAILED"))
            await db.flush()
            await sync_prompt_registry(db)
            assert old.scene == "content_analysis" and old.description != "old"
            assert await sync_prompt_registry(db) == 0
            catalog = await list_prompt_catalog(db, None, datetime.now(UTC) - timedelta(days=7))
            scene = next(s for s in catalog["scenes"] if s["scene"] == "content_analysis")
            assert scene["template_count"] == 6
            assert scene["stats_7d"]["call_count"] == 3
            assert scene["stats_7d"]["success_count"] == 2
            assert scene["stats_7d"]["failed_count"] == 1
            assert scene["stats_7d"]["total_cost"] == 0.3
            assert all("stats_7d" not in item for item in catalog["items"])
            assert not any(item["name"] == "retired_template" for item in catalog["items"])
            assert (
                await db.execute(select(PromptRegistry).where(PromptRegistry.name == "retired_template"))
            ).scalar_one()
            assert any(s["scene"] == "evaluation:custom" and s["template_count"] == 0 for s in catalog["scenes"])
            assert catalog["attribution"]["retry_count"] is None
            assert catalog["attribution"]["template_version_attribution"] is False
            detail = await prompt_catalog_detail(db, old.id, datetime.now(UTC) - timedelta(days=30))
            assert detail["stats_30d"]["call_count"] == 3
            assert detail["daily_trend"][0]["failed_count"] == 1
            filtered = await list_prompt_catalog(db, "classification", datetime.now(UTC) - timedelta(days=7))
            assert all(item["scene"] == "classification" for item in filtered["items"])
            assert filtered["scenes"][0]["stats_7d"]["call_count"] == 0
    finally:
        await engine.dispose()


def test_registered_templates_cover_actual_scenes_and_nested_creation_instructions():
    scenes = {entry["scene"] for entry in _PROMPT_CATALOG}
    assert {
        "content_analysis",
        "content_enrichment",
        "creation_plan",
        "relation_discovery",
        "topic_clustering",
    } <= scenes
    for entry in _PROMPT_CATALOG:
        assert _import_prompt_content(entry["module"], entry["attr"]), entry["name"]
