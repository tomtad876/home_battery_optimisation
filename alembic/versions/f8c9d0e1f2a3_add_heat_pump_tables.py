"""Add heat_pumps + heat_pump_data for Octopus heat-pump ingestion

`heat_pumps` caches the discovered controller (euid/property) per site so each
poll only needs the token + one data query, rather than re-discovering.
`heat_pump_data` stores one row per poll: live performance (power input, heat
output, COP, outdoor temp), cumulative lifetime counters (Δ between rows =
energy per interval) and the zone/water state. Unique(site_id, read_at) so the
poll is an idempotent upsert.

Octopus credentials (octopus_api_key, octopus_account_number) live in the
existing encrypted `batteries.provider_config` — no schema change needed.

Revision ID: f8c9d0e1f2a3
Revises: f7b8c9d0e1f2
Create Date: 2026-09-21 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'f8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'f7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('heat_pumps', 'heat_pump_data')


def upgrade() -> None:
    op.create_table(
        'heat_pumps',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('site_id', UUID(as_uuid=True), sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('euid', sa.String(), nullable=False),
        sa.Column('property_id', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('site_id', 'euid', name='uq_heat_pumps_site_euid'),
    )

    op.create_table(
        'heat_pump_data',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('site_id', UUID(as_uuid=True), sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=False),
        # live performance
        sa.Column('power_input_kw', sa.Float(), nullable=True),
        sa.Column('heat_output_kw', sa.Float(), nullable=True),
        sa.Column('cop', sa.Float(), nullable=True),
        sa.Column('outdoor_temp_c', sa.Float(), nullable=True),
        # cumulative lifetime counters
        sa.Column('lifetime_energy_input_kwh', sa.Float(), nullable=True),
        sa.Column('lifetime_heat_output_kwh', sa.Float(), nullable=True),
        sa.Column('lifetime_scop', sa.Float(), nullable=True),
        # water/zone state
        sa.Column('water_mode', sa.String(), nullable=True),
        sa.Column('water_setpoint_c', sa.Float(), nullable=True),
        sa.Column('zones', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('site_id', 'read_at', name='uq_heat_pump_data_site_read_at'),
    )
    op.create_index('ix_heat_pump_data_site_read', 'heat_pump_data', ['site_id', 'read_at'])

    for table in _TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f"""
            CREATE POLICY {table}_user_isolation ON {table}
            FOR ALL
            USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
            WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        """)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f'DROP POLICY IF EXISTS {table}_user_isolation ON {table}')
    op.drop_index('ix_heat_pump_data_site_read', table_name='heat_pump_data')
    op.drop_table('heat_pump_data')
    op.drop_table('heat_pumps')
