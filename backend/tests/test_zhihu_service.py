from datetime import datetime, timezone, UTC
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.services import zhihu_service


def _category_record():
    return {
        "zhihu_id": "1512",
        "name": "故事",
        "name_en": "story",
        "level": 1,
        "parent_id": None,
        "sort": 1,
        "artwork": "https://example.com/cat.png",
    }


def _album_record():
    return {
        "business_id": "album-1",
        "sort_type": "hottest__1512",
        "title": "标题",
        "author": "作者",
        "author_desc": "简介",
        "abstract": "摘要",
        "thumb_url": "https://example.com/cover.png",
        "category1_name": "故事",
        "category2_name": "故事全部",
        "chapter_text": "10 篇文章",
        "price": 0,
        "original_price": 0,
        "is_exclusive": False,
        "is_svip": False,
        "is_purchased": False,
        "online_time": 1,
        "online_time_text": "今天上新",
        "tag": None,
        "subscription_name": None,
        "media_type": "book",
        "subcategory": "paid_column",
        "business_line": "vip",
        "position": 1,
        "updated_at": datetime.now(UTC),
    }


def test_zhihu_category_upsert_uses_sqlite_profile(monkeypatch):
    monkeypatch.setattr(
        zhihu_service,
        "database_profile",
        SimpleNamespace(is_sqlite=True, is_postgresql=False, backend="sqlite"),
    )

    stmt = zhihu_service._upsert_zhihu_category_statement(_category_record())
    sql = str(stmt.compile(dialect=sqlite.dialect()))

    assert "INSERT INTO zhihu_categories" in sql
    assert "ON CONFLICT (zhihu_id) DO UPDATE SET" in sql
    assert "parent_id = excluded.parent_id" in sql


def test_zhihu_album_upsert_uses_postgresql_profile(monkeypatch):
    monkeypatch.setattr(
        zhihu_service,
        "database_profile",
        SimpleNamespace(is_sqlite=False, is_postgresql=True, backend="postgresql"),
    )

    stmt = zhihu_service._upsert_zhihu_album_statement(_album_record())
    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "INSERT INTO zhihu_albums" in sql
    assert "ON CONFLICT (business_id, sort_type) DO UPDATE SET" in sql
    assert "author_desc = excluded.author_desc" in sql
    assert "business_line = excluded.business_line" in sql


def test_zhihu_upsert_rejects_unknown_database_backend(monkeypatch):
    monkeypatch.setattr(
        zhihu_service,
        "database_profile",
        SimpleNamespace(is_sqlite=False, is_postgresql=False, backend="mysql"),
    )

    with pytest.raises(RuntimeError, match="Unsupported database backend"):
        zhihu_service._upsert_zhihu_category_statement(_category_record())
