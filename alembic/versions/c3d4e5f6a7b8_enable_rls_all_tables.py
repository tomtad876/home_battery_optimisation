"""Enable Row-Level Security on all tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-05 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = [
        'sites', 'batteries', 'tariffs',
        'historic_energy_data', 'solcast_forecast', 'agile_rates',
        'forecast_runs', 'optimisation_runs',
    ]
    for table in tables:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')

    # sites: user_id is varchar, auth.uid() returns uuid — cast to text
    op.execute("""
        CREATE POLICY sites_user_isolation ON sites
        FOR ALL
        USING (user_id = auth.uid()::text)
        WITH CHECK (user_id = auth.uid()::text)
    """)

    # batteries: via site ownership
    op.execute("""
        CREATE POLICY batteries_user_isolation ON batteries
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)

    # tariffs: via site ownership
    op.execute("""
        CREATE POLICY tariffs_user_isolation ON tariffs
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)

    # historic_energy_data: via site ownership
    op.execute("""
        CREATE POLICY historic_energy_data_user_isolation ON historic_energy_data
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)

    # solcast_forecast: via site ownership
    op.execute("""
        CREATE POLICY solcast_forecast_user_isolation ON solcast_forecast
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)

    # agile_rates: read-only for all authenticated users (regional data)
    op.execute("""
        CREATE POLICY agile_rates_read_all ON agile_rates
        FOR SELECT
        USING (true)
    """)

    # forecast_runs: via site ownership
    op.execute("""
        CREATE POLICY forecast_runs_user_isolation ON forecast_runs
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)

    # optimisation_runs: via site ownership
    op.execute("""
        CREATE POLICY optimisation_runs_user_isolation ON optimisation_runs
        FOR ALL
        USING (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
        WITH CHECK (site_id IN (SELECT id FROM sites WHERE user_id = auth.uid()::text))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS sites_user_isolation ON sites")
    op.execute("DROP POLICY IF EXISTS batteries_user_isolation ON batteries")
    op.execute("DROP POLICY IF EXISTS tariffs_user_isolation ON tariffs")
    op.execute("DROP POLICY IF EXISTS historic_energy_data_user_isolation ON historic_energy_data")
    op.execute("DROP POLICY IF EXISTS solcast_forecast_user_isolation ON solcast_forecast")
    op.execute("DROP POLICY IF EXISTS agile_rates_read_all ON agile_rates")
    op.execute("DROP POLICY IF EXISTS forecast_runs_user_isolation ON forecast_runs")
    op.execute("DROP POLICY IF EXISTS optimisation_runs_user_isolation ON optimisation_runs")
    tables = [
        'sites', 'batteries', 'tariffs',
        'historic_energy_data', 'solcast_forecast', 'agile_rates',
        'forecast_runs', 'optimisation_runs',
    ]
    for table in tables:
        op.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')
