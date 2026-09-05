"""add user_id to sites and site_id to historic_energy_data

Revision ID: a1b2c3d4e5f6
Revises: 8f6de9dc8d0d
Create Date: 2026-09-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8f6de9dc8d0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add user_id to sites (nullable initially, will be backfilled)
    op.add_column('sites', sa.Column('user_id', sa.String(), nullable=True))
    op.create_index('ix_sites_user_id', 'sites', ['user_id'])

    # Add site_id to historic_energy_data (nullable initially, will be backfilled)
    op.add_column('historic_energy_data', sa.Column('site_id', sa.UUID(), nullable=True))
    op.create_index('ix_historic_energy_data_site_id', 'historic_energy_data', ['site_id'])


def downgrade() -> None:
    op.drop_index('ix_historic_energy_data_site_id', table_name='historic_energy_data')
    op.drop_column('historic_energy_data', 'site_id')
    op.drop_index('ix_sites_user_id', table_name='sites')
    op.drop_column('sites', 'user_id')
