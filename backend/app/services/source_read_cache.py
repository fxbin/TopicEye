from __future__ import annotations

from app.services.source_cache import invalidate_source_list_cache


def invalidate_source_read_caches() -> None:
    """Invalidate cached read models derived from sources or source health.

    注意：不再失效 stats 缓存。同 content_read_cache 的理由——聚合统计靠 TTL 过期。
    """
    invalidate_source_list_cache()
