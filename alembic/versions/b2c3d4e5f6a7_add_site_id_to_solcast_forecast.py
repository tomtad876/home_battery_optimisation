"""add site_id to solcast_forecast

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-05 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('solcast_forecast', sa.Column('site_id', sa.UUID(), nullable=True))
    op.create_index('ix_solcast_forecast_site_id', 'solcast_forecast', ['site_id'])


def downgrade() -> None:
    op.drop_index('ix_solcast_forecast_site_id', table_name='solcast_forecast')
    op.drop_column('solcast_forecast', 'site_id')
