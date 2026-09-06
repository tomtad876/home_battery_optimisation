"""Add auto_push_enabled to batteries and push logging to schedules

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batteries: add auto_push_enabled toggle (opt-in for background schedule push)
    op.add_column('batteries', sa.Column('auto_push_enabled', sa.Boolean(), server_default='false', nullable=False))

    # Schedules: extend with push tracking fields
    op.add_column('schedules', sa.Column('pushed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('schedules', sa.Column('foxess_groups', JSONB(), nullable=True))
    op.add_column('schedules', sa.Column('trigger_source', sa.String(), nullable=True))
    op.add_column('schedules', sa.Column('soc_at_push', sa.Float(), nullable=True))
    op.add_column('schedules', sa.Column('error_message', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('schedules', 'error_message')
    op.drop_column('schedules', 'soc_at_push')
    op.drop_column('schedules', 'trigger_source')
    op.drop_column('schedules', 'foxess_groups')
    op.drop_column('schedules', 'pushed_at')
    op.drop_column('batteries', 'auto_push_enabled')
