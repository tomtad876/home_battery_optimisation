"""Estimate the battery's round-trip efficiency from historic data.

Why this exists
---------------
The optimiser's SOC model needs charge/discharge efficiencies (eta_c, eta_d).
A datasheet number is wrong for a specific site (inverter + wiring + BMS +
temperature), so we fit it from the actual FoxESS history instead.

Method
------
Using `SoC` (%) and the AC-side `batChargePower` / `batDischargePower` (kW),
per 5-min interval:

    dSOC_fraction = (SoC_t - SoC_{t-1}) / 100
    Ec = energy charged to the battery this interval (kWh, AC)
    Ed = energy discharged from the battery this interval (kWh, AC)

    dSOC_fraction = (eta_c / C) * Ec - (1 / (eta_d * C)) * Ed

Least squares on (Ec, Ed) gives s = eta_c/C and t = 1/(eta_d*C). The
round-trip is s/t (capacity cancels), and the implied C = sqrt(1/(s*t))
is a specification check — it should come out near the nameplate capacity.

Note: the two coefficients are both scaled by 1/C, so without an independent
capacity we cannot separate eta_c from eta_d; we report the round-trip and
assume symmetric per-direction efficiency eta = sqrt(round_trip).

Usage
-----
    ./venv/bin/python scripts/estimate_round_trip_efficiency.py --days 60

Requires FoxESS credentials for a battery row in the database (decrypted with
PROVIDER_CONFIG_ENCRYPTION_KEY) and network access to foxesscloud.com.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd


def _load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip().replace("\r", "")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_foxess_time(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %Z%z")
    except ValueError:
        # e.g. "2026-09-24 23:57:00 BST+0100" -> keep the numeric offset
        return datetime.fromisoformat(re.sub(r" ([A-Z]{2,5})([+-]\d{4})$", r"\2", value))


def _foxess_credentials():
    import psycopg2
    from app.core.encryption import decrypt_provider_config

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = conn.cursor()
        cur.execute(
            "select provider_config from batteries "
            "where provider_config->>'encrypted' is not null"
        )
        for (config,) in cur.fetchall():
            decrypted = decrypt_provider_config(config["encrypted"])
            if decrypted.get("foxess_device_sn") and decrypted.get("foxess_api_key"):
                return decrypted["foxess_api_key"], decrypted["foxess_device_sn"]
    finally:
        conn.close()
    raise SystemExit("No battery row with FoxESS credentials found.")


def fetch_history(api_key: str, device_sn: str, days: int) -> pd.DataFrame:
    import foxesscloud.openapi as f

    f.api_key = api_key
    f.device_sn = device_sn
    f.debug_setting = -1

    variables = ["batChargePower", "batDischargePower", "SoC", "batTemperature"]
    rows: list[tuple[datetime, str, float]] = []
    for offset in range(days, 0, -1):
        day = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
        try:
            history = f.get_history("day", d=day, v=variables, summary=0)
        except Exception as exc:  # noqa: BLE001 - best-effort per day
            print(f"  day {day}: {exc}", file=sys.stderr)
            continue
        for entry in history or []:
            for point in entry.get("data") or []:
                rows.append((_parse_foxess_time(point["time"]), entry["variable"], point["value"]))
    df = pd.DataFrame(rows, columns=["time", "variable", "value"])
    if df.empty:
        raise SystemExit("No history returned.")
    return df.pivot_table(index="time", columns="variable", values="value").sort_index()


def fit_efficiency(p: pd.DataFrame) -> dict:
    dt = (p.index.to_series().diff().dt.total_seconds() / 3600).clip(0, 0.25)
    # Trapezoidal interval energy attributed to the interval ending at each sample.
    ec = ((p["batChargePower"] + p["batChargePower"].shift(1)) / 2 * dt).clip(lower=0)
    ed = ((p["batDischargePower"] + p["batDischargePower"].shift(1)) / 2 * dt).clip(lower=0)
    dsoc = (p["SoC"] - p["SoC"].shift(1)) / 100.0

    data = pd.DataFrame({"Ec": ec, "Ed": ed, "dSOC": dsoc, "dt": dt}).dropna()
    data = data[(data.dt > 0.01) & (data.dt < 0.2)]
    data = data[(data.Ec > 0.001) | (data.Ed > 0.001)]  # drop idle intervals

    a = np.column_stack([data.Ec, data.Ed])
    coef, *_ = np.linalg.lstsq(a, data.dSOC, rcond=None)
    s, t = coef[0], -coef[1]  # s = eta_c/C, t = 1/(eta_d*C), both > 0
    pred = a @ coef
    r2 = 1 - ((data.dSOC - pred) ** 2).sum() / ((data.dSOC - data.dSOC.mean()) ** 2).sum()
    round_trip = s / t
    return {
        "round_trip": round_trip,
        "per_direction": float(np.sqrt(round_trip)),
        "implied_capacity_kwh": float(np.sqrt(1 / (s * t))),
        "r2": float(r2),
        "n_intervals": int(len(data)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60, help="history window (default 60)")
    args = parser.parse_args()

    _load_env()
    api_key, device_sn = _foxess_credentials()
    print(f"Fetching {args.days} days of FoxESS history...")
    p = fetch_history(api_key, device_sn, args.days)
    if "SoC" not in p.columns:
        raise SystemExit("No SoC in history — cannot fit efficiency.")
    result = fit_efficiency(p)
    print(f"  span:              {p.index.min()} .. {p.index.max()}")
    print(f"  intervals used:    {result['n_intervals']}")
    print(f"  round-trip:        {result['round_trip']:.4f}")
    print(f"  per-direction:     {result['per_direction']:.4f}")
    print(f"  implied capacity:  {result['implied_capacity_kwh']:.3f} kWh")
    print(f"  R^2:               {result['r2']:.3f}")
    print()
    print("To update the optimiser defaults, round the per-direction figure to 2dp and")
    print("edit DEFAULT_CHARGE_EFFICIENCY / DEFAULT_DISCHARGE_EFFICIENCY in app/core/optimiser.py.")


if __name__ == "__main__":
    main()
