"""add historic_energy_data table

Revision ID: 8f6de9dc8d0d
Revises: 4e02e44fc34c
Create Date: 2026-02-21 22:59:20.517573

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f6de9dc8d0d'
down_revision: Union[str, Sequence[str], None] = '4e02e44fc34c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historic_energy_data",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text("gen_random_uuid()")),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("variable", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("time", sa.String(), nullable=True),
        sa.UniqueConstraint("period_end", "variable", name="uq_period_variable"),
    )


def downgrade() -> None:
    op.drop_table("historic_energy_data")
