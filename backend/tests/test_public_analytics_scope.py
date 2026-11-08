"""Shared analytics and periodicals must not aggregate private content."""

from datetime import UTC, date, datetime, timedelta

import pytest


@pytest.fixture
def analytics(monkeypatch):
    import duckdb

    from app.services.duckdb_service import DuckDBAnalytics

    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""CREATE TABLE oltp_db.content_items (
        id INTEGER, source_id INTEGER, source_name VARCHAR, source_type VARCHAR,
        category VARCHAR, crawled_at TIMESTAMP, published_at TIMESTAMP,
        title VARCHAR, url VARCHAR, platform VARCHAR, summary VARCHAR,
        raw_content VARCHAR, owner_user_id INTEGER, topic_id INTEGER)""")
    score_columns = [
        "curation_score",
        "creator_score",
        "viral_score",
        "quality_score",
        "hot_score",
        "freshness_score",
        "risk_score",
        "info_density",
        "actionability",
        "source_weight",
    ]
    conn.execute(
        "CREATE TABLE oltp_db.ai_analyses (id INTEGER, content_id INTEGER, created_at TIMESTAMP, summary VARCHAR, recommendation VARCHAR, recommended_reason VARCHAR, tags VARCHAR, summary_source VARCHAR,"
        + ",".join(c + " DOUBLE" for c in score_columns)
        + ")"
    )
    conn.execute("CREATE TABLE oltp_db.sources (id INTEGER, name VARCHAR, source_type VARCHAR, weight INTEGER)")
    conn.execute(
        "CREATE TABLE oltp_db.user_feedback (id INTEGER, content_id INTEGER, user_id INTEGER, score_delta DOUBLE, created_at TIMESTAMP)"
    )
    conn.execute("CREATE TABLE oltp_db.ignored_items (id INTEGER, content_id INTEGER, user_id INTEGER)")
    conn.execute("CREATE TABLE oltp_db.content_event_groups (id INTEGER, canonical_content_id INTEGER, status VARCHAR)")
    conn.execute(
        "CREATE TABLE oltp_db.content_event_members (id INTEGER, event_group_id INTEGER, content_id INTEGER, review_status VARCHAR)"
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    for cid, owner in [(1, None), (2, 1), (3, 2)]:
        name = "公共源" if owner is None else f"私有源{owner}"
        conn.execute("INSERT INTO oltp_db.sources VALUES (?, ?, 'RSS', 3)", [cid, name])
        conn.execute(
            "INSERT INTO oltp_db.content_items VALUES (?, ?, ?, 'RSS', ?, ?, ?, ?, ?, 'rss', '可读摘要', '用于验证归属限制的真实正文', ?, NULL)",
            [
                cid,
                cid,
                name,
                "公共分类" if owner is None else "私有分类",
                now,
                now,
                f"文章{cid}",
                f"https://example.test/{cid}",
                owner,
            ],
        )
        scores = [90 if c != "risk_score" else 0 for c in score_columns]
        conn.execute(
            "INSERT INTO oltp_db.ai_analyses VALUES (?, ?, ?, '分析摘要', '推荐理由', '推荐理由', '[\"评估\"]', 'llm_pro',"
            + ",".join("?" for _ in scores)
            + ")",
            [cid, cid, now, *scores],
        )
    instance = DuckDBAnalytics()
    monkeypatch.setattr(instance, "_get_conn", lambda: conn)
    monkeypatch.setattr(instance, "query_stats_novel_platforms", lambda: {"platforms": []})
    yield instance
    conn.close()


def test_all_shared_analytics_queries_exclude_private_inputs(analytics):
    overview = analytics.query_stats_overview()
    assert overview["total"] == 1 and overview["analyzed"] == 1
    assert overview["curated"] == 1
    assert [r["source_name"] for r in analytics.query_stats_source_distribution()["sources"]] == ["公共源"]
    assert [r["category"] for r in analytics.query_stats_category_distribution()["categories"]] == ["公共分类"]
    assert sum(r["content_count"] for r in analytics.query_stats_daily_trend()["trend"]) == 1
    assert analytics.query_daily_stats()["total_items"] == 1
    dashboard = analytics.query_dashboard_stats()
    assert dashboard["kpi"]["total_crawled"] == 1
    assert dashboard["kpi"]["active_sources"] == 1
    assert [r["source_name"] for r in dashboard["source_breakdown"]] == ["公共源"]
    assert {r["id"] for r in analytics._query_stats_scored_items()} == {1}


def test_public_report_and_digest_inputs_exclude_private_content(analytics):
    assert [r["id"] for r in analytics.query_content_for_report()] == [1]
    rows = analytics.query_content_for_weekly(
        (date.today() - timedelta(days=1)).isoformat(), (date.today() + timedelta(days=1)).isoformat()
    )
    assert [r["id"] for r in rows] == [1]


@pytest.mark.asyncio
async def test_weekly_pick_tracking_uses_only_public_daily_reports(db):
    from app.models.daily_report import DailyReport
    from app.models.user import User
    from app.repositories.daily_report_repo import DailyReportRepository

    db.add(User(id=1, email="private-report@test"))
    await db.flush()
    db.add_all(
        [
            DailyReport(report_date="2026-11-07", weekday=5, status="DONE", owner_user_id=None, edition="final"),
            DailyReport(report_date="2026-11-07", weekday=5, status="DONE", owner_user_id=1, edition="final"),
        ]
    )
    await db.commit()
    reports = await DailyReportRepository(db).list_done_by_date_range("2026-11-01", "2026-11-08")
    assert len(reports) == 1
    assert reports[0].owner_user_id is None
