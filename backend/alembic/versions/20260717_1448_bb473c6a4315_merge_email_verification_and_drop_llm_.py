"""merge email_verification and drop_llm_models_owner_scope heads

Revision ID: bb473c6a4315
Revises: e7f8a9b0c1d2, 4e5f6a7b8c9d
Create Date: 2026-07-17 14:48:08.619790

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb473c6a4315'
down_revision: Union[str, None] = ('e7f8a9b0c1d2', '4e5f6a7b8c9d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
