"""Add calibration fields to demand_events + demand_day_inventory table

Two things this enables (demand-forecasting Phase 2 groundwork):

1. `demand_events.cleanliness` — the primary filter for template fitting.
   Template signatures must be fit on isolated examples only; contamination
   inflates them. Values: 'clean' (only this appliance ran), 'unsure',
   'contaminated' (other appliances running). NULL = not yet annotated
   (existing/seeded rows).
2. `demand_events.target_temp` / `start_temp` — the Cosy (heat pump, DHW mode)
   is a function of temperature lift, not a fixed template, so the labelling
   form records the DHW setpoint (50/60) and, when known, the tank start temp.

3. `demand_day_inventory` — a per-day "what ran today" tick-list. This gives
   set-level labels *with negatives*: on a day whose inventory is a single
   appliance, every detected window that day is provably clean. It is the
   supervision channel the per-window card cannot supply, and doubles as the
   future Phase-4 "what's running / what should run" override surface.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-21 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1 + 2: per-event calibration annotations (all nullable — additive only).
    op.add_column('demand_events', sa.Column('cleanliness', sa.String(), nullable=True))
    op.add_column('demand_events', sa.Column('target_temp', sa.Float(), nullable=True))
    op.add_column('demand_events', sa.Column('start_temp', sa.Float(), nullable=True))

    # 3: per-day appliance inventory (set-level supervision labels).
    op.create_table(
        'demand_day_inventory',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('site_id', UUID(as_uuid=True), sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('appliances', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('site_id', 'day', name='uq_demand_day_inventory_site_day'),
    )
    op.create_index('ix_demand_day_inventory_site_day', 'demand_day_inventory', ['site_id', 'day'])
    op.execute('ALTER TABLE demand_day_inventory ENABLE ROW LEVEL SECURITY')
    op.execute("""
        CREATE POLICY demand_day_inventory_user_isolation ON demand_day_inventory
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS demand_day_inventory_user_isolation ON demand_day_inventory')
    op.drop_index('ix_demand_day_inventory_site_day', table_name='demand_day_inventory')
    op.drop_table('demand_day_inventory')
    op.drop_column('demand_events', 'start_temp')
    op.drop_column('demand_events', 'target_temp')
    op.drop_column('demand_events', 'cleanliness')
