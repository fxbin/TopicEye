"""
DuckDB analytics mixin — extracted from duckdb_service.py.
Part of the DuckDBAnalytics class split.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services._duckdb_sql import LATEST_ANALYSIS_CTE
from app.services.scoring_engine import CONFIG as SCORING_CONFIG


class PicksMixin:
    def query_today_picks(
        self,
        hours: int = 48,
        curation_threshold: float = 55,
        weight_bonus: int = 8,
        risk_threshold: float | None = None,
        category: str | None = None,
        content_type: str | None = None,
        limit: int | None = None,
        visible_user_id: int | None = None,
        public_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Top curated picks from the last N hours.

        Runs the curation scoring + source weight adjustment entirely in DuckDB.
        Returns items with adjusted_curation_score >= threshold.
        """
        conn = self._get_conn()
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        # 忽略口径按用户隔离：全局屏蔽 + 当前用户个人忽略（匿名只见全局）
        ignored_cte, ignored_params = self._ignored_content_cte_for_user(conn, visible_user_id)
        params: list[Any] = ignored_params + [cutoff]
        feedback_min = float(SCORING_CONFIG["feedback_score_min"])
        feedback_max = float(SCORING_CONFIG["feedback_score_max"])
        feedback_weight = float(SCORING_CONFIG["w_feedback"])
        risk_threshold = float(SCORING_CONFIG["risk_threshold"] if risk_threshold is None else risk_threshold)
        category_clause = ""
        if category:
            category_clause = " AND c.category = ?"
            params.append(category)
        content_type_clause = ""
        has_content_type = self._oltp_column_exists(conn, "content_items", "content_type")
        if content_type and has_content_type:
            content_type_clause = " AND c.content_type = ?"
            params.append(content_type)
        visibility_clause, visibility_params = self._content_visibility_clause(
            conn,
            public_only=public_only,
            visible_user_id=visible_user_id,
        )
        params.extend(visibility_params)
        analysis_source_weight_expr = (
            "a.source_weight AS analysis_source_weight"
            if self._oltp_column_exists(conn, "ai_analyses", "source_weight")
            else "CAST(NULL AS DOUBLE) AS analysis_source_weight"
        )
        # 与 owner_user_id / source_weight 同策略：未迁移的只读快照/测试库
        # 可能还没有 content_type 列，此时 SELECT NULL 保持列位稳定，避免整端点报错。
        content_type_expr = "c.content_type" if has_content_type else "CAST(NULL AS VARCHAR) AS content_type"
        _ = limit

        results = conn.execute(
            f"""
            WITH {LATEST_ANALYSIS_CTE},
            {self._feedback_scores_cte(conn)},
            {ignored_cte}
            SELECT
                c.id, c.title, c.url, c.source_id, c.source_name, c.source_type,
                c.platform, c.author,
                c.published_at, c.crawled_at,
                c.content_hash, c.summary, c.cover_url,
                c.category, {content_type_expr}, c.tags, c.language, c.status, c.is_favorited,
                c.topic_id,
                c.created_at, c.updated_at,
                a.id AS analysis_id, a.created_at AS analysis_created_at,
                a.quality_score, a.hot_score, a.freshness_score,
                a.creator_score, a.viral_score, a.risk_score,
                a.curation_score, a.info_density, a.actionability,
                {analysis_source_weight_expr},
                a.recommended_reason, a.recommendation,
                a.summary AS ai_summary, a.tags AS ai_tags,
                a.key_points, a.audience_emotion, a.creator_angles,
                a.title_suggestions, a.outline_suggestions,
                a.xiaohongshu_plan, a.short_video_plan,
                a.risk_notes, a.platform_fit, a.summary_source,
                a.enrichment_status, a.enrichment,
                COALESCE(s.weight, 3) AS source_weight_db,
                COALESCE(f.feedback_score, 0) AS feedback_score,
                CASE
                    WHEN a.curation_score > 0
                        THEN a.curation_score + (COALESCE(s.weight, 3) - 3) * {weight_bonus}
                             + LEAST({feedback_max}, GREATEST({feedback_min}, COALESCE(f.feedback_score, 0))) * {feedback_weight}
                    ELSE (COALESCE(a.creator_score, 0) + COALESCE(a.viral_score, 0)) / 2.0
                         + (COALESCE(s.weight, 3) - 3) * {weight_bonus}
                         + LEAST({feedback_max}, GREATEST({feedback_min}, COALESCE(f.feedback_score, 0))) * {feedback_weight}
                END AS adjusted_curation_score
            FROM oltp_db.content_items c
            LEFT JOIN latest_analysis a ON a.content_id = c.id
            LEFT JOIN oltp_db.sources s ON s.id = c.source_id
            LEFT JOIN feedback_scores f ON f.content_id = c.id
            LEFT JOIN ignored_content ignored ON ignored.content_id = c.id
            WHERE c.crawled_at >= ?
              AND ignored.content_id IS NULL
              AND a.risk_score <= {risk_threshold}
              AND a.curation_score IS NOT NULL
              {category_clause}
              {content_type_clause}
              {visibility_clause}
            ORDER BY adjusted_curation_score DESC
        """,
            params,
        ).fetchall()

        columns = [
            "id",
            "title",
            "url",
            "source_id",
            "source_name",
            "source_type",
            "platform",
            "author",
            "published_at",
            "crawled_at",
            "content_hash",
            "summary",
            "cover_url",
            "category",
            "content_type",
            "tags",
            "language",
            "status",
            "is_favorited",
            "topic_id",
            "created_at",
            "updated_at",
            "analysis_id",
            "analysis_created_at",
            "quality_score",
            "hot_score",
            "freshness_score",
            "creator_score",
            "viral_score",
            "risk_score",
            "curation_score",
            "info_density",
            "actionability",
            "analysis_source_weight",
            "recommended_reason",
            "recommendation",
            "ai_summary",
            "ai_tags",
            "key_points",
            "audience_emotion",
            "creator_angles",
            "title_suggestions",
            "outline_suggestions",
            "xiaohongshu_plan",
            "short_video_plan",
            "risk_notes",
            "platform_fit",
            "summary_source",
            "enrichment_status",
            "enrichment",
            "source_weight_db",
            "feedback_score",
            "adjusted_curation_score",
        ]

        items: list[dict[str, Any]] = []
        for row in results:
            item = dict(zip(columns, row, strict=False))
            if item["adjusted_curation_score"] < curation_threshold:
                continue
            # Serialize datetime fields
            for dt_field in ("published_at", "crawled_at", "created_at", "updated_at", "analysis_created_at"):
                val = item.get(dt_field)
                if val and hasattr(val, "isoformat"):
                    item[dt_field] = val.isoformat()
            # Round floats
            item["adjusted_curation_score"] = round(float(item["adjusted_curation_score"]), 1)
            for score_field in (
                "quality_score",
                "hot_score",
                "freshness_score",
                "creator_score",
                "viral_score",
                "risk_score",
                "curation_score",
                "info_density",
                "actionability",
                "analysis_source_weight",
                "feedback_score",
            ):
                val = item.get(score_field)
                if val is not None:
                    item[score_field] = float(val)
            items.append(item)

        return items
