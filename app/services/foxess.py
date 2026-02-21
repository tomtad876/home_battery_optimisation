import os
from datetime import timedelta, datetime
import pandas as pd
import foxesscloud.openapi as f

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
    f.api_key = api_key

def get_agile_prices():
    """Return a DataFrame with `PeriodEnd` (UTC) and `price` (pence).
    Uses foxesscloud helper to fetch Octopus Agile prices.
    """
    agile_prices = f.get_agile_times()
    prices_df = pd.DataFrame(agile_prices["prices"])

    # Parse base_time robustly (accept date-only or timezone-less strings)
    base_time = agile_prices.get("base_time")
    base_time_dt = pd.to_datetime(base_time, utc=True, errors="coerce")
    if pd.isna(base_time_dt):
        # Try parsing as date-only (YYYY-MM-DD)
        base_time_dt = pd.to_datetime(base_time, format="%Y-%m-%d", utc=True, errors="coerce")
    if pd.isna(base_time_dt):
        raise ValueError("Unable to parse agile base_time from FoxESS response")

    prices_df["PeriodEnd"] = base_time_dt + pd.to_timedelta(prices_df["hour"], unit="h") + timedelta(minutes=30)

    # Ensure UTC timezone (PeriodEnd already tz-aware thanks to utc=True above)
    prices_df["PeriodEnd"] = prices_df["PeriodEnd"].dt.tz_convert("UTC")
    return prices_df[["PeriodEnd", "price"]]

def get_demand_forecast(days: int = 7) -> pd.DataFrame:
    """Fetch last N days of load history from FoxESS and return time-of-day average.
    
    Returns DataFrame with `time_of_day` (time) and `energy_kwh` (average half-hourly energy).
    """
    # Get load history for the specified days
    load_history = pd.DataFrame(f.get_history('week', d=datetime.today(), v=f.power_vars))
    load_history = load_history.loc[load_history['variable'] == 'loadsPower'].dropna()['data'].explode().apply(pd.Series)

    # Parse times robustly (accept date-only and timezone-less strings). Drop unparseable rows.
    load_history["time"] = pd.to_datetime(load_history["time"], utc=True, errors="coerce")
    load_history = load_history.dropna(subset=["time", "value"])
    load_history = load_history.set_index("time").sort_index()

    # Calculate time differences in hours
    load_history["dt_hours"] = load_history.index.to_series().diff().dt.total_seconds().div(3600)

    # Energy (kWh) = Power (kW) * duration (hours)
    load_history["energy_kwh"] = load_history["value"].shift(1) * load_history["dt_hours"]

    # Drop the first row (NaN interval)
    load_history = load_history.dropna(subset=["energy_kwh"])

    # Resample into half-hour bins and sum
    half_hourly = load_history["energy_kwh"].resample("30min", label="right", closed="right").sum()
    half_hourly = half_hourly.reset_index()
    half_hourly["time_utc"] = half_hourly["time"].dt.tz_convert("UTC")

    # Extract just the time of day (ignoring the date)
    half_hourly["time_of_day"] = half_hourly["time_utc"].dt.time

    # Group by half-hour-of-day and average energy
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

