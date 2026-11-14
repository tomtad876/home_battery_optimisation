"""Merge the two alembic heads

Two parallel lines of migrations existed: the Oct 2026 line ending at
``a3b4c5d6e7f8`` (historic period_end in UTC) and the tariff/heat-pump line
ending at ``c4d5e6f7a8b9``. Both are physically applied in production, but
alembic could only record one head, so the history was ambiguous.

This merge makes the graph single-headed without changing any schema. Stamp it
on a database that already has both lines applied (do NOT run the parents
again), then upgrade normally.

Revision ID: m1a2b3c4d5e6
Revises: a3b4c5d6e7f8, c4d5e6f7a8b9
Create Date: 2026-11-14
"""

revision = "m1a2b3c4d5e6"
down_revision = ("a3b4c5d6e7f8", "c4d5e6f7a8b9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
