from datetime import datetime

from app.schemas.content import ContentResponse
from app.schemas.daily_report import DailyReportResponse
from app.services.zhihu_url import normalize_zhihu_url


def test_normalize_zhihu_question_answer_api_url():
    assert (
        normalize_zhihu_url("https://api.zhihu.com/questions/123/answers/456?include=data")
        == "https://www.zhihu.com/question/123/answer/456"
    )


def test_normalize_zhihu_question_and_answer_urls():
    assert normalize_zhihu_url("https://api.zhihu.com/questions/123") == "https://www.zhihu.com/question/123"
    assert normalize_zhihu_url("https://api.zhihu.com/answers/456") == "https://www.zhihu.com/answer/456"


def test_normalize_zhihu_article_url():
    assert normalize_zhihu_url("https://api.zhihu.com/articles/789") == "https://zhuanlan.zhihu.com/p/789"


def test_normalize_zhihu_url_leaves_other_hosts_unchanged():
    url = "https://example.com/questions/123"
    assert normalize_zhihu_url(url) == url


def test_content_response_serializes_normalized_zhihu_url():
    response = ContentResponse(
        id=1,
        title="title",
        url="https://api.zhihu.com/questions/123/answers/456",
        crawled_at=datetime(2026, 1, 1),
        status="pending",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )

    assert response.model_dump()["url"] == "https://www.zhihu.com/question/123/answer/456"


def test_daily_report_response_parses_and_normalizes_top_pick_urls():
    response = DailyReportResponse(
        id=1,
        report_date="2026-01-01",
        weekday="周四",
        edition="final",
        source_item_ids="[1,2]",
        top_picks='[{"title":"t","source_url":"https://api.zhihu.com/questions/123"}]',
    )

    assert response.model_dump()["top_picks"] == [{"title": "t", "source_url": "https://www.zhihu.com/question/123"}]
    assert response.model_dump()["edition"] == "final"
    assert response.model_dump()["source_item_ids"] == [1, 2]
