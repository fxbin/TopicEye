import pytest

from app.services import fanqie_service, qimao_service, zhihu_service


class _FakeAsyncResult:
    """Minimal stand-in for a SQLAlchemy Result: enough to satisfy SELECT rows(),
    scalar() etc., while letting DELETE/UPDATE statements silently ignore the
    return value. Newer code paths under test may iterate result.all()."""

    def all(self):
        return []

    def scalar(self):
        return None

    def scalars(self):
        return self

    def __iter__(self):
        return iter([])

    def __bool__(self):  # truthy result checks
        return False


class _FakeAsyncSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement):
        return _FakeAsyncResult()

    async def commit(self):
        return None


def _fake_async_session():
    return _FakeAsyncSession()


@pytest.mark.asyncio
async def test_fanqie_full_sync_invalidates_novel_platform_stats_cache(monkeypatch):
    calls = []

    async def sync_categories():
        return [{"fanqie_id": "1", "name": "样本", "group": "male"}]

    async def sync_category_books(_categories):
        return None

    async def save_daily_snapshot(_db):
        return 0

    async def cleanup_old_snapshots(_db, days):
        assert days == 30
        return 0

    monkeypatch.setattr(fanqie_service, "sync_categories", sync_categories)
    monkeypatch.setattr(fanqie_service, "sync_category_books", sync_category_books)
    monkeypatch.setattr(fanqie_service, "_save_daily_snapshot", save_daily_snapshot)
    monkeypatch.setattr(fanqie_service, "_cleanup_old_snapshots", cleanup_old_snapshots)
    monkeypatch.setattr(fanqie_service, "async_session", _fake_async_session)
    monkeypatch.setattr(fanqie_service, "invalidate_novel_platform_stats_cache", lambda: calls.append("invalidated"))

    result = await fanqie_service.full_sync()

    assert result["categories"] == 1
    assert calls == ["invalidated"]


@pytest.mark.asyncio
async def test_qimao_sync_invalidates_novel_platform_stats_cache(monkeypatch):
    calls = []

    async def fetch_all_ranks():
        return {}

    monkeypatch.setattr(qimao_service, "fetch_all_ranks", fetch_all_ranks)
    monkeypatch.setattr(qimao_service, "async_session", _fake_async_session)
    monkeypatch.setattr(qimao_service, "invalidate_novel_platform_stats_cache", lambda: calls.append("invalidated"))

    result = await qimao_service.sync_qimao_ranks()

    assert result["books"] == 0
    assert calls == ["invalidated"]


@pytest.mark.asyncio
async def test_zhihu_sync_invalidates_novel_platform_stats_cache(monkeypatch):
    calls = []

    async def fetch_html(_url):
        return '{"categories":[{"id":"1512","name":"故事","level":1,"sort":1,"sub_category":[]}]}'

    async def fetch_api(_sort_type, limit=20, offset=0, category_id=None):
        return [{"business_id": f"{category_id}-{_sort_type}"}]

    async def fetch_and_save_albums(items, _sort_type, _category1, _category2, prev_positions=None):
        return len(items)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(zhihu_service, "_fetch_html", fetch_html)
    monkeypatch.setattr(zhihu_service, "_fetch_api", fetch_api)
    monkeypatch.setattr(zhihu_service, "_fetch_and_save_albums", fetch_and_save_albums)
    monkeypatch.setattr(zhihu_service.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(zhihu_service, "async_session", _fake_async_session)
    monkeypatch.setattr(zhihu_service, "invalidate_novel_platform_stats_cache", lambda: calls.append("invalidated"))

    result = await zhihu_service.sync_zhihu_ranks()

    assert result["categories"] == 1
    assert result["total_albums"] == 30
    assert calls == ["invalidated"]
