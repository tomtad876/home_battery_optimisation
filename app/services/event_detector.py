"""Event detection for the demand-events review queue.

Re-implements the floor-baseline residual detection from the analysis phase:
compute the 10th-percentile "always-on" floor per 5-min-of-day slot over the
last ~30 days, then flag sustained runs above floor+1kW as candidate appliance
events. Each candidate gets a suggested label from a flatness heuristic
(resistive vs duty-cycled) that Tom confirms/corrects in the UI.

Candidates already covered by an existing demand_events row (confirmed or
rejected) are dropped, so the review queue only ever shows genuinely new events.
Each candidate also carries a small `trace` of the load around it, so the UI can
render a sparkline without a second round-trip.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text

from app.core.database import SessionLocal

LONDON = ZoneInfo("Europe/London")

THRESHOLD_KW = 1.0
MIN_SAMPLES = 3  # 15 minutes at 5-min resolution
BASELINE_DAYS = 30
TRACE_PAD_SAMPLES = 6  # ±30 min around each event for the sparkline


def _suggest(hod: float, mean_kw: float, peak_kw: float, flatness: float,
             dur_min: int) -> tuple[str, float]:
    """Suggest an appliance label + rough confidence (0..1).

    Deliberately caps confidence at 0.6: the previous heuristic emitted 0.90 for
    "flat overnight = cosy", but those runs are the heat pump's *space-heating*
    mode (the Cosy and the heating are the same appliance — mutually exclusive
    modes of one heat pump), so the confident suggestions were the wrong ones.
    Nothing here is reliable enough to call "confident" until templates are fit
    from clean (isolated) labels — the UI treats <0.7 as a guess.

    Cooking is split only as far as the meter can actually support it:
    duration separates the oven (long/sustained), peak separates the hob
    (multi-ring, >=2.5 kW); a short low-power event is genuinely ambiguous
    between a single hob ring and an air fryer, so it stays "cooking".
    """
    # Evening meal prep (Tom's data: 17:30-19:00, 15-30 min, peaks 2.3-3.5 kW).
    if 17 <= hod <= 20.5 and mean_kw >= 1.2:
        if dur_min >= 45:
            return ("oven", 0.50)   # long sustained draw = oven
        if peak_kw >= 2.5:
            return ("hob", 0.50)    # multi-ring / boiling
        return ("cooking", 0.40)    # short + low power: hob ring vs air fryer

    if flatness < 0.2:  # steady/resistive → heat pump (either mode)
        if dur_min >= 90 or (mean_kw >= 2.5 and dur_min >= 45):
            return ("heating", 0.55)  # long steady run = space heating
        if 10 <= hod <= 15:
            # Genuine midday DHW runs ~30+ min; a short midday flat burst is
            # more likely a hob/air fryer (Tom labelled exactly that, 2026-09-21).
            if dur_min >= 25:
                return ("cosy", 0.55)
            return ("cooking", 0.40)
        if hod <= 6:
            return ("cosy", 0.50)  # overnight DHW — genuinely ambiguous w/ heating
        return ("cosy" if mean_kw < 2.5 else "heating", 0.45)

    # duty-cycled daytime = laundry / dishwasher
    if 10 <= hod <= 16:
        return ("washing_machine", 0.40)
    return ("dishwasher", 0.40)


def _overlap_fraction(a0, a1, b0, b1) -> float:
    """Fraction of [a0,a1] covered by [b0,b1] (both tz-aware datetimes)."""
    if a1 <= b0 or b1 <= a0:
        return 0.0
    overlap = min(a1, b1) - max(a0, b0)
    return overlap.total_seconds() / (a1 - a0).total_seconds()


def detect_events(site_id: str, days: int = 7) -> list[dict]:
    """Return candidate events for the last `days` days (detected, unlabelled).

    Returns a list of dicts with tz-aware UTC `start_time`/`end_time` ISO strings
    plus display fields (`start_local`, `dur_min`, `peak_kw`, `mean_kw`,
    `flatness`, `energy_kwh`, `suggested_appliance`, `confidence`, `trace`).
    """
    session = SessionLocal()
    try:
        # Baseline window: last 30 days (period_end is stored naive-local).
        cutoff = (datetime.now(LONDON) - timedelta(days=BASELINE_DAYS)).replace(tzinfo=None)
        df = pd.read_sql_query(
            text("""
                SELECT period_end AS t, value AS kw
                FROM historic_energy_data
                WHERE variable='loadsPower' AND site_id = :sid AND period_end >= :cutoff
                ORDER BY t
            """),
            session.bind,
            params={"sid": site_id, "cutoff": cutoff},
        )

        report_start_local = (datetime.now(LONDON) - timedelta(days=days)).replace(tzinfo=None)
        existing = pd.read_sql_query(
            text("""
                SELECT start_time, end_time FROM demand_events
                WHERE site_id = :sid AND start_time >= :since
            """),
            session.bind,
            params={
                "sid": site_id,
                "since": report_start_local.replace(tzinfo=LONDON).astimezone(timezone.utc),
            },
        )
    finally:
        session.close()

    if df.empty:
        return []

    df["t"] = pd.to_datetime(df["t"])
    df["slot"] = df["t"].dt.hour * 12 + (df["t"].dt.minute // 5)
    floor = df.groupby("slot")["kw"].quantile(0.10)
    df["floor"] = df["slot"].map(floor)
    df["resid"] = df["kw"] - df["floor"]

    report_cutoff = df["t"].max() - pd.Timedelta(days=days)
    df = df[df["t"] >= report_cutoff].reset_index(drop=True)

    # Existing events as UTC datetimes (for overlap filtering).
    existing_spans = []
    if not existing.empty:
        for _, row in existing.iterrows():
            s = pd.to_datetime(row["start_time"])
            e = pd.to_datetime(row["end_time"])
            if pd.isna(s):
                continue
            if pd.isna(e):
                e = s + pd.Timedelta(minutes=30)
            existing_spans.append((s.to_pydatetime(), e.to_pydatetime()))

    ev = (df["resid"] > THRESHOLD_KW).astype(int)
    grp = (ev.diff() != 0).cumsum()
    events = []
    for _, sub in df[ev == 1].groupby(grp[ev == 1]):
        if len(sub) < MIN_SAMPLES:
            continue
        i0 = sub.index[0]
        i1 = sub.index[-1]
        kw = sub["kw"]
        mean_kw = float(kw.mean())
        flatness = float(kw.std() / mean_kw) if mean_kw > 0 else 0.0
        hod = sub["t"].dt.hour.iloc[0] + sub["t"].dt.minute.iloc[0] / 60
        start_local = sub["t"].min()
        end_local = sub["t"].max() + pd.Timedelta(minutes=5)
        start_dt = start_local.tz_localize(LONDON).astimezone(timezone.utc)
        end_dt = end_local.tz_localize(LONDON).astimezone(timezone.utc)

        # Skip if already covered by an existing (labelled) event.
        if any(_overlap_fraction(start_dt, end_dt, s, e) > 0.5 for s, e in existing_spans):
            continue

        # Sparkline window: the event ± 30 minutes.
        win = df.iloc[max(0, i0 - TRACE_PAD_SAMPLES):i1 + TRACE_PAD_SAMPLES + 1]
        trace = [
            {"t": t.tz_localize(LONDON).astimezone(timezone.utc).isoformat(), "kw": round(float(k), 2)}
            for t, k in zip(win["t"], win["kw"])
        ]

        dur_min = int(len(sub) * 5)
        suggested, confidence = _suggest(hod, mean_kw, float(kw.max()), flatness, dur_min)
        events.append({
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "start_local": start_local.strftime("%Y-%m-%d %H:%M"),
            "end_local": end_local.strftime("%H:%M"),
            "dur_min": dur_min,
            "peak_kw": round(float(kw.max()), 2),
            "mean_kw": round(mean_kw, 2),
            "flatness": round(flatness, 2),
            "energy_kwh": round(float(kw.sum()) * 5 / 60, 3),
            "suggested_appliance": suggested,
            "confidence": round(confidence, 2),
            "trace": trace,
        })

    events.sort(key=lambda e: e["start_time"])
    return events
