"""Add site_id to the historic_energy_data unique constraint

`uq_period_variable` was UNIQUE(period_end, variable) — missing site_id — so two
tenants couldn't store the same slot/variable: the fetch-demand upsert would
silently overwrite one tenant's value/unit/name while leaving site_id pointing
at the other. Fix: UNIQUE(site_id, period_end, variable).

Single real site today, so there are no duplicate rows and the swap is safe.
fetch-demand's onConflict string must be updated in lockstep ("site_id,
period_end,variable"), otherwise its upsert fails with "no unique or exclusion
constraint matching the ON CONFLICT specification".

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-21 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('uq_period_variable', 'historic_energy_data', type_='unique')
    op.create_unique_constraint(
        'uq_site_period_variable', 'historic_energy_data',
        ['site_id', 'period_end', 'variable'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_site_period_variable', 'historic_energy_data', type_='unique')
    op.create_unique_constraint(
        'uq_period_variable', 'historic_energy_data',
        ['period_end', 'variable'],
    )
