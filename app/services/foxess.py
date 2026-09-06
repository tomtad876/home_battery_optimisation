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


# --- v3 classifier and push (for background/manual schedule push) ---

FOXESS_MODE_SELF_USE = "SelfUse"
FOXESS_MODE_FORCE_CHARGE = "ForceCharge"
FOXESS_MODE_FORCE_DISCHARGE = "ForceDischarge"
FOXESS_MODE_FEEDIN = "Feedin"

_MODE_MAP = {
    0: FOXESS_MODE_SELF_USE,
    1: FOXESS_MODE_FORCE_CHARGE,
    2: FOXESS_MODE_FORCE_DISCHARGE,
}


def classify_optimiser_output(
    result_df: pd.DataFrame,
    threshold: float = 0.05,
    from_time: datetime | None = None,
    min_soc_pct: float = 10.0,
    max_soc_pct: float = 100.0,
    rated_power_w: float = 3000.0,
    local_tz: str = "Europe/London",
) -> list[dict]:
    """Classify optimiser output into FoxESS v3 schedule groups.

    Maps each half-hour slot to a work mode based on net battery flow,
    groups consecutive same-mode slots, and returns v3 period dicts.

    The FoxESS device operates in local time, so all period times are
    converted from UTC to local_tz before extracting hours/minutes.

    Returns a list of FoxESS v3 period dicts ready for set_schedule().
    """
    import zoneinfo
    tz = zoneinfo.ZoneInfo(local_tz)

    df = result_df.copy()

    # Default missing grid columns to 0 (tests / older callers may omit them)
    for col in ("grid_import_kwh", "grid_export_kwh"):
        if col not in df.columns:
            df[col] = 0.0

    if from_time is not None:
        if "period_end" in df.columns:
            # Only keep slots whose START time is in the future (not just period_end)
            start_cutoff = pd.Timestamp(from_time) + timedelta(minutes=30)
            df = df[pd.to_datetime(df["period_end"], utc=True) > start_cutoff].reset_index(drop=True)

    if df.empty:
        return []

    # Classify each slot.
    # The key refinement: a positive net battery flow only needs ForceCharge
    # when it pulls from the grid. If the charge is covered by solar surplus
    # (no grid import), SelfUse handles it naturally. Similarly, a negative
    # net flow only needs ForceDischarge when it's exporting to the grid —
    # if it's just covering home demand, SelfUse is the right mode.
    def _classify(row):
        net = row.get("net_battery_kwh", 0)
        export = row.get("grid_export_kwh", 0)
        import_kwh = row.get("grid_import_kwh", 0)
        price = row.get("price", 0)
        if net > threshold:
            # Charging — from grid (needs ForceCharge) or solar surplus (SelfUse)?
            if import_kwh > threshold:
                return FOXESS_MODE_FORCE_CHARGE
            return FOXESS_MODE_SELF_USE
        if net < -threshold:
            # Discharging — exporting to grid (ForceDischarge) or covering demand (SelfUse)?
            if export > threshold:
                return FOXESS_MODE_FORCE_DISCHARGE
            return FOXESS_MODE_SELF_USE
        # Net near zero — battery idle, but solar exporting to grid
        if export > threshold:
            # During negative prices, prefer ForceCharge over Feedin —
            # we're being paid to charge, so keep the battery topped up.
            if price < 0:
                return FOXESS_MODE_FORCE_CHARGE
            return FOXESS_MODE_FEEDIN
        return FOXESS_MODE_SELF_USE

    df["mode"] = df.apply(_classify, axis=1)

    # Group consecutive same-mode slots
    df["mode_group"] = (df["mode"] != df["mode"].shift()).cumsum()

    groups = []
    for _, grp in df.groupby("mode_group"):
        mode = grp.iloc[0]["mode"]
        start_row = grp.iloc[0]
        end_row = grp.iloc[-1]

        # Convert from UTC to local time for FoxESS device
        start_utc = pd.to_datetime(start_row["period_end"], utc=True) - timedelta(minutes=30)
        end_utc = pd.to_datetime(end_row["period_end"], utc=True)
        start_local = start_utc.to_pydatetime().astimezone(tz)
        end_local = end_utc.to_pydatetime().astimezone(tz)

        duration_h = len(grp) * 0.5

        # Per-group force params: size the charge/discharge to what the
        # optimiser actually scheduled, instead of blasting full power and
        # charging to 100% / draining to min SOC.
        grp_min_soc = min_soc_pct
        grp_max_soc = max_soc_pct
        grp_power = rated_power_w
        if mode == FOXESS_MODE_FORCE_CHARGE and "soc_pct" in grp.columns:
            # maxSoc = highest SOC this charge period reaches (rounded up 5%)
            grp_max_soc = min(max_soc_pct, _round_soc_up(grp["soc_pct"].max()))
            # Power = energy to move / time available, rounded up to 100W
            energy = grp["net_battery_kwh"].sum()
            grp_power = _round_power_w(energy / duration_h)
        elif mode == FOXESS_MODE_FORCE_DISCHARGE and "soc_pct" in grp.columns:
            # fdSoc = lowest SOC reached in this period (rounded DOWN 5%) so
            # we keep reserve for SelfUse after the forced discharge ends
            grp_min_soc = max(min_soc_pct, _round_soc_down(grp["soc_pct"].min()))
            energy = (-grp["net_battery_kwh"]).sum()
            grp_power = _round_power_w(energy / duration_h)

        # Build v3 period dict directly (no foxesscloud dependency)
        period = _build_v3_period(
            start_local, end_local, mode,
            min_soc_pct=grp_min_soc,
            max_soc_pct=grp_max_soc,
            rated_power_w=grp_power,
        )
        groups.append(period)

    return groups


def get_device_remain_mode(api_key: str, device_sn: str) -> str | None:
    """Query the device's default (remain) mode.

    The remain mode is the mode the inverter uses in unscheduled time slots.
    It appears in the schedule as a 00:00-23:59 group with isRemainMode=True.
    Returns None if it can't be determined.
    """
    try:
        init_api(api_key)
        f.device_sn = device_sn
        sched = f.get_schedule(filter=0)
        if not sched:
            return None
        for p in sched.get("periods", []):
            if p.get("isRemainMode"):
                return p.get("workMode")
        return None
    except Exception:
        return None


def split_groups_at_midnight(groups: list[dict]) -> list[dict]:
    """Split any group that spans midnight into two groups (one per day).

    FoxESS does not accept a single schedule period that crosses 00:00.
    A group whose end time is earlier (in wall-clock terms) than its start
    time spans midnight and must be split.
    """
    out = []
    for g in groups:
        start_m = g["startHour"] * 60 + g["startMinute"]
        end_m = g["endHour"] * 60 + g["endMinute"]
        if end_m <= start_m:
            # Spans midnight: split at 23:59 of the first day / 00:00 of the next
            first = {**g, "endHour": 23, "endMinute": 59}
            second = {**g, "startHour": 0, "startMinute": 0}
            out.append(first)
            out.append(second)
        else:
            out.append(g)
    return out


def _round_soc_up(v: float) -> int:
    """Round a SOC % up to the nearest 5% (capped 0-100)."""
    import math
    return min(100, max(0, int(math.ceil(v / 5.0) * 5)))


def _round_soc_down(v: float) -> int:
    """Round a SOC % down to the nearest 5% (capped 0-100)."""
    import math
    return min(100, max(0, int(math.floor(v / 5.0) * 5)))


def _round_power_w(kw: float) -> int:
    """Round a kW value up to the nearest 100W, minimum 100W."""
    import math
    return max(100, int(math.ceil(kw * 1000 / 100.0) * 100))


def _build_v3_period(
    start_dt: datetime,
    end_dt: datetime,
    mode: str,
    min_soc_pct: float = 10.0,
    max_soc_pct: float = 100.0,
    rated_power_w: float = 3000.0,
) -> dict:
    """Build a FoxESS v3 schedule period dict."""
    min_soc = round(min_soc_pct)
    period: dict = {
        "startHour": start_dt.hour,
        "startMinute": start_dt.minute,
        "endHour": end_dt.hour,
        "endMinute": end_dt.minute,
        "workMode": mode,
        "isRemainMode": False,
        "extraParam": {"minSocOnGrid": min_soc},
    }

    if mode == FOXESS_MODE_FORCE_CHARGE:
        period["extraParam"]["maxSoc"] = round(max_soc_pct)
        period["extraParam"]["fdSoc"] = min_soc
        period["extraParam"]["fdPwr"] = int(rated_power_w)
    elif mode == FOXESS_MODE_FORCE_DISCHARGE:
        period["extraParam"]["fdSoc"] = min_soc
        period["extraParam"]["fdPwr"] = int(rated_power_w)

    return period


def classify_and_push(
    api_key: str,
    device_sn: str,
    result_df: pd.DataFrame,
    capacity_kwh: float = 15.0,
    min_soc_pct: float = 20.0,
    max_soc_pct: float = 90.0,
    rated_power_w: float = 3000.0,
    from_time: datetime | None = None,
) -> dict:
    """Full push sequence: init API → classify → push to device.

    Reads the device's remain (default) mode and drops any classified groups
    that match it — those instructions are redundant since the inverter
    already falls back to that mode in unscheduled gaps.

    Returns {pushed: bool, groups_sent: int, provider_response: any, error?: str}.
    """
    try:
        init_api(api_key)
        f.device_sn = device_sn

        # Get device schedule info (maxGroupCount, supported modes)
        info = f.get_flag()
        if info is None:
            return {"pushed": False, "groups_sent": 0, "provider_response": None, "error": "Failed to get device schedule info"}

        max_groups = f.max_periods or 8

        # Classify
        groups = classify_optimiser_output(
            result_df,
            threshold=0.05,
            from_time=from_time,
            min_soc_pct=min_soc_pct,
            max_soc_pct=max_soc_pct,
            rated_power_w=rated_power_w,
        )

        if not groups:
            return {"pushed": False, "groups_sent": 0, "provider_response": None, "error": "No schedule groups to push"}

        # Drop groups matching the device's remain mode (redundant — the
        # inverter already defaults to that mode in unscheduled gaps).
        remain_mode = get_device_remain_mode(api_key, device_sn)
        if remain_mode:
            groups = [g for g in groups if g.get("workMode") != remain_mode]

        # Split any group that spans midnight (FoxESS rejects cross-midnight periods)
        groups = split_groups_at_midnight(groups)

        if not groups:
            return {"pushed": False, "groups_sent": 0, "provider_response": None, "error": "No schedule groups to push after filtering"}

        # Merge if over device limit
        if len(groups) > max_groups:
            groups = _merge_groups(groups, max_groups)

        # Push via foxesscloud library
        response = f.set_schedule(periods=groups, enable=True)

        return {
            "pushed": response is not None,
            "groups_sent": len(groups),
            "provider_response": response,
            "remain_mode": remain_mode,
        }
    except Exception as e:
        return {"pushed": False, "groups_sent": 0, "provider_response": None, "error": str(e)}


def _merge_groups(groups: list[dict], max_groups: int) -> list[dict]:
    """Merge groups down to fit within device limit.

    Prefers absorbing SelfUse groups into neighbours.
    """
    if len(groups) <= max_groups:
        return groups

    merged = list(groups)

    while len(merged) > max_groups:
        # Find best candidate: SelfUse first, otherwise shortest
        best_idx = 0
        best_score = float("inf")
        for i, g in enumerate(merged):
            is_self_use = 0 if g.get("workMode") == FOXESS_MODE_SELF_USE else 100
            score = is_self_use + i  # prefer earlier groups if tied
            if score < best_score:
                best_score = score
                best_idx = i

        # Merge into larger neighbour
        target = best_idx - 1 if best_idx > 0 else best_idx + 1
        if target < 0 or target >= len(merged):
            break

        # Extend target's end time to cover merged group
        merged[target]["endHour"] = merged[best_idx]["endHour"]
        merged[target]["endMinute"] = merged[best_idx]["endMinute"]
        merged.pop(best_idx)

    return merged

