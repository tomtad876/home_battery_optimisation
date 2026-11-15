"""Flexibility (VPP) income as a site setting

Axle pays for battery flexibility on separate payment rails, so it never appears
in the Octopus meter or tariff data the cost history is built from. Ingesting
bank statements into this app was explicitly rejected, and Axle's API is
partner-only (organisational bearer token), so the honest interim is an
assumption the user sets: a monthly floor, accrued daily.

Default 0 — it applies to nobody until a site opts in, and the dashboard labels
it as estimated rather than measured.

Revision ID: o1d2e3f4g5h6
Revises: n1c2o3s4t5h6
Create Date: 2026-11-15
"""
from alembic import op
import sqlalchemy as sa

revision = "o1d2e3f4g5h6"
down_revision = "n1c2o3s4t5h6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("flex_income_pence_per_month", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_cost_summary",
        sa.Column("flex_income_gbp", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("daily_cost_summary", "flex_income_gbp")
    op.drop_column("sites", "flex_income_pence_per_month")
