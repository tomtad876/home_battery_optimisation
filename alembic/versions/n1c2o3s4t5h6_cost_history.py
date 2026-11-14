"""Cost history: per-day savings summary + the tariff history it needs

`daily_cost_summary` stores one row per site per local day with the four cost
layers used for attribution:

    no kit        -> everything bought at the import rate
    solar only    -> PV offsets load, surplus exported
    self-use      -> same, plus a battery that only shifts PV (never grid-charges,
                     never exports from the battery) - the "dumb" installed setup
    actual        -> what the optimiser actually did

    solar_value      = no-kit    - solar-only
    battery_value    = solar-only- self-use
    optimiser_value  = self-use  - actual
    total_value      = no-kit    - actual

`site_tariff_history` exists because those layers have to be priced at the
tariff that was actually in force on the day. The `tariffs` table only holds the
current choice, so without history a backfill would price last winter's Agile
import at today's Cosy rates and last summer's 12p fixed export at today's Agile
export rate. Both errors are material.

Revision ID: n1c2o3s4t5h6
Revises: m1a2b3c4d5e6
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "n1c2o3s4t5h6"
down_revision = "m1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_tariff_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_type", sa.String(), nullable=False),
        sa.Column("import_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("export_type", sa.String(), nullable=False),
        sa.Column("export_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("site_id", "valid_from", name="uq_site_tariff_history_from"),
    )
    op.create_index(
        "ix_site_tariff_history_site_from",
        "site_tariff_history",
        ["site_id", "valid_from"],
    )

    op.create_table(
        "daily_cost_summary",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        # energy
        sa.Column("import_kwh", sa.Float(), nullable=False, server_default="0"),
        sa.Column("export_kwh", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pv_kwh", sa.Float(), nullable=False, server_default="0"),
        sa.Column("load_kwh", sa.Float(), nullable=False, server_default="0"),
        # actual money
        sa.Column("import_cost_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("export_income_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("standing_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("net_cost_gbp", sa.Float(), nullable=False, server_default="0"),
        # counterfactual layers (each includes the standing charge, so comparing
        # two layers cancels it)
        sa.Column("nokit_cost_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("solar_only_cost_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("selfuse_cost_gbp", sa.Float(), nullable=False, server_default="0"),
        # attribution
        sa.Column("solar_value_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("battery_value_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("optimiser_value_gbp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_value_gbp", sa.Float(), nullable=False, server_default="0"),
        # data quality
        sa.Column("soc_min_pct", sa.Float(), nullable=True),
        sa.Column("soc_max_pct", sa.Float(), nullable=True),
        sa.Column("covered_slots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_slots", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("source", sa.String(), nullable=False, server_default="foxess"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("site_id", "day", name="uq_daily_cost_summary_site_day"),
    )
    op.create_index("ix_daily_cost_summary_site_day", "daily_cost_summary", ["site_id", "day"])

    # Default-deny for anon/authenticated (same posture as d3e4f5a6b7c8): the
    # backend and Edge Functions use privileged connections that bypass RLS.
    for table in ("site_tariff_history", "daily_cost_summary"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_daily_cost_summary_site_day", table_name="daily_cost_summary")
    op.drop_table("daily_cost_summary")
    op.drop_index("ix_site_tariff_history_site_from", table_name="site_tariff_history")
    op.drop_table("site_tariff_history")
