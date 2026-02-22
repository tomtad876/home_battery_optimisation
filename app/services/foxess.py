import os
from datetime import timedelta, datetime, timezone
import pandas as pd
import foxesscloud.openapi as f

from app.services.data_provider import get_optimiser_inputs

FOXESS_API_KEY = os.environ.get("FOXESS_API_KEY")

# Work mode constants (from legacy code)
FOXESS_WORK_MODE_SELF_USE = 0
FOXESS_WORK_MODE_CHARGE = 1
FOXESS_WORK_MODE_DISCHARGE = 2

def init_api(api_key: str | None = None):
    if api_key is None:
        api_key = FOXESS_API_KEY
    if api_key is None:
        raise ValueError("FoxESS API key required")
    try:
        f.api_key = api_key
    except Exception:
        pass

def get_agile_prices(days: int = 7) -> pd.DataFrame:
    """Return `PeriodEnd` and `price` from DB-backed inputs (no external API).

    This sources prices from `agile_rates` via the joined `get_optimiser_inputs`.
    """
    # Try DB first
    try:
        df = get_optimiser_inputs(days=days)
        if df is not None and not df.empty:
            return df[["PeriodEnd", "price"]].copy()
    except Exception:
        pass

    # Fallback to FoxESS API behaviour (kept for compatibility/tests)
    agile_prices = f.get_agile_times()
    prices_df = pd.DataFrame(agile_prices["prices"])

    base_time = agile_prices.get("base_time")
    base_time_dt = pd.to_datetime(base_time, utc=True, errors="coerce")
    if pd.isna(base_time_dt):
        base_time_dt = pd.to_datetime(base_time, format="%Y-%m-%d", utc=True, errors="coerce")
    if pd.isna(base_time_dt):
        raise ValueError("Unable to parse agile base_time from FoxESS response")

    prices_df["PeriodEnd"] = base_time_dt + pd.to_timedelta(prices_df["hour"], unit="h") + timedelta(minutes=30)
    prices_df["PeriodEnd"] = prices_df["PeriodEnd"].dt.tz_convert("UTC")
    return prices_df[["PeriodEnd", "price"]]

def get_demand_forecast(days: int = 7) -> pd.DataFrame:
    """Return average half-hourly demand (kWh) over the last `days` days from DB.

    This replaces the old API-backed implementation and uses `get_optimiser_inputs`.
    """
    # Try DB first
    try:
        df = get_optimiser_inputs(days=days)
        if df is not None and not df.empty:
            df["time_of_day"] = df["PeriodEnd"].dt.time
            avg = df.groupby("time_of_day")["demand"].mean().reset_index()
            avg = avg.rename(columns={"demand": "energy_kwh"})
            return avg
    except Exception:
        pass

    # Fallback to API behaviour
    load_history = pd.DataFrame(f.get_history('week', d=datetime.today(), v=f.power_vars))
    load_history = load_history.loc[load_history['variable'] == 'loadsPower'].dropna()['data'].explode().apply(pd.Series)
    load_history["time"] = pd.to_datetime(load_history["time"], utc=True, errors="coerce")
    load_history = load_history.dropna(subset=["time", "value"]) 
    load_history = load_history.set_index("time").sort_index()
    load_history["dt_hours"] = load_history.index.to_series().diff().dt.total_seconds().div(3600)
    load_history["energy_kwh"] = load_history["value"].shift(1) * load_history["dt_hours"]
    load_history = load_history.dropna(subset=["energy_kwh"]) 
    half_hourly = load_history["energy_kwh"].resample("30min", label="right", closed="right").sum()
    half_hourly = half_hourly.reset_index()
    half_hourly["time_utc"] = half_hourly["time"].dt.tz_convert("UTC")
    half_hourly["time_of_day"] = half_hourly["time_utc"].dt.time
    avg_profile = half_hourly.groupby("time_of_day")["energy_kwh"].mean()
    return avg_profile.reset_index()

def create_foxess_schedule_df(optimiser_result_df: pd.DataFrame) -> pd.DataFrame:
    schedule_data = []
    for i, row in optimiser_result_df.iterrows():
        end_time = row["PeriodEnd"]
        start_time = end_time - timedelta(minutes=30)
        start_str = start_time.strftime("%H:%M")
        end_str = end_time.strftime("%H:%M")
        net_battery = row.get("net_battery_kwh", 0)
        if net_battery > 0.05:
            work_mode = FOXESS_WORK_MODE_CHARGE
        elif net_battery < -0.05:
            work_mode = FOXESS_WORK_MODE_DISCHARGE
        else:
            work_mode = FOXESS_WORK_MODE_SELF_USE
        schedule_data.append({"start": start_str, "end": end_str, "WorkMode": int(work_mode)})
    return pd.DataFrame(schedule_data)

def send_schedule(device_sn: str, schedule_df, min_soc: int = 20, max_soc: int = 90, fd_pwr: float = 3000):
    """Send schedule (DataFrame with start,end,WorkMode) to FoxESS cloud via signed_post helper."""
    mode_change = schedule_df["WorkMode"] != schedule_df["WorkMode"].shift()
    midnight_break = schedule_df["start"] == '00:00'
    schedule_df["grp"] = (mode_change | midnight_break.fillna(True)).cumsum()
    grouped = schedule_df.groupby(["grp", "WorkMode"], as_index=False).agg({"start": "first", "end": "last"})
    groups = []
    for _, row in grouped.iterrows():
        start_h, start_m = map(int, row["start"][-5:].split(":"))
        end_h, end_m = map(int, row["end"][-5:].split(":"))
        if end_m == 0:
            end_m = 59
            end_h = (end_h - 1 + 24) % 24
        else:
            end_m = (end_m - 1) % 60
        work_mode = row["WorkMode"]
        group = {
            "enable": 1,
            "startHour": start_h,
            "startMinute": start_m,
            "endHour": end_h,
            "endMinute": end_m,
            "workMode": work_mode,
            "minSocOnGrid": min_soc,
            "fdSoc": min_soc,
            "fdPwr": fd_pwr,
            "maxSoc": max_soc,
        }
        groups.append(group)
    url_to_sign = "/op/v1/device/scheduler/enable"
    payload = {"deviceSN": device_sn, "groups": groups}
    response = f.signed_post(path=url_to_sign, body=payload)
    return response

