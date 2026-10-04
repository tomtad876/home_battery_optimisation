"""add holiday mode to sites

Holiday mode: while the household is away, the demand forecast collapses to
baseload (plus any explicitly scheduled events) instead of the 7-day
half-hour-of-day average. `holiday_until` auto-expires the flag so it cannot
silently stay on.

Revision ID: a9b0c1d2e3f4
Revises: f8c9d0e1f2a3
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a9b0c1d2e3f4"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("holiday_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "sites",
        sa.Column("holiday_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "holiday_until")
    op.drop_column("sites", "holiday_mode")
