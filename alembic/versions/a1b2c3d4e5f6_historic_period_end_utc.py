"""historic_energy_data.period_end -> timestamptz (store UTC, not local)

Revision ID: a1b2c3d4e5f6
Revises: e1f2a3b4c5d6
Create Date: 2026-10-25

`period_end` was a naive timestamp holding *London local* wall-clock time. On
2026-10-25 (autumn change) 01:00-02:00 happened twice, the ingest upserts on
(site_id, period_end, variable) so the second pass silently overwrote the
first, and pandas could not localise the ambiguous value ("Cannot infer dst
time from 2026-10-25 01:03:32") — which 500'd /events/detect.

The FoxESS history API sends the offset in its `time` string
("2026-07-15 11:03:33 BST+0100"), which the ingest stored verbatim in the
`time` column, so the true instant is recoverable for every row that has one.
Do NOT rely on Postgres parsing "BST+0100" directly — it mis-reads it (verified:
'2026-07-15 11:03:33 BST+0100'::timestamptz = 2026-07-19 15:03:33Z), hence the
substr/right surgery to build a plain ISO offset.

Rows with no usable `time` (3,080 of 555,239 at the time of writing) fall back
to interpreting the stored local value as Europe/London.
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None

_TIME_WITH_OFFSET = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [A-Za-z]+\s*[+-]\d{4}$"

UPGRADE = f"""
ALTER TABLE historic_energy_data
    ALTER COLUMN period_end TYPE timestamptz
    USING (
        CASE
            WHEN time ~ '{_TIME_WITH_OFFSET}'
                THEN (substr(time, 1, 19) || right(time, 5))::timestamptz
            ELSE period_end AT TIME ZONE 'Europe/London'
        END
    );
"""

DOWNGRADE = """
ALTER TABLE historic_energy_data
    ALTER COLUMN period_end TYPE timestamp
    USING (period_end AT TIME ZONE 'Europe/London');
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
