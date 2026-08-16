from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.content import ContentResponse
from app.services.content_summary import clean_content_summary


def test_clean_content_summary_removes_hacker_news_link_metadata_html():
    raw = (
        '<p>Article URL: <a href="https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting">'
        "https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting</a></p>"
        '<p>Comments URL: <a href="https://news.ycombinator.com/item?id=1">'
        "https://news.ycombinator.com/item?id=1</a></p>"
    )

    assert clean_content_summary(raw) == ""


def test_clean_content_summary_preserves_prose_while_removing_metadata_block():
    raw = (
        '<p>Article URL: <a href="https://example.com/article">https://example.com/article</a></p>'
        "<p><strong>作者</strong> 讨论了如何为 AI 生成内容添加清晰标识。</p>"
    )

    assert clean_content_summary(raw) == "作者 讨论了如何为 AI 生成内容添加清晰标识。"


def test_clean_content_summary_supports_escaped_html_and_removes_non_text_markup():
    raw = "&lt;p&gt;可靠的 &lt;em&gt;RSS 摘要&lt;/em&gt;。&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;"

    assert clean_content_summary(raw) == "可靠的 RSS 摘要。"


def test_content_response_normalizes_legacy_summary_without_changing_content_url():
    created_at = datetime(2026, 8, 6, tzinfo=UTC)
    response = ContentResponse(
        id=1,
        title="Show HN",
        url="https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting",
        crawled_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        status="analyzed",
        summary='<p>Article URL: <a href="https://example.com/article">https://example.com/article</a></p>',
    )

    payload = response.model_dump()

    assert payload["summary"] is None
    assert payload["url"] == "https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting"
