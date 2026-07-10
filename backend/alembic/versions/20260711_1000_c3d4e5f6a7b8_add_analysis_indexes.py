"""add critical indexes for latest-analysis and content-list queries

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-11 10:00:00

补三个影响性能的关键索引：

1. ai_analyses(content_id, created_at) — latest_analysis_id_subquery 对每行
   content_item 做 correlated subquery 查 ai_analyses,该表之前完全无索引,
   导致低粉爆文、今日选题计数、内容列表等全量扫描。

2. content_items(status, crawled_at) — list_for_scoring / 低粉爆文按
   status='analyzed' AND crawled_at >= cutoff 过滤,无复合索引时全表扫描。

3. trending_snapshots(snapshot_date, snapshot_hour, source) — get_snapshot_diff
   按这三列过滤,之前只有 snapshot_date 单列索引。
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. ai_analyses: 消灭逐行 correlated subquery 的全表扫描
    op.create_index(
        'ix_ai_analyses_content_id_created',
        'ai_analyses',
        ['content_id', 'created_at'],
    )

    # 2. content_items: 支撑 status + crawled_at 复合过滤
    op.create_index(
        'ix_content_items_status_crawled',
        'content_items',
        ['status', 'crawled_at'],
    )

    # 3. trending_snapshots: 支撑 snapshot_date + snapshot_hour + source 查询
    op.create_index(
        'ix_trending_snapshots_date_hour_source',
        'trending_snapshots',
        ['snapshot_date', 'snapshot_hour', 'source'],
    )


def downgrade() -> None:
    op.drop_index('ix_trending_snapshots_date_hour_source', table_name='trending_snapshots')
    op.drop_index('ix_content_items_status_crawled', table_name='content_items')
    op.drop_index('ix_ai_analyses_content_id_created', table_name='ai_analyses')
