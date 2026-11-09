from datetime import datetime, timedelta, timezone

import pandas as pd

from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.encryption import encrypt_provider_config, decrypt_provider_config
from app.services.tariff import get_active_tariff, resolve_prices


# Fallback energy (kWh) per appliance for a planned event that has no
# `energy_kwh` set. Only seeds the holiday forecast; a measured/entered value
# always wins. Kept deliberately rough — these are the appliances Tom can
# schedule while away, and the Cosy is the one that matters.
PLANNED_EVENT_FALLBACK_KWH = {
    "cosy": 0.8,
    "washing_machine": 0.7,
    "dishwasher": 0.9,
    "tumble_dryer": 1.5,
    "oven": 1.8,
    "hob": 0.6,
    "airfryer": 0.4,
    "heating": 1.0,
}
DEFAULT_EVENT_FALLBACK_KWH = 0.5
HORIZON_HOURS = 48


def _holiday_active(session, site_id: str) -> bool:
    """True if holiday mode is on for the site and hasn't auto-expired."""
    row = session.execute(
        text("SELECT holiday_mode, holiday_until FROM sites WHERE id = :sid"),
        {"sid": site_id},
    ).mappings().first()
    if not row or not row["holiday_mode"]:
        return False
    until = row["holiday_until"]
    if until is not None and datetime.now(timezone.utc) > until:
        return False
    return True


def _add_planned_events(df: pd.DataFrame, session, site_id: str, now: datetime) -> None:
    """Add explicitly scheduled (status='planned') events to `df['demand']`, in place.

    Each event's energy is spread evenly across the half-hour slots its window
    overlaps. Only called in holiday mode: in normal mode the learned 7-day
    average already contains the routine, so injecting the same event again
    would double-count it.
    """
    horizon_end = now + timedelta(hours=HORIZON_HOURS)
    rows = session.execute(text("""
        SELECT appliance, start_time, end_time, energy_kwh
        FROM demand_events
        WHERE site_id = :sid
          AND status = 'planned'
          AND start_time < :hend
          AND COALESCE(end_time, start_time + interval '30 minutes') > :nstart
    """), {"sid": site_id, "hend": horizon_end, "nstart": now}).mappings().all()

    for e in rows:
        start = e["start_time"]
        end = e["end_time"] or (start + timedelta(minutes=30))
        energy = e["energy_kwh"]
        if energy is None:
            energy = PLANNED_EVENT_FALLBACK_KWH.get(e["appliance"], DEFAULT_EVENT_FALLBACK_KWH)
        # A slot covers (period_end - 30min, period_end]; it overlaps the event
        # if its start is before the event ends and its end is after it starts.
        mask = (df["period_end"] - pd.Timedelta(minutes=30) < end) & (df["period_end"] > start)
        n = int(mask.sum())
        if n > 0:
            df.loc[mask, "demand"] = df.loc[mask, "demand"] + (energy / n)


def get_optimiser_inputs(site_id: str) -> pd.DataFrame:
    """Return a merged half-hourly DataFrame for the optimiser.

    Generates a complete half-hourly series from now through tomorrow evening,
    LEFT JOINs solcast (solar), agile_rates (prices), and historic demand.
    Overnight periods (no solar) get pv_estimate=0 so the optimiser can see
    cheap overnight prices and plan accordingly.

    Columns returned:
      - period_end: timezone-aware UTC timestamp (half-hour resolution)
      - pv_estimate: solar energy in kWh for the half-hour (0 if no forecast)
      - price: import price (pence)
      - demand: demand energy in kWh for the half-hour
    """
    session = SessionLocal()
    try:
        sql = text("""
        WITH five_min AS (
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
            -- Bucket on the *local* half-hour-of-day: the forecast side below
            -- buckets the same way, so the household's 18:00 peak lines up with
            -- historical 18:00 all year (it was UTC-vs-local drift before the
            -- 2026-10-26 UTC migration: an hour out through BST).
            SELECT
                floor(date_part('hour', period_end AT TIME ZONE 'Europe/London') * 2
                    + date_part('minute', period_end AT TIME ZONE 'Europe/London') / 30) AS hh_slot,
                AVG(value_kw) / 2.0 AS avg_kwh,
                -- Baseload floor: the 20th percentile of the 5-min samples in
                -- this half-hour-of-day slot over the trailing 7 days. This is
                -- the always-on load (fridge/router/standby) with appliance
                -- events stripped out. Used by holiday mode.
                percentile_cont(0.2) WITHIN GROUP (ORDER BY value_kw) / 2.0 AS base_kwh
            FROM five_min
            GROUP BY hh_slot
        ),

        -- 7-day time-of-day average of historical Agile prices, used to fill
        -- the horizon beyond the last published price so the optimiser still
        -- sees tomorrow's typical shape (cheap overnight, evening peak).
        price_history AS (
            SELECT
                floor(date_part('hour', period_end AT TIME ZONE 'Europe/London') * 2
                    + date_part('minute', period_end AT TIME ZONE 'Europe/London') / 30) AS hh_slot,
                AVG(import_price) AS avg_import_price,
                AVG(export_price) AS avg_export_price
            FROM public.agile_rates
            WHERE period_end < now()
            GROUP BY hh_slot
        ),

        -- Generate complete half-hourly series: now through +48h. Longer than
        -- the old 36h so the optimiser can see a full next day (Agile prices
        -- publish ~4pm day-ahead) and hold charge for tomorrow's evening peak
        -- instead of dumping at the end of today.
        forecast_series AS (
            SELECT 
                gs AS period_end,
                floor(date_part('hour', gs AT TIME ZONE 'Europe/London') * 2
                      + date_part('minute', gs AT TIME ZONE 'Europe/London') / 30) AS hh_slot
            FROM generate_series(
                date_trunc('hour', now()) + interval '30 minutes',
                now() + interval '48 hours',
                interval '30 minutes'
            ) gs
        )

        SELECT
            f.period_end as period_end,
            COALESCE(sf.solar_kwh, 0.0) AS pv_estimate,
            ar.import_price AS agile_import_price,
            ar.export_price AS agile_export_price,
            ph.avg_import_price AS avg_import_price,
            ph.avg_export_price AS avg_export_price,
            COALESCE(h.avg_kwh, 0.3) AS demand_avg,
            COALESCE(h.base_kwh, 0.3) AS demand_base
        FROM forecast_series f
        LEFT JOIN solcast_forecast sf
            ON sf.period_end = f.period_end
            AND sf.site_id = :site_id
        LEFT JOIN half_hour_history h
            ON f.hh_slot = h.hh_slot
        LEFT JOIN agile_rates ar
            ON ar.period_end = f.period_end
        LEFT JOIN price_history ph
            ON f.hh_slot = ph.hh_slot
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
            return pd.DataFrame(columns=["period_end", "pv_estimate", "price", "export_price", "demand", "is_synthetic"]) 

        # Normalize column names and types
        # handle both tz-aware and tz-naive timestamps returned by the DB
        try:
            df["period_end"] = pd.to_datetime(df["period_end"]).dt.tz_convert("UTC")
        except TypeError:
            df["period_end"] = pd.to_datetime(df["period_end"]).dt.tz_localize("UTC")
        df["pv_estimate"] = df["pv_estimate"].astype(float)

        # Prices come from the site's tariff, not directly from Agile. With Cosy
        # the import leg is a fixed local-time window vector; export stays Agile
        # unless the site chose a flat export rate. `is_synthetic` marks the
        # backfilled/estimated tail that auto-push refuses to send to the device.
        tariff = get_active_tariff(site_id)
        price, export_price, is_synthetic = resolve_prices(
            tariff,
            df["period_end"],
            agile_import=df.get("agile_import_price"),
            agile_export=df.get("agile_export_price"),
            avg_import=df.get("avg_import_price"),
            avg_export=df.get("avg_export_price"),
        )
        df["price"] = price
        df["export_price"] = export_price
        df["is_synthetic"] = is_synthetic

        # Demand: normal mode keeps the learned 7-day half-hour-of-day average
        # (unchanged behaviour). Holiday mode collapses to the baseload floor,
        # then adds explicitly scheduled (planned) events — so a single Cosy run
        # can still be scheduled before returning home.
        if _holiday_active(session, site_id):
            df["demand"] = df["demand_base"].astype(float)
            _add_planned_events(df, session, site_id, datetime.now(timezone.utc))
        else:
            df["demand"] = df["demand_avg"].astype(float)

        # is_synthetic was resolved above from the tariff price vectors.

        return df[["period_end", "pv_estimate", "price", "export_price", "demand", "is_synthetic"]]
    finally:
        session.close()


def get_user_site(user_id: str) -> dict | None:
    """Look up the user's site by their auth UID.

    Returns site id, name, timezone plus the holiday-mode fields.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("SELECT id, name, timezone, holiday_mode, holiday_until FROM sites WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id}
        )
        row = result.mappings().first()
        return dict(row) if row else None
    finally:
        session.close()


def update_site_holiday(site_id: str, updates: dict) -> dict | None:
    """Update the holiday-mode fields on a site.

    `updates` may contain `holiday_mode` and/or `holiday_until` (a datetime or
    None to clear). Fields absent from the dict are left unchanged; an explicit
    None for `holiday_until` clears it.
    """
    allowed = {"holiday_mode", "holiday_until"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return None
    session = SessionLocal()
    try:
        set_parts = [f"{k} = :{k}" for k in fields]
        sql = text(f"""UPDATE sites
                       SET {', '.join(set_parts)}
                       WHERE id = :sid
                       RETURNING id, name, timezone, holiday_mode, holiday_until""")
        result = session.execute(sql, {"sid": site_id, **fields})
        row = result.mappings().first()
        session.commit()
        if not row:
            return None
        d = dict(row)
        if d.get("id"):
            d["id"] = str(d["id"])
        return d
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
        encrypted = encrypt_provider_config(provider_config or {})
        result = session.execute(
            text("""INSERT INTO batteries (id, site_id, capacity_kwh, max_charge_kw, max_discharge_kw, min_soc_pct, max_soc_pct, provider_type, provider_config)
                    VALUES (gen_random_uuid(), :sid, :cap, :mch, :mdis, :minsoc, :maxsoc, :ptype, CAST(:pconf AS json))
                    RETURNING id, site_id, capacity_kwh, max_charge_kw, max_discharge_kw, min_soc_pct, max_soc_pct, provider_type"""),
            {"sid": site_id, "cap": capacity_kwh, "mch": max_charge_kw, "mdis": max_discharge_kw,
             "minsoc": min_soc_pct, "maxsoc": max_soc_pct, "ptype": provider_type,
             "pconf": json.dumps({"encrypted": encrypted})}
        )
        row = result.mappings().first()
        session.commit()
        return dict(row)
    finally:
        session.close()


def create_tariff(site_id: str, import_type: str, export_type: str, config_json: dict | None = None) -> dict:
    """Deprecated alias — use `app.services.tariff.upsert_tariff`.

    Kept so an older import path cannot silently insert a second row for the
    same site (which the unique index now rejects).
    """
    from app.services.tariff import upsert_tariff

    return upsert_tariff(site_id, import_type, export_type, config_json)


def get_user_battery(user_id: str) -> dict | None:
    """Return the user's battery as a dict, or None."""
    session = SessionLocal()
    try:
        result = session.execute(
            text("""SELECT b.id, b.site_id, b.capacity_kwh, b.max_charge_kw,
                           b.max_discharge_kw, b.min_soc_pct, b.max_soc_pct,
                           b.provider_type, b.provider_config, b.auto_push_enabled
                    FROM batteries b
                    JOIN sites s ON s.id = b.site_id
                    WHERE s.user_id = :uid
                    LIMIT 1"""),
            {"uid": user_id}
        )
        row = result.mappings().first()
        if not row:
            return None
        d = dict(row)
        # Convert UUIDs to strings for JSON serialization
        if d.get("id"):
            d["id"] = str(d["id"])
        if d.get("site_id"):
            d["site_id"] = str(d["site_id"])
        # Parse and decrypt provider_config
        raw = d.get("provider_config")
        if isinstance(raw, str):
            import json
            raw = json.loads(raw)
        if isinstance(raw, dict) and "encrypted" in raw:
            d["provider_config"] = decrypt_provider_config(raw["encrypted"])
        elif isinstance(raw, dict):
            # Legacy unencrypted — return as-is
            d["provider_config"] = raw
        else:
            d["provider_config"] = {}
        return d
    finally:
        session.close()


def update_battery_provider_config(battery_id: str, provider_config: dict) -> dict:
    """Update the provider_config JSON column for a battery (encrypted)."""
    session = SessionLocal()
    try:
        import json
        encrypted = encrypt_provider_config(provider_config)
        result = session.execute(
            text("""UPDATE batteries
                    SET provider_config = CAST(:pconf AS json)
                    WHERE id = :bid
                    RETURNING id, site_id, provider_type, provider_config"""),
            {"bid": battery_id, "pconf": json.dumps({"encrypted": encrypted})}
        )
        row = result.mappings().first()
        session.commit()
        if not row:
            return None
        d = dict(row)
        if d.get("id"):
            d["id"] = str(d["id"])
        if d.get("site_id"):
            d["site_id"] = str(d["site_id"])
        # Decrypt on return
        raw = d.get("provider_config")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict) and "encrypted" in raw:
            d["provider_config"] = decrypt_provider_config(raw["encrypted"])
        else:
            d["provider_config"] = raw or {}
        return d
    finally:
        session.close()


def update_battery_config(battery_id: str, updates: dict) -> dict:
    """Update battery config fields (capacity, power, SOC limits)."""
    session = SessionLocal()
    try:
        allowed = {"capacity_kwh", "max_charge_kw", "max_discharge_kw", "min_soc_pct", "max_soc_pct", "auto_push_enabled"}
        fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not fields:
            return None

        set_parts = [f"{k} = :{k}" for k in fields]
        sql = text(f"""UPDATE batteries
                       SET {', '.join(set_parts)}
                       WHERE id = :bid
                       RETURNING id, site_id, capacity_kwh, max_charge_kw, max_discharge_kw,
                                 min_soc_pct, max_soc_pct, provider_type, provider_config, auto_push_enabled""")
        params = {"bid": battery_id, **fields}
        result = session.execute(sql, params)
        row = result.mappings().first()
        session.commit()
        if not row:
            return None
        d = dict(row)
        if d.get("id"):
            d["id"] = str(d["id"])
        if d.get("site_id"):
            d["site_id"] = str(d["site_id"])
        raw = d.get("provider_config")
        if isinstance(raw, str):
            import json
            raw = json.loads(raw)
        if isinstance(raw, dict) and "encrypted" in raw:
            d["provider_config"] = decrypt_provider_config(raw["encrypted"])
        else:
            d["provider_config"] = raw or {}
        return d
    finally:
        session.close()


def _foxess_ts_to_iso(ts_str: str) -> str:
    """Convert FoxESS timestamp like '2026-09-05 16:03:36 BST+0100' to ISO format."""
    import re
    from datetime import datetime, timezone, timedelta
    m = re.match(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+\w+([+-])(\d{4})', ts_str)
    if not m:
        return ts_str
    date_str, time_str, sign_char, tz_digits = m.groups()
    sign = 1 if sign_char == '+' else -1
    tz_hours = int(tz_digits[0:2])
    tz_mins = int(tz_digits[2:4])
    tz = timezone(timedelta(hours=sign * tz_hours, minutes=sign * tz_mins))
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    return dt.isoformat()


def get_battery_realtime(user_id: str) -> dict:
    """Fetch real-time SOC and last 4 hours of history from FoxESS.

    Returns {soc_pct: float|None, history: [...], error?: str}.
    `error` is included when credentials are missing/unreadable or a FoxESS
    call fails, so failures don't silently masquerade as "no live data".
    """
    import hashlib
    import time as _time
    import requests

    try:
        battery = get_user_battery(user_id)
    except ValueError as exc:
        return {"soc_pct": None, "history": [], "error": str(exc)}
    if not battery:
        return {"soc_pct": None, "history": [], "error": "No battery found. Complete setup first."}

    config = battery.get("provider_config") or {}
    foxess_key = config.get("foxess_api_key")
    device_sn = config.get("foxess_device_sn")

    if not foxess_key or not device_sn:
        return {
            "soc_pct": None,
            "history": [],
            "error": "FoxESS API credentials not configured. Add them in Settings.",
        }

    base_url = "https://www.foxesscloud.com"
    headers_base = {"Content-Type": "application/json", "lang": "en"}

    def _sign(path: str, key: str, ts: int) -> dict:
        sig = hashlib.md5(f"{path}\r\n{key}\r\n{ts}".encode()).hexdigest()
        return {**headers_base, "signature": sig, "token": key, "timestamp": str(ts)}

    soc_pct = None
    history = []
    errors = []

    # 1. Real-time SOC
    try:
        path = "/op/v0/device/real/query"
        ts = int(_time.time() * 1000)
        resp = requests.post(
            f"{base_url}{path}",
            headers=_sign(path, foxess_key, ts),
            json={"sn": device_sn, "variables": ["SoC"]},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            for entry in data.get("result", [{}])[0].get("datas", []):
                if entry.get("variable") == "SoC":
                    soc_pct = float(entry.get("value", 0))
                    break
        else:
            errors.append(f"FoxESS SOC query failed (HTTP {resp.status_code})")
    except Exception as exc:
        errors.append(f"FoxESS SOC query error: {exc}")

    # 2. History: last 4 hours, aggregated to 30-min buckets
    try:
        path = "/op/v0/device/history/query"
        now_ms = int(_time.time() * 1000)
        begin_ms = now_ms - (4 * 60 * 60 * 1000)
        ts = int(_time.time() * 1000)
        resp = requests.post(
            f"{base_url}{path}",
            headers=_sign(path, foxess_key, ts),
            json={
                "sn": device_sn,
                "variables": ["SoC", "batChargePower", "batDischargePower", "gridConsumptionPower", "pvPower"],
                "begin": begin_ms,
                "end": now_ms,
            },
            timeout=15,
        )
        if resp.ok:
            import re
            from datetime import datetime, timezone, timedelta
            data = resp.json()

            # Parse FoxESS timestamp to datetime
            def _parse_fox(ts_str):
                m = re.match(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+\w+([+-])(\d{4})', ts_str)
                if not m:
                    return None
                date_s, time_s, sign_char, tz_digits = m.groups()
                sign = 1 if sign_char == '+' else -1
                tz = timezone(timedelta(hours=sign*int(tz_digits[0:2]), minutes=sign*int(tz_digits[2:4])))
                return datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)

            # Round datetime down to nearest 30-min bucket
            def _bucket_30(dt):
                if dt.minute < 30:
                    return dt.replace(minute=0, second=0, microsecond=0)
                else:
                    return dt.replace(minute=30, second=0, microsecond=0)

            # Collect raw data points keyed by original time string
            raw = {}
            for entry in data.get("result", [{}])[0].get("datas", []):
                var_name = entry.get("variable")
                for d in entry.get("data", []):
                    t = d.get("time")
                    v = d.get("value")
                    if t is None or v is None:
                        continue
                    if t not in raw:
                        raw[t] = {}
                    raw[t][var_name] = float(v)

            # Integrate power (kW) over time to get energy (kWh), then aggregate into 30-min buckets.
            # FoxESS returns ~5-min power samples; energy = power × Δt_hours.
            power_vars = ["batChargePower", "batDischargePower", "gridConsumptionPower", "pvPower"]

            # Sort all raw points by timestamp
            sorted_points = []
            for t_str, vals in raw.items():
                dt = _parse_fox(t_str)
                if dt:
                    sorted_points.append((dt, t_str, vals))
            sorted_points.sort(key=lambda x: x[0])

            # Compute energy for each sample: power × hours_since_previous_sample
            energy_points = []
            for i, (dt, t_str, vals) in enumerate(sorted_points):
                if i == 0:
                    dt_hours = 5.0 / 60.0  # first sample: assume 5-min interval
                else:
                    dt_hours = (dt - sorted_points[i - 1][0]).total_seconds() / 3600.0
                    dt_hours = max(dt_hours, 1.0 / 60.0)  # clamp to at least 1 min
                ep = {"dt": dt, "t_str": t_str}
                for v in power_vars:
                    ep[v] = vals.get(v, 0.0) * dt_hours
                if "SoC" in vals:
                    ep["SoC"] = vals["SoC"]
                energy_points.append(ep)

            # Aggregate energy into 30-min buckets
            buckets = {}
            for ep in energy_points:
                bucket = _bucket_30(ep["dt"])
                key = bucket.isoformat()
                if key not in buckets:
                    buckets[key] = {"time": key, "soc": [], "charge": 0.0, "discharge": 0.0,
                                    "grid": 0.0, "load": 0.0, "pv": 0.0}
                if "SoC" in ep:
                    buckets[key]["soc"].append(ep["SoC"])
                buckets[key]["charge"] += ep["batChargePower"]
                buckets[key]["discharge"] += ep["batDischargePower"]
                buckets[key]["grid"] += ep["gridConsumptionPower"]
                buckets[key]["pv"] += ep["pvPower"]
                buckets[key]["load"] += (ep["gridConsumptionPower"]
                                          + ep["batDischargePower"]
                                          + ep["pvPower"])

            # Build final history: SoC = last value in bucket, energy values in kWh
            history = []
            for key in sorted(buckets):
                b = buckets[key]
                soc_val = b["soc"][-1] if b["soc"] else None
                entry = {"time": b["time"]}
                if soc_val is not None:
                    entry["soc_pct"] = soc_val
                entry["charge_kwh"] = round(b["charge"], 3)
                entry["discharge_kwh"] = round(b["discharge"], 3)
                entry["grid_import_kwh"] = round(b["grid"], 3)
                entry["load_kwh"] = round(b["load"], 3)
                entry["pv_kwh"] = round(b["pv"], 3)
                history.append(entry)

            # Attach the tariff's import price and Agile export price to each
            # historic bucket. Matched on the slot's UTC period_end, not on an
            # HH:MM string — the old string map silently mismatched across
            # midnight and during BST.
            if history:
                from datetime import timezone as tz, timedelta as td

                starts = []
                for entry in history:
                    start = datetime.fromisoformat(entry["time"])
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=tz.utc)
                    starts.append(start.astimezone(tz.utc))
                period_ends = pd.to_datetime([s + td(minutes=30) for s in starts])

                try:
                    session = SessionLocal()
                    try:
                        result = session.execute(
                            text("""
                                SELECT period_end, import_price, export_price
                                FROM agile_rates
                                WHERE period_end >= :start AND period_end <= :end
                                ORDER BY period_end
                            """),
                            {"start": period_ends.min().to_pydatetime(),
                             "end": period_ends.max().to_pydatetime()},
                        )
                        price_by_slot = {}
                        for r in result.mappings():
                            pe = r["period_end"]
                            if pe.tzinfo is None:
                                pe = pe.replace(tzinfo=tz.utc)
                            price_by_slot[pd.Timestamp(pe).tz_convert("UTC")] = (
                                float(r["import_price"]),
                                float(r["export_price"]),
                            )
                    finally:
                        session.close()

                    agile_import = pd.Series(
                        [price_by_slot.get(ts, (None, None))[0] for ts in period_ends]
                    )
                    agile_export = pd.Series(
                        [price_by_slot.get(ts, (None, None))[1] for ts in period_ends]
                    )
                    import_prices, export_prices, _ = resolve_prices(
                        get_active_tariff(str(battery["site_id"])),
                        pd.Series(period_ends),
                        agile_import=agile_import,
                        agile_export=agile_export,
                    )
                    for entry, imp, exp in zip(history, import_prices, export_prices):
                        entry["import_price"] = float(imp)
                        entry["export_price"] = float(exp)
                except Exception:
                    pass
        else:
            errors.append(f"FoxESS history query failed (HTTP {resp.status_code})")
    except Exception as exc:
        errors.append(f"FoxESS history query error: {exc}")

    result = {"soc_pct": soc_pct, "history": history}
    if errors:
        result["error"] = "; ".join(errors)
    return result
