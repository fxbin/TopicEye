"""oauth accounts

Revision ID: a1b2c3d4e5f6
Revises: d4e5f6a7b8c9
Create Date: 2026-07-04 12:00:00

新增 user_oauth_accounts 表，支持 Google/GitHub OAuth 登录。
- 一个 provider 用户只能关联一个本地账号（provider + provider_user_id 唯一）
- 首次 OAuth 登录时若邮箱已验证且与现有账号相同，自动合并到该账号
- 同时把 users.password_hash 改为 nullable —— 纯 OAuth 用户没有密码

downgrade 注意：若已存在 password_hash IS NULL 的 OAuth-only 用户，
改回 NOT NULL 会失败；生产环境 downgrade 前需先给这些用户补密码或删除。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. password_hash 改 nullable（纯 OAuth 用户无密码）
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              existing_type=sa.String(length=512),
                              nullable=True)

    # 2. user_oauth_accounts 表
    op.create_table(
        'user_oauth_accounts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('provider_email', sa.String(length=255), nullable=False),
        sa.Column('email_verified', sa.Boolean(), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint(
            'provider', 'provider_user_id',
            name='uq_user_oauth_accounts_provider_user',
        ),
    )
    # 按 email 自动合并时查询用
    op.create_index(
        'ix_user_oauth_accounts_provider_email', 'user_oauth_accounts',
        ['provider', 'provider_email'],
    )
    op.create_index(
        'ix_user_oauth_accounts_user_id', 'user_oauth_accounts', ['user_id'],
    )


def downgrade() -> None:
    # 注意：若存在 password_hash IS NULL 的 OAuth-only 用户，下面这行会失败。
    # 先给这些用户补密码或删除后再 downgrade。
    op.drop_index('ix_user_oauth_accounts_user_id', table_name='user_oauth_accounts')
    op.drop_index('ix_user_oauth_accounts_provider_email', table_name='user_oauth_accounts')
    op.drop_table('user_oauth_accounts')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              existing_type=sa.String(length=512),
                              nullable=False)
