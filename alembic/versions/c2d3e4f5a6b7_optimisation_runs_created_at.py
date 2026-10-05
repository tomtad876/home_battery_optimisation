"""optimisation runs/intervals: created_at + demand_kwh

Two small schema gaps for persisting and analysing optimiser runs:
- optimisation_runs had no created_at, but the Edge Function orders by it
  (always got null). Add it with a server default.
- optimisation_intervals stored battery/grid/cost but not the demand forecast
  it was planned against, so you couldn't score forecast accuracy. Add
  demand_kwh.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "optimisation_runs",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.add_column("optimisation_intervals", sa.Column("demand_kwh", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("optimisation_intervals", "demand_kwh")
    op.drop_column("optimisation_runs", "created_at")
