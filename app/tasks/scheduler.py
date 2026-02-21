from datetime import datetime, timezone, timedelta
import math
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.services import solcast, foxess, forecast
from app.core.database import SessionLocal
from app.models.forecast import ForecastRun, ForecastInterval
import pandas as pd
import numpy as np

scheduler = BackgroundScheduler()


def _utc_naive(dt):
    # store as naive UTC for DB
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _store_forecast(df, run_time=None):
    """Store merged forecast DataFrame into DB.
    Expected columns: PeriodEnd, PvEstimate, price, (and demand if merged)
    """
    if run_time is None:
        run_time = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        fr = ForecastRun(site_id=None, run_time=_utc_naive(run_time))
        session.add(fr)
        session.flush()
        for _, r in df.iterrows():
            period_end = r.get('PeriodEnd') if 'PeriodEnd' in r else None
            if period_end is None or (hasattr(period_end, 'tzinfo') and period_end.tzinfo is None and not isinstance(period_end, datetime)):
                # try to parse
                try:
                    period_end = pd.to_datetime(period_end, utc=True)
                except Exception:
                    continue
            period_end = _utc_naive(period_end)
            solar_kwh = float(r.get('PvEstimate', 0.0) or 0.0)
            import_price = float(r.get('price', 0.0) or 0.0)
            demand_kwh = float(r.get('demand', 0.0) or 0.0)
            export_price = float(r.get('export_price', 0.0) or 0.0)
            fi = ForecastInterval(forecast_run_id=fr.id, period_end=period_end,
                                  solar_kwh=solar_kwh, demand_kwh=demand_kwh,
                                  import_price=import_price, export_price=export_price)
            session.add(fi)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def fetch_and_store_solcast():
    """Fetch Solcast forecasts and store to DB. Limited to 10 calls/day by free API."""
    # Use SOLCAST_PV_SYSTEM_ID from env inside solcast service
    df = solcast.get_solar_forecast(None, None)
    if df is None or df.empty:
        return
    df = df[['PeriodEnd', 'PvEstimate']].copy()
    df['price'] = np.nan
    df['demand'] = np.nan
    _store_forecast(df)


def fetch_and_store_prices():
    """Fetch Octopus/Agile prices from FoxESS and store. Retry once if empty."""
    prices = foxess.get_agile_prices()
    if prices is None or prices.empty:
        prices = foxess.get_agile_prices()
    if prices is None or prices.empty:
        return
    df = prices.rename(columns={'price': 'price'}).copy()
    df['PvEstimate'] = np.nan
    df['demand'] = np.nan
    _store_forecast(df)


def fetch_and_store_demand():
    df = foxess.get_demand_forecast(days=7)
    if df is None or df.empty:
        return
    now = datetime.now(timezone.utc)
    rows = []
    for h in range(0, 48):
        period_end = now + timedelta(minutes=30 * (h + 1))
        tod = period_end.time().replace(second=0, microsecond=0)
        match = df.loc[df['time_of_day'] == tod]
        demand = float(match['energy_kwh'].iloc[0]) if not match.empty else 0.0
        rows.append({'PeriodEnd': period_end, 'PvEstimate': np.nan, 'price': np.nan, 'demand': demand})
    df_store = pd.DataFrame(rows)
    _store_forecast(df_store)


def schedule_jobs():
    # Solcast: 10 times between 07:00 and 22:00 inclusive
    start_hour = 7
    end_hour = 22
    samples = 10
    span = end_hour - start_hour
    interval = span / (samples - 1)
    for i in range(samples):
        hour_f = start_hour + i * interval
        hour = int(math.floor(hour_f))
        minute = int(round((hour_f - hour) * 60))
        trigger = CronTrigger(hour=hour, minute=minute)
        scheduler.add_job(fetch_and_store_solcast, trigger, id=f"solcast_{i}")

    # Prices: daily around 16:00 (allow a small offset)
    scheduler.add_job(fetch_and_store_prices, CronTrigger(hour=16, minute=5), id='prices_daily')

    # Demand forecast: daily at 03:00
    scheduler.add_job(fetch_and_store_demand, CronTrigger(hour=3, minute=0), id='demand_daily')


def start():
    schedule_jobs()
    scheduler.start()


def stop():
    scheduler.shutdown(wait=False)
