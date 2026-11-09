"""Tariff-aware import and export pricing.

The optimiser is price-vector agnostic — it only needs pence/kWh per half-hour
slot. This module turns the site's tariff choice into that vector.

Import tariffs:
  agile  half-hourly Agile prices from ``agile_rates`` (previous behaviour)
  cosy   Octopus Cosy: 8 cheap hours in three fixed local-time windows plus an
         evening peak. Rates come from Octopus's public product API and fall
         back to the rates saved on the tariff row if the API is unavailable.
  fixed  one flat rate.

Export always comes from Agile (Outgoing Agile) unless the site explicitly
chooses a flat export rate, because the export tariff is independent of the
import tariff and is what the household is actually paid.

Windows are local wall-clock time (Europe/London), so they follow BST/GMT with
no hardcoded offset.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.core.database import SessionLocal
from app.services import octopus

LONDON = "Europe/London"

SUPPORTED_IMPORT_TARIFFS = ("agile", "cosy", "fixed")
SUPPORTED_EXPORT_TARIFFS = ("agile", "fixed")

# Region E (West Midlands) is the app's historical default for Agile; keep it as
# the default here too. Cosy rates differ per region: L (South West) is
# 14.11 / 28.78 / 43.17 where E is 13.59 / 27.72 / 41.58 (Nov 2026).
DEFAULT_REGION = os.getenv("AGILE_REGION_CODE", "E").upper()
DEFAULT_COSY_PRODUCT = os.getenv("COSY_PRODUCT_CODE", "COSY-22-12-08")

# Octopus Cosy cheap windows (8 h) and evening peak. Confirmed against the
# published product API: 04:00-07:00, 13:00-16:00, 22:00-24:00 cheap;
# 16:00-19:00 peak; everything else day rate.
DEFAULT_COSY_WINDOWS = {
    "cheap": [["04:00", "07:00"], ["13:00", "16:00"], ["22:00", "24:00"]],
    "peak": [["16:00", "19:00"]],
}
# Fallback only — the live rates come from the Octopus API. These are the
# region-E rates published 2026-11-09 (inc VAT).
DEFAULT_COSY_RATES = {
    "cheap_pence": 13.59,
    "day_pence": 27.72,
    "peak_pence": 41.58,
}
DEFAULT_FIXED_IMPORT_PENCE = 24.5
DEFAULT_FLAT_EXPORT_PENCE = 15.0


def _default_import_config() -> dict:
    return {
        "product_code": DEFAULT_COSY_PRODUCT,
        "rates": dict(DEFAULT_COSY_RATES),
        "windows": {k: [list(w) for w in v] for k, v in DEFAULT_COSY_WINDOWS.items()},
        "flat_pence": DEFAULT_FIXED_IMPORT_PENCE,
    }


def normalise_tariff(row: dict | None) -> dict:
    """Return a complete tariff dict from a (possibly sparse) DB row.

    Unknown/missing fields fall back to defaults so callers never have to guard
    against a half-written config. Existing rows only have ``region_code``.
    """
    row = row or {}
    config = row.get("config_json") or {}
    if isinstance(config, str):
        import json

        try:
            config = json.loads(config)
        except ValueError:
            config = {}

    import_type = (row.get("import_type") or "agile").lower()
    export_type = (row.get("export_type") or "agile").lower()
    if import_type not in SUPPORTED_IMPORT_TARIFFS:
        import_type = "agile"
    if export_type not in SUPPORTED_EXPORT_TARIFFS:
        export_type = "agile"

    raw_import = config.get("import") or {}
    defaults = _default_import_config()
    rates = {**defaults["rates"], **(raw_import.get("rates") or {})}
    windows = raw_import.get("windows") or defaults["windows"]
    raw_export = config.get("export") or {}

    return {
        "id": row.get("id"),
        "site_id": row.get("site_id"),
        "import_type": import_type,
        "export_type": export_type,
        "region_code": (config.get("region_code") or DEFAULT_REGION).upper(),
        "import": {
            "product_code": raw_import.get("product_code") or defaults["product_code"],
            "rates": {
                "cheap_pence": float(rates["cheap_pence"]),
                "day_pence": float(rates["day_pence"]),
                "peak_pence": float(rates["peak_pence"]),
            },
            "windows": windows,
            "flat_pence": float(raw_import.get("flat_pence", defaults["flat_pence"])),
        },
        "export": {
            "flat_pence": float(raw_export.get("flat_pence", DEFAULT_FLAT_EXPORT_PENCE)),
        },
    }


def get_active_tariff(site_id: str) -> dict:
    """Return the site's active tariff. Never writes; defaults to Agile."""
    session = SessionLocal()
    try:
        row = session.execute(
            text(
                """SELECT id, site_id, import_type, export_type, config_json
                   FROM tariffs WHERE site_id = :sid LIMIT 1"""
            ),
            {"sid": site_id},
        ).mappings().first()
        return normalise_tariff(dict(row) if row else None)
    finally:
        session.close()


def upsert_tariff(site_id: str, import_type: str, export_type: str,
                  config_json: dict | None = None) -> dict:
    """Create or replace the site's tariff (one row per site).

    Switching tariffs is an update, not an append: the optimiser reads a single
    active tariff and a second row would make the choice ambiguous.
    """
    import json

    import_type = (import_type or "agile").lower()
    export_type = (export_type or "agile").lower()
    if import_type not in SUPPORTED_IMPORT_TARIFFS:
        raise ValueError(
            f"Unsupported import tariff '{import_type}'. "
            f"Choose one of: {', '.join(SUPPORTED_IMPORT_TARIFFS)}."
        )
    if export_type not in SUPPORTED_EXPORT_TARIFFS:
        raise ValueError(
            f"Unsupported export tariff '{export_type}'. "
            f"Choose one of: {', '.join(SUPPORTED_EXPORT_TARIFFS)}."
        )

    merged = normalise_tariff(
        {"import_type": import_type, "export_type": export_type, "config_json": config_json}
    )
    stored_config = {
        "region_code": merged["region_code"],
        "import": merged["import"],
        "export": merged["export"],
    }

    session = SessionLocal()
    try:
        row = session.execute(
            text(
                """INSERT INTO tariffs (id, site_id, import_type, export_type, config_json)
                   VALUES (gen_random_uuid(), :sid, :itype, :etype, CAST(:conf AS json))
                   ON CONFLICT (site_id) DO UPDATE
                     SET import_type = EXCLUDED.import_type,
                         export_type = EXCLUDED.export_type,
                         config_json = EXCLUDED.config_json
                   RETURNING id, site_id, import_type, export_type, config_json"""
            ),
            {"sid": site_id, "itype": import_type, "etype": export_type,
             "conf": json.dumps(stored_config)},
        ).mappings().first()
        session.commit()
        return normalise_tariff(dict(row) if row else None)
    finally:
        session.close()


# --- Price vectors -----------------------------------------------------------

def _parse_minutes(value: str) -> int:
    """'04:00' -> 240, '24:00' -> 1440."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _in_window(minutes: int, start: str, end: str) -> bool:
    return _parse_minutes(start) <= minutes < _parse_minutes(end)


def _window_price(local_ts: pd.Timestamp, windows: dict, rates: dict) -> float:
    minutes = local_ts.hour * 60 + local_ts.minute
    for start, end in windows.get("cheap", []):
        if _in_window(minutes, start, end):
            return float(rates["cheap_pence"])
    for start, end in windows.get("peak", []):
        if _in_window(minutes, start, end):
            return float(rates["peak_pence"])
    return float(rates["day_pence"])


def _utc_index(values) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(values))
    if idx.tz is None:
        return idx.tz_localize("UTC")
    return idx.tz_convert("UTC")


def cosy_prices(period_end, tariff: dict, index: pd.Index | None = None) -> pd.Series:
    """Cosy import price per slot, keyed by ``period_end``.

    A slot covers ``(period_end - 30 min, period_end]``, so the window is chosen
    from the slot *start*. Published Octopus rates win where they exist; the
    configured windows fill any gap (and are the only source if the API is down).
    """
    period_end = _utc_index(period_end)
    out_index = index if index is not None else pd.RangeIndex(len(period_end))
    starts = period_end - pd.Timedelta(minutes=30)
    local = starts.tz_convert(LONDON)
    windows = tariff["import"]["windows"]
    rates = tariff["import"]["rates"]

    prices = np.array([_window_price(ts, windows, rates) for ts in local], dtype=float)

    live = octopus.get_standard_unit_rates(
        tariff["import"]["product_code"],
        tariff["region_code"],
        starts.min().to_pydatetime(),
        (starts.max() + pd.Timedelta(minutes=30)).to_pydatetime(),
    )
    if live:
        live_prices = np.full(len(starts), np.nan)
        for rate in live:
            valid_from = pd.Timestamp(rate["valid_from"]).tz_convert("UTC")
            valid_to = (
                pd.Timestamp(rate["valid_to"]).tz_convert("UTC")
                if rate["valid_to"]
                else pd.Timestamp.max.tz_localize("UTC")
            )
            mask = (starts >= valid_from) & (starts < valid_to)
            live_prices[np.asarray(mask)] = rate["pence"]
        prices = np.where(np.isnan(live_prices), prices, live_prices)

    return pd.Series(prices, index=out_index, dtype=float)


def resolve_prices(
    tariff: dict,
    period_end: pd.Series,
    agile_import: pd.Series | None = None,
    agile_export: pd.Series | None = None,
    avg_import: pd.Series | None = None,
    avg_export: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return ``(import_pence, export_pence, is_synthetic)`` aligned to the index.

    ``is_synthetic`` is true where a price is a fallback rather than a published
    one. It gates the estimated tail of the plan (auto-push drops it), so an
    estimated *export* leg counts too — with Cosy the import leg is always known
    but Outgoing Agile prices are only published ~a day ahead.
    """
    index = period_end.index
    zeros = pd.Series(0.0, index=index)

    def _num(series):
        if series is None:
            return None
        return pd.to_numeric(series, errors="coerce").astype(float)

    agile_imp = _num(agile_import)
    agile_exp = _num(agile_export)
    avg_imp = _num(avg_import)
    avg_exp = _num(avg_export)

    import_type = tariff["import_type"]
    if import_type == "cosy":
        import_prices = cosy_prices(period_end, tariff, index=index)
        import_synthetic = pd.Series(False, index=index)
    elif import_type == "fixed":
        import_prices = pd.Series(
            tariff["import"]["flat_pence"], index=index, dtype=float
        )
        import_synthetic = pd.Series(False, index=index)
    elif agile_imp is None:
        # No Agile series supplied at all: don't silently price imports at 0p.
        import_prices = pd.Series(
            tariff["import"]["flat_pence"], index=index, dtype=float
        )
        import_synthetic = pd.Series(True, index=index)
    else:  # agile
        import_prices = agile_imp.fillna(avg_imp if avg_imp is not None else zeros)
        import_prices = import_prices.fillna(tariff["import"]["flat_pence"])
        import_synthetic = agile_imp.isna()

    if tariff["export_type"] == "fixed":
        export_prices = pd.Series(
            tariff["export"]["flat_pence"], index=index, dtype=float
        )
        export_synthetic = pd.Series(False, index=index)
    elif agile_exp is None:
        export_prices = pd.Series(
            tariff["export"]["flat_pence"], index=index, dtype=float
        )
        export_synthetic = pd.Series(True, index=index)
    else:  # agile
        export_prices = agile_exp.fillna(avg_exp if avg_exp is not None else zeros)
        export_prices = export_prices.fillna(tariff["export"]["flat_pence"])
        export_synthetic = agile_exp.isna()

    return (
        import_prices.astype(float),
        export_prices.astype(float),
        (import_synthetic | export_synthetic).astype(bool),
    )
