from datetime import datetime, timezone

import pandas as pd

from sqlalchemy import text

from app.core.database import SessionLocal


def get_optimiser_inputs(site_id: str) -> pd.DataFrame:
    """Return a merged half-hourly DataFrame for the optimiser.

    Columns returned:
      - period_end: timezone-aware UTC timestamp (half-hour resolution)
      - pv_estimate: solar energy in kWh for the half-hour
      - price: import price (pence)
      - demand: demand energy in kWh for the half-hour

    The function builds a half-hour series for the last 7 days, left-joins
    `solcast_forecast`, `agile_rates`, and an aggregated view of
    `historic_energy_data` (5-minute -> half-hour), filtered by site_id.
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
            AND site_id = :site_id
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
            AND sf.site_id = :site_id
        )

        SELECT
            f.period_end as period_end,
            f.solar_kwh AS pv_estimate,
            ar.import_price as price,
            ar.export_price,
            h.avg_kwh AS demand
        FROM future_half_hours f
        JOIN half_hour_history h
            ON f.hh_slot = h.hh_slot
        JOIN agile_rates ar
            ON ar.period_end = f.period_end
        ORDER BY f.period_end;
        """)
        result = session.execute(sql, {"site_id": site_id})
        # Use SQLAlchemy result mappings for robust dict conversion
        try:
            mapped = result.mappings().all()
            rows = [dict(r) for r in mapped]
        except Exception:
            rows = []
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=["period_end", "pv_estimate", "price", "export_price", "demand"]) 

        # Normalize column names and types
        # handle both tz-aware and tz-naive timestamps returned by the DB
        try:
            df["period_end"] = pd.to_datetime(df["period_end"]).dt.tz_convert("UTC")
        except TypeError:
            df["period_end"] = pd.to_datetime(df["period_end"]).dt.tz_localize("UTC")
        df["pv_estimate"] = df["pv_estimate"].astype(float)
        # price: may be NULL
        df["price"] = df["price"].astype(float)
        df["export_price"] = df["export_price"].astype(float)
        # demand_forecast_kwh -> kWh for half-hour
        df["demand"] = df["demand"].astype(float) 

        return df[["period_end", "pv_estimate", "price", "export_price", "demand"]]
    finally:
        session.close()


def get_user_site(user_id: str) -> dict | None:
    """Look up the user's site by their auth UID. Returns dict with id, name, timezone or None."""
    session = SessionLocal()
    try:
        result = session.execute(
            text("SELECT id, name, timezone FROM sites WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id}
        )
        row = result.mappings().first()
        return dict(row) if row else None
    finally:
        session.close()


def create_site(user_id: str, name: str, timezone: str = "Europe/London") -> dict:
    """Create a new site for a user. Returns the created site dict."""
    session = SessionLocal()
    try:
        result = session.execute(
            text("INSERT INTO sites (id, name, timezone, user_id) VALUES (gen_random_uuid(), :name, :tz, :uid) RETURNING id, name, timezone"),
            {"name": name, "tz": timezone, "uid": user_id}
        )
        row = result.mappings().first()
        session.commit()
        return dict(row)
    finally:
        session.close()


def create_battery(site_id: str, capacity_kwh: float, max_charge_kw: float,
                   max_discharge_kw: float, min_soc_pct: float, max_soc_pct: float,
                   provider_type: str, provider_config: dict | None = None) -> dict:
    """Create a battery config for a site."""
    session = SessionLocal()
    try:
        import json
        result = session.execute(
            text("""INSERT INTO batteries (id, site_id, capacity_kwh, max_charge_kw, max_discharge_kw, min_soc_pct, max_soc_pct, provider_type, provider_config)
                    VALUES (gen_random_uuid(), :sid, :cap, :mch, :mdis, :minsoc, :maxsoc, :ptype, CAST(:pconf AS json))
                    RETURNING id, site_id, capacity_kwh, max_charge_kw, max_discharge_kw, min_soc_pct, max_soc_pct, provider_type"""),
            {"sid": site_id, "cap": capacity_kwh, "mch": max_charge_kw, "mdis": max_discharge_kw,
             "minsoc": min_soc_pct, "maxsoc": max_soc_pct, "ptype": provider_type,
             "pconf": json.dumps(provider_config or {})}
        )
        row = result.mappings().first()
        session.commit()
        return dict(row)
    finally:
        session.close()


def create_tariff(site_id: str, import_type: str, export_type: str, config_json: dict | None = None) -> dict:
    """Create a tariff config for a site."""
    session = SessionLocal()
    try:
        import json
        result = session.execute(
            text("""INSERT INTO tariffs (id, site_id, import_type, export_type, config_json)
                    VALUES (gen_random_uuid(), :sid, :itype, :etype, CAST(:conf AS json))
                    RETURNING id, site_id, import_type, export_type, config_json"""),
            {"sid": site_id, "itype": import_type, "etype": export_type,
             "conf": json.dumps(config_json or {})}
        )
        row = result.mappings().first()
        session.commit()
        return dict(row)
    finally:
        session.close()
