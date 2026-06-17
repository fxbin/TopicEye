import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.category import Category
from app.services import classifier


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_classify_async_rejects_unknown_existing_category(monkeypatch):
    async def fake_llm_json(*args, **kwargs):
        return {
            "category": "幻觉分类",
            "tags": ["phantom"],
            "is_new_category": False,
            "confidence": 2,
        }

    monkeypatch.setattr("app.services.llm.call_llm_json", fake_llm_json)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        result = await classifier.classify_async(
            "unmapped bland headline",
            "no matching keywords here",
            db,
            category_names=["AI", "产品"],
        )

    assert result == {
        "category": "其他",
        "tags": [],
        "is_new_category": False,
        "confidence": 0.3,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_classify_async_normalizes_known_category_contract(monkeypatch):
    async def fake_llm_json(*args, **kwargs):
        return {
            "category": "AI",
            "tags": ["模型", "模型", " ", "x" * 80, "工具", "产品", "额外"],
            "is_new_category": False,
            "confidence": 2,
        }

    monkeypatch.setattr("app.services.llm.call_llm_json", fake_llm_json)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        result = await classifier.classify_async(
            "unmapped bland headline",
            "no matching keywords here",
            db,
            category_names=["AI", "产品"],
        )

    assert result["category"] == "AI"
    assert result["tags"] == ["模型", "x" * 40, "工具", "产品", "额外"]
    assert result["confidence"] == 1.0
    assert result["is_new_category"] is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_classify_async_still_creates_explicit_new_category(monkeypatch):
    async def fake_llm_json(*args, **kwargs):
        return {
            "category": "  新奇分类  ",
            "tags": '["新奇", "案例"]',
            "is_new_category": True,
            "confidence": -1,
        }

    monkeypatch.setattr("app.services.llm.call_llm_json", fake_llm_json)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        result = await classifier.classify_async(
            "unmapped bland headline",
            "no matching keywords here",
            db,
            category_names=["AI"],
        )
        stored = await db.scalar(select(Category).where(Category.name == "新奇分类"))

    assert result["category"] == "新奇分类"
    assert result["tags"] == ["新奇", "案例"]
    assert result["confidence"] == 0.0
    assert result["is_new_category"] is True
    assert stored is not None
    await engine.dispose()
