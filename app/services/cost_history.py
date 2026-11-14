"""Cost history: what the kit saved, split by what did the saving.

Four cost layers per half-hour, each priced at the tariff actually in force:

    no kit      everything the house used, bought at the import rate
    solar only  PV offsets load first, surplus exported, shortfall imported
    self-use    solar, plus a battery that shifts PV only - never grid-charges,
                never exports from the battery. This is what a "dumb" install
                does, and it is the honest baseline for the optimiser.
    actual      what actually happened (meter where available)

Attribution:
    solar_value     = no kit     - solar only
    battery_value   = solar only - self-use
    optimiser_value = self-use   - actual
    total_value     = no kit     - actual        (= the three above, by construction)

Every layer carries the standing charge, so it cancels inside each subtraction
and never inflates a "saving". It is stored so "what you would have paid" reads
like a real bill.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.tariff import cosy_prices, normalise_tariff

# Matches app/core/optimiser.py: empirically fitted on this hardware.
CHARGE_EFFICIENCY = 0.95
DISCHARGE_EFFICIENCY = 0.95

DEFAULT_BATTERY = {
    "capacity_kwh": 5.0,
    "max_charge_kw": 3.0,
    "max_discharge_kw": 3.0,
    "min_soc_pct": 20.0,
    "max_soc_pct": 100.0,
}


# ---------------------------------------------------------------- tariff history
def get_tariff_periods(site_id: str) -> list[dict]:
    """Tariff periods for a site, oldest first. Falls back to the current tariff."""
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                """SELECT valid_from, valid_to, import_type, import_config,
                          export_type, export_config
                   FROM site_tariff_history
                   WHERE site_id = :sid ORDER BY valid_from"""
            ),
            {"sid": site_id},
        ).mappings().all()
        periods = [dict(r) for r in rows]

        if not periods:
            current = session.execute(
                text("SELECT import_type, export_type, config_json FROM tariffs WHERE site_id = :sid LIMIT 1"),
                {"sid": site_id},
            ).mappings().first()
            if current:
                cfg = current["config_json"] or {}
                if isinstance(cfg, str):
                    import json

                    cfg = json.loads(cfg)
                periods = [{
                    "valid_from": datetime(1970, 1, 1, tzinfo=timezone.utc),
                    "valid_to": None,
                    "import_type": current["import_type"],
                    "import_config": cfg.get("import") or {},
                    "export_type": current["export_type"],
                    "export_config": cfg.get("export") or {},
                }]
    finally:
        session.close()
    return periods


def tariff_label(period: dict) -> str:
    """Human label for a tariff period, e.g. "Agile · Outgoing 12p"."""
    imp = (period.get("import_type") or "").title() or "Unknown"
    if (period.get("export_type") or "") == "fixed":
        pence = (period.get("export_config") or {}).get("flat_pence")
        exp = f"Outgoing {float(pence):g}p" if pence is not None else "Outgoing fixed"
    else:
        exp = "Agile Outgoing"
    return f"{imp} · {exp}"


def label_for_day(periods: list[dict], day: date) -> str | None:
    """The tariff label in force at midday on ``day`` (stable across DST)."""
    at = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    chosen = None
    for p in periods:
        if p["valid_from"] <= at:
            chosen = p
    return tariff_label(chosen) if chosen else None


def _period_tariff(period: dict) -> dict:
    """Shape a history row into the dict ``resolve_prices``/``cosy_prices`` expect."""
    return normalise_tariff({
        "import_type": period["import_type"],
        "export_type": period["export_type"],
        "config_json": {
            "import": period.get("import_config") or {},
            "export": period.get("export_config") or {},
        },
    })


def resolve_rates(site_id: str, slots: pd.DatetimeIndex) -> pd.DataFrame:
    """Import/export pence per slot, plus the standing charge for each day.

    Slots outside every recorded period fall back to the earliest period, which
    is the common case for the first day of a new install.
    """
    periods = get_tariff_periods(site_id)
    out = pd.DataFrame(
        {"import_pence": 0.0, "export_pence": 0.0},
        index=slots,
    )
    if not periods:
        return out

    session = SessionLocal()
    try:
        agile = session.execute(
            text(
                """SELECT period_end, import_price, export_price FROM agile_rates
                   WHERE period_end >= :start AND period_end <= :end"""
            ),
            {"start": slots.min().to_pydatetime(), "end": (slots.max() + timedelta(hours=1)).to_pydatetime()},
        ).mappings().all()
    finally:
        session.close()

    agile_map = {}
    for r in agile:
        pe = r["period_end"]
        if pe.tzinfo is None:
            pe = pe.replace(tzinfo=timezone.utc)
        agile_map[pe] = (r["import_price"], r["export_price"])

    # assign each slot to a period
    bounds = [p["valid_from"] for p in periods]
    for i, slot in enumerate(slots):
        # last period that starts at or before this slot
        idx = 0
        for j, b in enumerate(bounds):
            if b <= slot:
                idx = j
        period = periods[idx]
        tariff = _period_tariff(period)
        pe = slot + timedelta(minutes=30)

        if tariff["import_type"] == "cosy":
            imp = float(cosy_prices(pd.Series([pe]), tariff).iloc[0])
        elif tariff["import_type"] == "fixed":
            imp = tariff["import"]["flat_pence"]
        else:
            pair = agile_map.get(pe)
            imp = pair[0] if pair and pair[0] is not None else tariff["import"]["flat_pence"]

        if tariff["export_type"] == "fixed":
            exp = tariff["export"]["flat_pence"]
        else:
            pair = agile_map.get(pe)
            exp = pair[1] if pair and pair[1] is not None else tariff["export"]["flat_pence"]

        out.iat[i, 0] = float(imp)
        out.iat[i, 1] = float(exp)
    return out


def standing_pence_for(site_id: str, day: date) -> float:
    """Daily standing charge for the tariff in force on ``day`` (0 when unknown)."""
    periods = get_tariff_periods(site_id)
    at = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    chosen = None
    for p in periods:
        if p["valid_from"] <= at:
            chosen = p
    if not chosen:
        return 0.0
    cfg = chosen.get("import_config") or {}
    try:
        return float(cfg.get("standing_pence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- actuals
def load_series(site_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Half-hourly load/PV/SOC plus metered import/export where the site has a meter."""
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                """
                WITH s AS (
                  SELECT variable, period_end, value,
                         date_trunc('hour', period_end)
                           + CASE WHEN extract(minute FROM period_end) >= 30
                                  THEN interval '30 min' ELSE interval '0 min' END AS slot,
                         least(extract(epoch FROM (
                             lead(period_end) OVER (PARTITION BY variable ORDER BY period_end)
                             - period_end)) / 3600.0, 5.0/60.0) AS dt_h
                  FROM historic_energy_data
                  WHERE site_id = :sid AND period_end >= :start AND period_end < :end
                    AND variable IN ('pvPower','loadsPower','gridConsumptionPower','feedinPower','SoC')
                ), e AS (
                  SELECT variable, slot, sum(value * coalesce(dt_h, 0.0833)) AS kwh, avg(value) AS avg_v
                  FROM s GROUP BY 1, 2
                )
                SELECT slot,
                       coalesce(max(CASE WHEN variable='pvPower' THEN kwh END), 0) AS pv_kwh,
                       coalesce(max(CASE WHEN variable='loadsPower' THEN kwh END), 0) AS load_kwh,
                       coalesce(max(CASE WHEN variable='gridConsumptionPower' THEN kwh END), 0) AS fox_import_kwh,
                       coalesce(max(CASE WHEN variable='feedinPower' THEN kwh END), 0) AS fox_export_kwh,
                       max(CASE WHEN variable='SoC' THEN avg_v END) AS soc_pct,
                       count(*) AS variables
                FROM e GROUP BY slot ORDER BY slot
                """
            ),
            {"sid": site_id, "start": start, "end": end},
        ).mappings().all()
    finally:
        session.close()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["slot"] = pd.to_datetime(df["slot"], utc=True)
    return df.set_index("slot")


# ---------------------------------------------------------------- simulation
def simulate_selfuse(
    pv_kwh: pd.Series,
    load_kwh: pd.Series,
    battery: dict | None = None,
    start_soc_pct: float = 50.0,
    dt_hours: float = 0.5,
) -> pd.DataFrame:
    """A battery that only ever shifts PV: charges from surplus, covers deficit.

    No grid charging and no battery-to-grid export - that is what separates this
    baseline from the optimiser, and it is what a default install does.
    """
    b = {**DEFAULT_BATTERY, **(battery or {})}
    cap = float(b["capacity_kwh"])
    min_kwh = cap * float(b["min_soc_pct"]) / 100.0
    max_kwh = cap * float(b["max_soc_pct"]) / 100.0
    max_charge = float(b["max_charge_kw"]) * dt_hours
    max_discharge = float(b["max_discharge_kw"]) * dt_hours

    soc = min(max(cap * start_soc_pct / 100.0, min_kwh), max_kwh)
    imp, exp, socs = [], [], []

    for pv, load in zip(pv_kwh, load_kwh):
        surplus = float(pv) - float(load)
        if surplus > 0:
            headroom = (max_kwh - soc) / DISCHARGE_EFFICIENCY
            charge = min(surplus, max_charge, headroom)
            charge = max(0.0, charge)
            soc += charge * CHARGE_EFFICIENCY
            imp.append(0.0)
            exp.append(surplus - charge)
        else:
            deficit = -surplus
            available = max(0.0, soc - min_kwh) * DISCHARGE_EFFICIENCY
            discharge = min(deficit, max_discharge, available)
            soc -= discharge / DISCHARGE_EFFICIENCY
            imp.append(deficit - discharge)
            exp.append(0.0)
        socs.append(soc)

    return pd.DataFrame({"self_import_kwh": imp, "self_export_kwh": exp, "self_soc_kwh": socs},
                        index=pv_kwh.index)


# ---------------------------------------------------------------- layers
def compute_days(site_id: str, start: datetime, end: datetime, battery: dict | None = None,
                 meter: dict | None = None) -> pd.DataFrame:
    """Return one row per local day with every layer costed.

    ``meter`` optionally supplies {'import': {slot: kwh}, 'export': {slot: kwh}} from
    the supplier's half-hourly readings; FoxESS is the fallback.
    """
    df = load_series(site_id, start, end)
    if df.empty:
        return df

    rates = resolve_rates(site_id, df.index)
    df = df.join(rates)

    sim = simulate_selfuse(df["pv_kwh"], df["load_kwh"], battery)
    df = df.join(sim)

    if meter:
        imp = pd.Series(meter.get("import", {}))
        exp = pd.Series(meter.get("export", {}))
        df["meter_import_kwh"] = imp.reindex(df.index)
        df["meter_export_kwh"] = exp.reindex(df.index)
    else:
        df["meter_import_kwh"] = pd.NA
        df["meter_export_kwh"] = pd.NA

    # actual side: meter wins, FoxESS fills the gaps
    df["actual_import_kwh"] = df["meter_import_kwh"].fillna(df["fox_import_kwh"])
    df["actual_export_kwh"] = df["meter_export_kwh"].fillna(df["fox_export_kwh"])

    # costs, all inc VAT, pence -> GBP
    df["actual_cost"] = (df["actual_import_kwh"] * df["import_pence"]
                         - df["actual_export_kwh"] * df["export_pence"]) / 100.0
    df["nokit_cost"] = df["load_kwh"] * df["import_pence"] / 100.0
    surplus = (df["pv_kwh"] - df["load_kwh"]).clip(lower=0)
    deficit = (df["load_kwh"] - df["pv_kwh"]).clip(lower=0)
    df["solar_only_cost"] = (deficit * df["import_pence"] - surplus * df["export_pence"]) / 100.0
    df["selfuse_cost"] = (df["self_import_kwh"] * df["import_pence"]
                          - df["self_export_kwh"] * df["export_pence"]) / 100.0

    df["day"] = df.index.tz_convert("Europe/London").date

    rows = []
    for day, g in df.groupby("day"):
        stand = standing_pence_for(site_id, day) / 100.0
        nokit = g["nokit_cost"].sum() + stand
        solar_only = g["solar_only_cost"].sum() + stand
        selfuse = g["selfuse_cost"].sum() + stand
        actual = g["actual_cost"].sum() + stand
        rows.append({
            "day": day,
            "import_kwh": float(g["actual_import_kwh"].sum()),
            "export_kwh": float(g["actual_export_kwh"].sum()),
            "pv_kwh": float(g["pv_kwh"].sum()),
            "load_kwh": float(g["load_kwh"].sum()),
            "import_cost_gbp": float((g["actual_import_kwh"] * g["import_pence"] / 100).sum()),
            "export_income_gbp": float((g["actual_export_kwh"] * g["export_pence"] / 100).sum()),
            "standing_gbp": stand,
            "net_cost_gbp": actual,
            "nokit_cost_gbp": nokit,
            "solar_only_cost_gbp": solar_only,
            "selfuse_cost_gbp": selfuse,
            "solar_value_gbp": nokit - solar_only,
            "battery_value_gbp": solar_only - selfuse,
            "optimiser_value_gbp": selfuse - actual,
            "total_value_gbp": nokit - actual,
            "soc_min_pct": float(g["soc_pct"].min()) if g["soc_pct"].notna().any() else None,
            "soc_max_pct": float(g["soc_pct"].max()) if g["soc_pct"].notna().any() else None,
            "covered_slots": int(len(g)),
            "expected_slots": expected_slots_for(day),
            "source": "octopus+foxess" if meter else "foxess",
        })
    return pd.DataFrame(rows)


def expected_slots_for(day: date) -> int:
    """Half-hours in this local day: 46 in spring, 50 in autumn, 48 otherwise."""
    start = pd.Timestamp(day, tz="Europe/London")
    end = pd.Timestamp(day + timedelta(days=1), tz="Europe/London")
    return int((end - start).total_seconds() // 1800)


def _is_dst_day(day: date) -> bool:
    """True on the two days a year that are not 48 half-hours long."""
    return expected_slots_for(day) != 48


def upsert_days(site_id: str, days: pd.DataFrame) -> int:
    if days is None or days.empty:
        return 0
    cols = ["day", "import_kwh", "export_kwh", "pv_kwh", "load_kwh", "import_cost_gbp",
            "export_income_gbp", "standing_gbp", "net_cost_gbp", "nokit_cost_gbp",
            "solar_only_cost_gbp", "selfuse_cost_gbp", "solar_value_gbp", "battery_value_gbp",
            "optimiser_value_gbp", "total_value_gbp", "soc_min_pct", "soc_max_pct",
            "covered_slots", "expected_slots", "source"]
    payload = []
    for _, r in days.iterrows():
        rec = {c: (None if pd.isna(r[c]) else (r[c].item() if hasattr(r[c], "item") else r[c])) for c in cols}
        rec["site_id"] = site_id
        payload.append(rec)

    session = SessionLocal()
    try:
        session.execute(
            text(
                f"""INSERT INTO daily_cost_summary ({', '.join(payload[0].keys())})
                    VALUES ({', '.join(':' + k for k in payload[0])})
                    ON CONFLICT (site_id, day) DO UPDATE SET
                      {', '.join(f'{c} = EXCLUDED.{c}' for c in cols if c != 'day')},
                      computed_at = now()"""
            ),
            payload,
        )
        session.commit()
    finally:
        session.close()
    return len(payload)


# ---------------------------------------------------------------- read side
def summary(site_id: str, since: date | None = None) -> dict:
    """Aggregate the daily rows. Returns zeros rather than raising on no data."""
    session = SessionLocal()
    try:
        row = session.execute(
            text(
                """SELECT count(*) AS days,
                          coalesce(sum(import_kwh),0) AS import_kwh,
                          coalesce(sum(export_kwh),0) AS export_kwh,
                          coalesce(sum(pv_kwh),0) AS pv_kwh,
                          coalesce(sum(load_kwh),0) AS load_kwh,
                          coalesce(sum(import_cost_gbp),0) AS import_cost_gbp,
                          coalesce(sum(export_income_gbp),0) AS export_income_gbp,
                          coalesce(sum(standing_gbp),0) AS standing_gbp,
                          coalesce(sum(net_cost_gbp),0) AS net_cost_gbp,
                          coalesce(sum(nokit_cost_gbp),0) AS nokit_cost_gbp,
                          coalesce(sum(solar_only_cost_gbp),0) AS solar_only_cost_gbp,
                          coalesce(sum(selfuse_cost_gbp),0) AS selfuse_cost_gbp,
                          coalesce(sum(solar_value_gbp),0) AS solar_value_gbp,
                          coalesce(sum(battery_value_gbp),0) AS battery_value_gbp,
                          coalesce(sum(optimiser_value_gbp),0) AS optimiser_value_gbp,
                          coalesce(sum(total_value_gbp),0) AS total_value_gbp,
                          coalesce(sum(covered_slots),0) AS covered_slots,
                          coalesce(sum(expected_slots),0) AS expected_slots,
                          min(day) AS first_day, max(day) AS last_day
                   FROM daily_cost_summary
                   WHERE site_id = :sid AND (:since IS NULL OR day >= :since)"""
            ),
            {"sid": site_id, "since": since},
        ).mappings().first()
    finally:
        session.close()

    out = dict(row) if row else {}
    for k, v in list(out.items()):
        if v is not None and k not in ("days", "covered_slots", "expected_slots", "first_day", "last_day"):
            # round and normalise -0.0 (a layer can legitimately be a tiny negative)
            out[k] = round(float(v), 2) + 0.0
    out["coverage_pct"] = (round(100.0 * out.get("covered_slots", 0) / out["expected_slots"], 1)
                           if out.get("expected_slots") else None)
    out["first_day"] = out["first_day"].isoformat() if out.get("first_day") else None
    out["last_day"] = out["last_day"].isoformat() if out.get("last_day") else None
    return out
