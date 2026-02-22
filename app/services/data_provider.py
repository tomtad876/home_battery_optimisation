from datetime import datetime, timezone

import pandas as pd

from sqlalchemy import text

from app.core.database import SessionLocal


def get_optimiser_inputs() -> pd.DataFrame:
    """Return a merged half-hourly DataFrame for the optimiser.

    Columns returned:
      - PeriodEnd: timezone-aware UTC timestamp (half-hour resolution)
      - PvEstimate: solar energy in kWh for the half-hour
      - price: import price (pence)
      - demand: demand energy in kWh for the half-hour

    The function builds a half-hour series for the last `days` days, left-joins
    `solcast_forecast`, `agile_rates`, and an aggregated view of
    `historic_energy_data` (5-minute -> half-hour), and returns a tidy DataFrame.
    """
    session = SessionLocal()
    try:
        sql = text("""WITH five_min AS (
            SELECT 
                period_end, 
                SUM(value) AS value_kw
            FROM public.historic_energy_data
            WHERE variable = 'loadsPower'
            AND period_end >= now() - interval '7 days'
            GROUP BY period_end
        ),

        half_hour_history AS (
            SELECT
                floor(date_part('hour', period_end) * 2 
                    + date_part('minute', period_end) / 30) AS hh_slot,
                AVG(value_kw) / 2.0 AS avg_kwh
            FROM five_min
            GROUP BY hh_slot
        ),

        future_half_hours AS (
            SELECT
                sf.period_end,
                sf.solar_kwh,
                floor(date_part('hour', sf.period_end) * 2 
                    + date_part('minute', sf.period_end) / 30) AS hh_slot
            FROM solcast_forecast sf
            WHERE sf.period_end >= now()
        )

        SELECT
            f.period_end as period_end,
            f.solar_kwh AS pv_estimate,
            ar.import_price as price,
            h.avg_kwh AS demand
        FROM future_half_hours f
        JOIN half_hour_history h
            ON f.hh_slot = h.hh_slot
        JOIN agile_rates ar
            ON ar.period_end = f.period_end
        ORDER BY f.period_end;
        """)
        result = session.execute(sql)
        # Use SQLAlchemy result mappings for robust dict conversion
        try:
            mapped = result.mappings().all()
            rows = [dict(r) for r in mapped]
        except Exception:
            rows = []
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=["period_end", "pv_estimate", "price", "demand"]) 

        # Normalize column names and types
        # handle both tz-aware and tz-naive timestamps returned by the DB
        try:
            df["period_end"] = pd.to_datetime(df["period_end"]).dt.tz_convert("UTC")
        except TypeError:
            df["period_end"] = pd.to_datetime(df["period_end"]).dt.tz_localize("UTC")
        df["pv_estimate"] = df["pv_estimate"].astype(float)
        # price: may be NULL
        df["price"] = df["price"].astype(float)
        # demand_forecast_kwh -> kWh for half-hour
        df["demand"] = df["demand"].astype(float) 

        return df[["period_end", "pv_estimate", "price", "demand"]]
    finally:
        session.close()
