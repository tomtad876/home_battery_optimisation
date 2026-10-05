"""schedules.id: add a server-side default

The SQLAlchemy model supplies a Python-side uuid4 default, so inserts through
the ORM work — but the Edge Function inserts via PostgREST without an id, and
the column had no server default, so every auto-push audit insert failed with a
NOT NULL violation (silently, because the function didn't check the result).

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("schedules", "id", server_default=sa.text("gen_random_uuid()"))


def downgrade() -> None:
    op.alter_column("schedules", "id", server_default=None)
