"""Enable RLS on tables created after the initial RLS pass

The 2026-09-05 migration (c3d4e5f6a7b8) enabled RLS on the tables that existed
then, but three were created later and left with RLS disabled, so Supabase
flagged `rls_disabled_in_public`: anyone with the public (anon) key could
read/write them over PostgREST.

No policies are added: the app accesses these only through the FastAPI backend
(postgres superuser) and Edge Functions (service role), which both bypass RLS,
so default-deny for anon/authenticated is correct and the safest outcome.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("forecast_intervals", "optimisation_intervals", "schedules"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ("forecast_intervals", "optimisation_intervals", "schedules"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
