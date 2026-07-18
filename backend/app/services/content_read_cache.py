from __future__ import annotations

from app.services.content_list_cache import invalidate_content_list_cache
from app.services.scoring_flow import invalidate_scoring_flow_cache
from app.services.today_picks_cache import invalidate_today_picks_cache


def invalidate_content_read_caches() -> None:
    """Invalidate cached read models derived from content, analyses, or feedback.

    注意：不再失效 stats 缓存。stats 是聚合统计，单条内容增删不该清空整个缓存。
    stats 缓存靠 300s TTL 自然过期，批量同步任务后可显式调 invalidate_stats_cache()。
    """
    invalidate_content_list_cache()
    invalidate_scoring_flow_cache()
    invalidate_today_picks_cache()
