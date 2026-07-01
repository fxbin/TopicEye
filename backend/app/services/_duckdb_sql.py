"""DuckDB SQL CTE 常量与统计阈值。

从 app.services.duckdb_service 抽出的纯字符串常量，便于：
- 复用同一份 CTE 在多个分析查询中保持一致（避免重复定义漂移）
- 单独单测 SQL 拼接结果
- 减少 duckdb_service.py 体积（其单类已 900+ 行）

包含：
- LATEST_ANALYSIS_CTE         — 每条 content 取最新分析
- LATEST_FEEDBACK_SCORES_CTE  — 每条 content 取最新用户反馈聚合
- EMPTY_FEEDBACK_SCORES_CTE   — 无反馈时的占位 CTE
- IGNORED_CONTENT_CTE         — 已忽略内容 ID 列表
- STATS_CURATION_FALLBACK_THRESHOLD — curation 分数 fallback 阈值（>=此值视为精选）
"""

from __future__ import annotations

STATS_CURATION_FALLBACK_THRESHOLD = 83.0

LATEST_ANALYSIS_CTE = """
latest_analysis AS (
    SELECT *
    FROM (
        SELECT
            a.*,
            ROW_NUMBER() OVER (
                PARTITION BY a.content_id
                ORDER BY a.created_at DESC, a.id DESC
            ) AS analysis_rank
        FROM oltp_db.ai_analyses a
    )
    WHERE analysis_rank = 1
)
"""

LATEST_FEEDBACK_SCORES_CTE = """
latest_user_feedback AS (
    SELECT *
    FROM (
        SELECT
            f.*,
            ROW_NUMBER() OVER (
                PARTITION BY f.content_id, f.user_id
                ORDER BY f.created_at DESC, f.id DESC
            ) AS feedback_rank
        FROM oltp_db.user_feedback f
    )
    WHERE feedback_rank = 1
),
feedback_scores AS (
    SELECT
        content_id,
        SUM(score_delta) AS feedback_score
    FROM latest_user_feedback
    GROUP BY content_id
)
"""

EMPTY_FEEDBACK_SCORES_CTE = """
feedback_scores AS (
    SELECT
        CAST(NULL AS INTEGER) AS content_id,
        CAST(0 AS DOUBLE) AS feedback_score
    WHERE FALSE
)
"""

IGNORED_CONTENT_CTE = """
ignored_content AS (
    SELECT DISTINCT content_id
    FROM oltp_db.ignored_items
)
"""