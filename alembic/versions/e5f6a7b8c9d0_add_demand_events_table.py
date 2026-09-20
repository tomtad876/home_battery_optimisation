"""Add demand_events table for appliance-labelled demand events

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-20 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'demand_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('site_id', UUID(as_uuid=True), sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('appliance', sa.String(), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='confirmed'),
        sa.Column('energy_kwh', sa.Float(), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='manual'),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_demand_events_site_start', 'demand_events', ['site_id', 'start_time'])
    op.execute('ALTER TABLE demand_events ENABLE ROW LEVEL SECURITY')
    op.execute("""
        CREATE POLICY demand_events_user_isolation ON demand_events
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS demand_events_user_isolation ON demand_events')
    op.drop_index('ix_demand_events_site_start', table_name='demand_events')
    op.drop_table('demand_events')
