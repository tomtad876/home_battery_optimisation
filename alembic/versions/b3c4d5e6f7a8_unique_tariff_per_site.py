"""One tariff row per site.

Switching tariffs updates the existing row instead of appending a second one —
the optimiser reads a single active tariff, so duplicates would make the choice
ambiguous. Dedupe before creating the index (prod currently has exactly one row
per site, so this is a no-op there).
"""
from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM tariffs a
        USING tariffs b
        WHERE a.site_id = b.site_id
          AND a.id::text > b.id::text
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tariffs_site_id ON tariffs (site_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tariffs_site_id")
