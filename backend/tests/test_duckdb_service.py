from datetime import UTC, datetime, timedelta

import pytest

duckdb = pytest.importorskip("duckdb")

from app.core.db_backend import duckdb_attach_sql  # noqa: E402
from app.services import duckdb_service  # noqa: E402


def create_ignored_items_table(conn):
    conn.execute("""
        CREATE TABLE oltp_db.ignored_items (
            id INTEGER,
            content_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.content_event_groups (
            id INTEGER,
            canonical_content_id INTEGER,
            status VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.content_event_members (
            id INTEGER,
            event_group_id INTEGER,
            content_id INTEGER,
            review_status VARCHAR
        )
    """)


def test_duckdb_status_redacts_database_password_on_connection_failure(monkeypatch):
    url = "postgresql+asyncpg://topiceye:s3 cr'et@localhost:5432/topiceye"
    monkeypatch.setattr(duckdb_service.settings, "DATABASE_URL", url)

    analytics = duckdb_service.DuckDBAnalytics()
    attach_sql = duckdb_attach_sql(analytics._profile)

    def fail_get_conn():
        raise RuntimeError(f"failed for {url}; conninfo password='s3 cr\\'et'; attach={attach_sql}")

    monkeypatch.setattr(analytics, "_get_conn", fail_get_conn)

    assert analytics.available is False
    status = analytics.status()

    assert status["available"] is False
    assert "s3 cr'et" not in status["error"]
    assert "s3 cr\\'et" not in status["error"]
    assert "password=***" in status["error"]
    assert "postgresql+asyncpg://topiceye:***@localhost:5432/topiceye" in status["error"]


def test_stats_queries_use_latest_analysis_only(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            source_name VARCHAR,
            category VARCHAR,
            crawled_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            name VARCHAR,
            source_type VARCHAR,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            freshness_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
risk_score DOUBLE,
created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, '测试信源', 'RSS', 3)")
    conn.execute(
        "INSERT INTO oltp_db.content_items VALUES (1, 1, '测试信源', 'AI', ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (1, 1, 10.0, 10, 10, 50, 10, 10, 10, 10, 10, 0, ?)",
        [now - timedelta(hours=2)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (2, 1, 90.0, 90, 90, 80, 90, 90, 90, 90, 90, 0, ?)",
        [now - timedelta(hours=1)],
    )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    overview = analytics.query_stats_overview(days=7)
    assert overview["total"] == 1
    assert overview["analyzed"] == 1
    assert overview["curated"] == 1
    assert overview["curation_threshold"] > 0

    source_distribution = analytics.query_stats_source_distribution(days=7)
    assert source_distribution["sources"] == [
        {
            "source_name": "测试信源",
            "source_type": "rss",
            "content_count": 1,
            "curated_count": 1,
            "curation_rate": 100.0,
        }
    ]

    category_distribution = analytics.query_stats_category_distribution(days=7)
    assert category_distribution["categories"] == [{"category": "AI", "content_count": 1, "avg_score": 90.0}]

    daily_trend = analytics.query_stats_daily_trend(days=7)
    assert len(daily_trend["trend"]) == 1
    assert daily_trend["trend"][0]["content_count"] == 1
    assert daily_trend["trend"][0]["curated_count"] == 1
    assert daily_trend["trend"][0]["analyzed_count"] == 1

    conn.close()


def test_dashboard_stats_uses_unified_scorer_for_curated_counts(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            source_name VARCHAR,
            category VARCHAR,
            crawled_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            name VARCHAR,
            source_type VARCHAR,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            freshness_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
risk_score DOUBLE,
created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)
    for table_name, timestamp_column in (
        ("fanqie_books", "crawled_at"),
        ("qimao_books", "crawled_at"),
        ("zhihu_albums", "updated_at"),
    ):
        conn.execute(f"""
            CREATE TABLE oltp_db.{table_name} (
                id INTEGER,
                {timestamp_column} TIMESTAMP
            )
        """)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, '测试信源', 'RSS', 3)")
    conn.execute("INSERT INTO oltp_db.content_items VALUES (1, 1, '测试信源', 'AI', ?)", [now])
    conn.execute("INSERT INTO oltp_db.content_items VALUES (2, 1, '测试信源', 'AI', ?)", [now])
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (1, 1, 95.0, 10, 10, 50, 10, 10, 50, 10, 10, 0, ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (2, 2, 70.0, 90, 90, 70, 90, 70, 80, 90, 70, 0, ?)",
        [now],
    )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    dashboard = analytics.query_dashboard_stats(days=7)

    assert dashboard["overview"]["curation_threshold"] > 0
    assert dashboard["overview"]["curated"] == 1
    assert dashboard["kpi"]["total_curated"] == 1
    assert dashboard["sources"][0]["curated_count"] == 1
    assert dashboard["source_breakdown"][0]["curated_count"] == 1
    assert dashboard["trend"][0]["curated_count"] == 1
    assert dashboard["daily_trend"][0]["curated_count"] == 1

    conn.close()


def test_stats_queries_exclude_ignored_content(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            source_name VARCHAR,
            category VARCHAR,
            crawled_at TIMESTAMP,
            topic_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            name VARCHAR,
            source_type VARCHAR,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            freshness_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
            risk_score DOUBLE,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)
    for table_name, timestamp_column in (
        ("fanqie_books", "crawled_at"),
        ("qimao_books", "crawled_at"),
        ("zhihu_albums", "updated_at"),
    ):
        conn.execute(f"""
            CREATE TABLE oltp_db.{table_name} (
                id INTEGER,
                {timestamp_column} TIMESTAMP
            )
        """)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, '测试信源', 'RSS', 3)")
    conn.execute("INSERT INTO oltp_db.content_items VALUES (1, 1, '测试信源', 'AI', ?, 10)", [now])
    conn.execute("INSERT INTO oltp_db.content_items VALUES (2, 1, '测试信源', '商业', ?, 20)", [now])
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (1, 1, 90, 90, 90, 80, 90, 90, 90, 90, 90, 0, ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (2, 2, 90, 90, 90, 80, 90, 90, 90, 90, 90, 0, ?)",
        [now],
    )
    conn.execute("INSERT INTO oltp_db.ignored_items VALUES (1, 1)")

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    overview = analytics.query_stats_overview(days=7)
    assert overview["total"] == 1
    assert overview["analyzed"] == 1
    assert overview["curated"] == 1
    assert overview["today_new"] == 1

    source_distribution = analytics.query_stats_source_distribution(days=7)
    assert source_distribution["sources"][0]["content_count"] == 1

    category_distribution = analytics.query_stats_category_distribution(days=7)
    assert category_distribution["categories"] == [{"category": "商业", "content_count": 1, "avg_score": 90.0}]

    daily_trend = analytics.query_stats_daily_trend(days=7)
    assert daily_trend["trend"][0]["content_count"] == 1
    assert daily_trend["trend"][0]["analyzed_count"] == 1

    daily_stats = analytics.query_daily_stats()
    assert daily_stats["total_items"] == 1
    assert daily_stats["topic_count"] == 1

    dashboard = analytics.query_dashboard_stats(days=7)
    assert dashboard["kpi"]["total_crawled"] == 1
    assert dashboard["kpi"]["total_curated"] == 1
    assert dashboard["source_breakdown"][0]["content_count"] == 1
    assert dashboard["daily_trend"][0]["content_count"] == 1

    conn.close()


def test_today_picks_query_uses_latest_analysis_only(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            title VARCHAR,
            url VARCHAR,
            source_id INTEGER,
            source_name VARCHAR,
            source_type VARCHAR,
            platform VARCHAR,
            author VARCHAR,
            published_at TIMESTAMP,
            crawled_at TIMESTAMP,
            content_hash VARCHAR,
            summary VARCHAR,
            raw_content VARCHAR,
            cover_url VARCHAR,
            category VARCHAR,
            content_type VARCHAR,
            tags VARCHAR,
            language VARCHAR,
            status VARCHAR,
            is_favorited BOOLEAN,
            topic_id INTEGER,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            quality_score DOUBLE,
            hot_score DOUBLE,
            freshness_score DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            recommended_reason VARCHAR,
            recommendation VARCHAR,
            summary VARCHAR,
            tags VARCHAR,
            key_points VARCHAR,
            audience_emotion VARCHAR,
            creator_angles VARCHAR,
            title_suggestions VARCHAR,
            outline_suggestions VARCHAR,
            xiaohongshu_plan VARCHAR,
            short_video_plan VARCHAR,
            risk_notes VARCHAR,
            platform_fit VARCHAR,
            summary_source VARCHAR,
            enrichment_status VARCHAR,
            enrichment VARCHAR,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, 5)")
    conn.execute(
        """
        INSERT INTO oltp_db.content_items VALUES (
            1, '最新分析精选', 'https://example.com/pick', 1, '测试信源', 'RSS',
            'rss', NULL, NULL, ?, NULL, '摘要', NULL, NULL, 'AI', NULL, '["AI"]',
            'zh', 'analyzed', false, NULL, ?, ?
        )
        """,
        [now, now, now],
    )
    conn.execute(
        """
        INSERT INTO oltp_db.ai_analyses VALUES (
            1, 1, 50, 50, 50, 50, 50, 10, 20, 50, 50, 40,
            '旧理由', '旧推荐', '旧摘要', '["旧"]', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'pending', NULL, ?
        )
        """,
        [now - timedelta(hours=2)],
    )
    conn.execute(
        """
        INSERT INTO oltp_db.ai_analyses VALUES (
            2, 1, 88, 80, 90, 86, 78, 12, 90, 85, 82, 0,
            '新理由', '新推荐', '新摘要', '["新"]', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'pending', NULL, ?
        )
        """,
        [now - timedelta(hours=1)],
    )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    rows = analytics.query_today_picks(hours=48, curation_threshold=0)

    assert len(rows) == 1
    assert rows[0]["analysis_id"] == 2
    assert rows[0]["curation_score"] == 90.0
    assert rows[0]["analysis_source_weight"] == 0.0
    assert rows[0]["recommended_reason"] == "新理由"
    assert rows[0]["adjusted_curation_score"] == 106.0

    conn.close()


def test_today_picks_query_applies_aggregated_feedback(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            title VARCHAR,
            url VARCHAR,
            source_id INTEGER,
            source_name VARCHAR,
            source_type VARCHAR,
            platform VARCHAR,
            author VARCHAR,
            published_at TIMESTAMP,
            crawled_at TIMESTAMP,
            content_hash VARCHAR,
            summary VARCHAR,
            raw_content VARCHAR,
            cover_url VARCHAR,
            category VARCHAR,
            content_type VARCHAR,
            tags VARCHAR,
            language VARCHAR,
            status VARCHAR,
            is_favorited BOOLEAN,
            topic_id INTEGER,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            quality_score DOUBLE,
            hot_score DOUBLE,
            freshness_score DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            recommended_reason VARCHAR,
            recommendation VARCHAR,
            summary VARCHAR,
            tags VARCHAR,
            key_points VARCHAR,
            audience_emotion VARCHAR,
            creator_angles VARCHAR,
            title_suggestions VARCHAR,
            outline_suggestions VARCHAR,
            xiaohongshu_plan VARCHAR,
            short_video_plan VARCHAR,
            risk_notes VARCHAR,
            platform_fit VARCHAR,
            summary_source VARCHAR,
            enrichment_status VARCHAR,
            enrichment VARCHAR,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, 3)")
    for content_id, title in ((1, "反馈提升样本"), (2, "无反馈样本")):
        conn.execute(
            """
            INSERT INTO oltp_db.content_items VALUES (
                ?, ?, ?, 1, '测试信源', 'RSS',
                'rss', NULL, NULL, ?, NULL, '摘要', NULL, NULL, 'AI', NULL, '["AI"]',
                'zh', 'analyzed', false, NULL, ?, ?
            )
            """,
            [content_id, title, f"https://example.com/{content_id}", now, now, now],
        )
        conn.execute(
            """
            INSERT INTO oltp_db.ai_analyses VALUES (
                ?, ?, 80, 80, 80, 80, 80, 10, 80, 80, 80,
                '理由', '推荐', '摘要', '["AI"]', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'pending', NULL, ?
            )
            """,
            [content_id, content_id, now],
        )

    conn.execute("INSERT INTO oltp_db.user_feedback VALUES (1, 1, 1, 20.0, ?)", [now])
    conn.execute("INSERT INTO oltp_db.user_feedback VALUES (2, 1, 2, 999.0, ?)", [now])

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    rows = analytics.query_today_picks(hours=48, curation_threshold=0)

    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["feedback_score"] == 1019.0
    assert rows[0]["adjusted_curation_score"] == 83.0
    assert rows[1]["feedback_score"] == 0.0
    assert rows[1]["adjusted_curation_score"] == 80.0

    conn.close()


def test_today_picks_query_uses_unified_risk_threshold_for_candidates(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            title VARCHAR,
            url VARCHAR,
            source_id INTEGER,
            source_name VARCHAR,
            source_type VARCHAR,
            platform VARCHAR,
            author VARCHAR,
            published_at TIMESTAMP,
            crawled_at TIMESTAMP,
            content_hash VARCHAR,
            summary VARCHAR,
            raw_content VARCHAR,
            cover_url VARCHAR,
            category VARCHAR,
            content_type VARCHAR,
            tags VARCHAR,
            language VARCHAR,
            status VARCHAR,
            is_favorited BOOLEAN,
            topic_id INTEGER,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            quality_score DOUBLE,
            hot_score DOUBLE,
            freshness_score DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            recommended_reason VARCHAR,
            recommendation VARCHAR,
            summary VARCHAR,
            tags VARCHAR,
            key_points VARCHAR,
            audience_emotion VARCHAR,
            creator_angles VARCHAR,
            title_suggestions VARCHAR,
            outline_suggestions VARCHAR,
            xiaohongshu_plan VARCHAR,
            short_video_plan VARCHAR,
            risk_notes VARCHAR,
            platform_fit VARCHAR,
            summary_source VARCHAR,
            enrichment_status VARCHAR,
            enrichment VARCHAR,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, 3)")
    for content_id, risk_score in ((1, 80), (2, 83)):
        conn.execute(
            """
            INSERT INTO oltp_db.content_items VALUES (
                ?, ?, ?, 1, '测试信源', 'RSS',
                'rss', NULL, NULL, ?, NULL, '摘要', NULL, NULL, 'AI', NULL, '["AI"]',
                'zh', 'analyzed', false, NULL, ?, ?
            )
            """,
            [content_id, f"风险候选 {content_id}", f"https://example.com/risk-{content_id}", now, now, now],
        )
        conn.execute(
            """
            INSERT INTO oltp_db.ai_analyses VALUES (
                ?, ?, 90, 90, 90, 90, 90, ?, 90, 90, 90,
                '理由', '推荐', '摘要', '["AI"]', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'pending', NULL, ?
            )
            """,
            [content_id, content_id, risk_score, now],
        )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    rows = analytics.query_today_picks(hours=48, curation_threshold=0)

    assert [row["id"] for row in rows] == [1]
    assert rows[0]["risk_score"] == 80.0

    conn.close()


def test_today_picks_query_excludes_ignored_content(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            title VARCHAR,
            url VARCHAR,
            source_id INTEGER,
            source_name VARCHAR,
            source_type VARCHAR,
            platform VARCHAR,
            author VARCHAR,
            published_at TIMESTAMP,
            crawled_at TIMESTAMP,
            content_hash VARCHAR,
            summary VARCHAR,
            raw_content VARCHAR,
            cover_url VARCHAR,
            category VARCHAR,
            content_type VARCHAR,
            tags VARCHAR,
            language VARCHAR,
            status VARCHAR,
            is_favorited BOOLEAN,
            topic_id INTEGER,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            quality_score DOUBLE,
            hot_score DOUBLE,
            freshness_score DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            recommended_reason VARCHAR,
            recommendation VARCHAR,
            summary VARCHAR,
            tags VARCHAR,
            key_points VARCHAR,
            audience_emotion VARCHAR,
            creator_angles VARCHAR,
            title_suggestions VARCHAR,
            outline_suggestions VARCHAR,
            xiaohongshu_plan VARCHAR,
            short_video_plan VARCHAR,
            risk_notes VARCHAR,
            platform_fit VARCHAR,
            summary_source VARCHAR,
            enrichment_status VARCHAR,
            enrichment VARCHAR,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, 3)")
    for content_id, title in ((1, "已忽略精选"), (2, "保留精选")):
        conn.execute(
            """
            INSERT INTO oltp_db.content_items VALUES (
                ?, ?, ?, 1, '测试信源', 'RSS',
                'rss', NULL, NULL, ?, NULL, '摘要', NULL, NULL, 'AI', NULL, '["AI"]',
                'zh', 'analyzed', false, NULL, ?, ?
            )
            """,
            [content_id, title, f"https://example.com/{content_id}", now, now, now],
        )
        conn.execute(
            """
            INSERT INTO oltp_db.ai_analyses VALUES (
                ?, ?, 90, 90, 90, 90, 90, 10, 90, 90, 90,
                '理由', '推荐', '摘要', '["AI"]', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'pending', NULL, ?
            )
            """,
            [content_id, content_id, now],
        )
    conn.execute("INSERT INTO oltp_db.ignored_items VALUES (1, 1)")

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    rows = analytics.query_today_picks(hours=48, curation_threshold=0)

    assert [row["id"] for row in rows] == [2]

    conn.close()


def test_digest_content_query_uses_latest_analysis_and_feedback_order(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            title VARCHAR,
            url VARCHAR,
            category VARCHAR,
            source_name VARCHAR,
            platform VARCHAR,
            crawled_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            summary VARCHAR,
            creator_score DOUBLE,
            viral_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
            freshness_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            tags VARCHAR,
            recommendation VARCHAR,
            recommended_reason VARCHAR,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    # 用 naive UTC,避免 DuckDB CAST(crawled_at AS DATE) 跟 Python .date()
    # 在跨时区机器上对 aware datetime 解释不一致(UTC+8 差 8 小时,导致
    # 测试范围 [yesterday, today] 实际不含 today 的 UTC 时刻 → 0 行)。
    now = datetime.now(UTC).replace(tzinfo=None).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (10, 4)")
    conn.execute(
        "INSERT INTO oltp_db.content_items VALUES (1, 10, '反馈后的最新分析', 'https://example.com/1', 'AI', '测试信源', 'rss', ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.content_items VALUES (2, NULL, '无反馈样本', 'https://example.com/2', 'AI', '测试信源', 'rss', ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (1, 1, '旧摘要', 95, 95, 95, 95, 95, 10, 99, 95, 95, 95, '[\"旧\"]', '旧推荐', '旧理由', ?)",
        [now - timedelta(hours=2)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (2, 1, '新摘要', 70, 70, 70, 65, 80, 10, 70, 82, 81, 72, '[\"新\"]', '新推荐', '新理由', ?)",
        [now - timedelta(hours=1)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (3, 2, '无反馈摘要', 72, 72, 72, 60, 75, 10, 72, 74, 73, 50, '[\"AI\"]', '推荐', '理由', ?)",
        [now],
    )
    conn.execute("INSERT INTO oltp_db.user_feedback VALUES (1, 1, 1, 20.0, ?)", [now])

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    rows = analytics.query_content_for_weekly(
        (now - timedelta(days=1)).date().isoformat(),
        now.date().isoformat(),
    )

    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["summary"] == "新摘要"
    assert rows[0]["curation_score"] == 70.0
    assert rows[0]["info_density"] == 82.0
    assert rows[0]["actionability"] == 81.0
    assert rows[0]["source_weight"] == 72.0
    assert rows[0]["hot_score"] == 65.0
    assert rows[0]["freshness_score"] == 80.0
    assert rows[0]["source_weight_db"] == 4
    assert rows[0]["feedback_score"] == 20.0
    assert rows[0]["adjusted_score"] == 73.0
    assert rows[0]["recommendation"] == "新推荐"
    assert rows[1]["curation_score"] == 72.0
    assert rows[1]["adjusted_score"] == 72.0

    conn.close()


def test_daily_report_content_query_uses_latest_analysis_only(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            title VARCHAR,
            url VARCHAR,
            category VARCHAR,
            source_name VARCHAR,
            crawled_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            summary VARCHAR,
            creator_score DOUBLE,
            viral_score DOUBLE,
            quality_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            recommended_reason VARCHAR,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute(
        "INSERT INTO oltp_db.content_items VALUES (1, '多次分析样本', 'https://example.com/1', 'AI', '测试信源', ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.content_items VALUES (2, '普通样本', 'https://example.com/2', 'AI', '测试信源', ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (1, 1, '旧日报摘要', 99, 99, 99, 10, 99, '旧理由', ?)",
        [now - timedelta(hours=2)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (2, 1, '新日报摘要', 50, 50, 50, 10, 50, '新理由', ?)",
        [now - timedelta(hours=1)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (3, 2, '普通摘要', 80, 80, 80, 10, 80, '普通理由', ?)",
        [now],
    )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    rows = analytics.query_content_for_report(hours=48)

    assert [row["id"] for row in rows] == [2, 1]
    assert rows[1]["summary"] == "新日报摘要"
    assert rows[1]["creator_score"] == 50.0
    assert rows[1]["recommended_reason"] == "新理由"

    conn.close()


def test_digest_content_queries_exclude_ignored_content(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            title VARCHAR,
            url VARCHAR,
            category VARCHAR,
            source_name VARCHAR,
            platform VARCHAR,
            crawled_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            summary VARCHAR,
            creator_score DOUBLE,
            viral_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
            freshness_score DOUBLE,
            risk_score DOUBLE,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            tags VARCHAR,
            recommendation VARCHAR,
            recommended_reason VARCHAR,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    for content_id, title in ((1, "已忽略素材"), (2, "保留素材")):
        conn.execute(
            "INSERT INTO oltp_db.content_items VALUES (?, NULL, ?, ?, 'AI', '测试信源', 'rss', ?)",
            [content_id, title, f"https://example.com/{content_id}", now],
        )
        conn.execute(
            """
            INSERT INTO oltp_db.ai_analyses VALUES (
                ?, ?, '摘要', 90, 90, 90, 90, 90, 10, 90, 90, 90, 90, '["AI"]', '推荐', '理由', ?
            )
            """,
            [content_id, content_id, now],
        )
    conn.execute("INSERT INTO oltp_db.ignored_items VALUES (1, 1)")

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    report_rows = analytics.query_content_for_report(hours=48)
    weekly_rows = analytics.query_content_for_weekly(
        (now - timedelta(days=1)).date().isoformat(),
        now.date().isoformat(),
    )

    assert [row["id"] for row in report_rows] == [2]
    assert [row["id"] for row in weekly_rows] == [2]

    conn.close()


def test_daily_stats_uses_latest_analysis_and_unified_curated_count(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            source_name VARCHAR,
            category VARCHAR,
            crawled_at TIMESTAMP,
            topic_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            name VARCHAR,
            source_type VARCHAR,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            freshness_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
risk_score DOUBLE,
created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, '测试信源', 'RSS', 3)")
    conn.execute("INSERT INTO oltp_db.content_items VALUES (1, 1, '测试信源', 'AI', ?, 10)", [now])
    conn.execute("INSERT INTO oltp_db.content_items VALUES (2, 1, '测试信源', 'AI', ?, 20)", [now])
    conn.execute("INSERT INTO oltp_db.content_items VALUES (3, 1, '测试信源', 'AI', ?, 20)", [now])
    conn.execute("INSERT INTO oltp_db.content_event_groups VALUES (10, 1, 'active')")
    conn.execute("INSERT INTO oltp_db.content_event_members VALUES (1, 10, 3, 'auto')")
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (1, 1, 20, 90, 90, 80, 90, 90, 90, 90, 90, 0, ?)",
        [now - timedelta(hours=2)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (2, 1, 95, 10, 10, 50, 10, 10, 50, 10, 10, 0, ?)",
        [now - timedelta(hours=1)],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (3, 2, 70, 90, 90, 70, 90, 70, 80, 90, 70, 0, ?)",
        [now],
    )
    conn.execute(
        "INSERT INTO oltp_db.ai_analyses VALUES (4, 3, 88, 90, 90, 70, 90, 70, 80, 90, 70, 0, ?)",
        [now],
    )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    stats = analytics.query_daily_stats()

    assert stats["total_items"] == 3
    assert stats["curated_count"] == 1
    assert stats["avg_curation"] == 84.3
    assert stats["max_curation"] == 95.0
    assert stats["topic_count"] == 2
    assert stats["event_member_count"] == 1

    conn.close()


def test_daily_stats_uses_unified_risk_threshold(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA oltp_db")
    conn.execute("""
        CREATE TABLE oltp_db.content_items (
            id INTEGER,
            source_id INTEGER,
            source_name VARCHAR,
            category VARCHAR,
            crawled_at TIMESTAMP,
            topic_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.sources (
            id INTEGER,
            name VARCHAR,
            source_type VARCHAR,
            weight INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.ai_analyses (
            id INTEGER,
            content_id INTEGER,
            curation_score DOUBLE,
            info_density DOUBLE,
            actionability DOUBLE,
            source_weight DOUBLE,
            creator_score DOUBLE,
            viral_score DOUBLE,
            freshness_score DOUBLE,
            quality_score DOUBLE,
            hot_score DOUBLE,
risk_score DOUBLE,
created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE oltp_db.user_feedback (
            id INTEGER,
            content_id INTEGER,
            user_id INTEGER,
            score_delta DOUBLE,
            created_at TIMESTAMP
        )
    """)
    create_ignored_items_table(conn)

    now = datetime.now(UTC).replace(tzinfo=None)
    conn.execute("INSERT INTO oltp_db.sources VALUES (1, '测试信源', 'RSS', 3)")
    for content_id, risk_score in ((1, 80), (2, 83)):
        conn.execute(
            "INSERT INTO oltp_db.content_items VALUES (?, 1, '测试信源', 'AI', ?, ?)",
            [content_id, now, content_id],
        )
        conn.execute(
            "INSERT INTO oltp_db.ai_analyses VALUES (?, ?, 90, 90, 90, 90, 90, 90, 90, 90, 90, ?, ?)",
            [content_id, content_id, risk_score, now],
        )

    analytics = duckdb_service.DuckDBAnalytics()
    monkeypatch.setattr(analytics, "_get_conn", lambda: conn)

    stats = analytics.query_daily_stats()

    assert stats["total_items"] == 1
    assert stats["avg_curation"] == 90.0
    assert stats["max_curation"] == 90.0
    assert stats["topic_count"] == 1

    conn.close()
