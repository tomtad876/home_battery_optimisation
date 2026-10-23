#!/usr/bin/env python3
"""Pull and align the data a battery backtest needs.

Writes two CSVs next to this script:
  bt_prices.csv   period_end (UTC), import_price, export_price   (from agile_rates)
  bt_load_pv.csv  period_end (UTC), loadsPower, pvPower          (half-hourly kWh)

`historic_energy_data.period_end` is device-local (naive Europe/London), NOT UTC;
`agile_rates` is UTC. The historic series is converted here, and the
half-hourly resampling matches the app's right-labelled slots.

Usage:
    python scripts/backtest/prep.py            # from DATABASE_URL
    python scripts/backtest/prep.py --from-csv # re-use existing CSVs (no DB)

Requires psycopg2 and DATABASE_URL for the DB path.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def pull(sql: str) -> pd.DataFrame:
    import psycopg2

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-csv", action="store_true", help="skip the DB, reuse the CSVs")
    args = ap.parse_args()

    if args.from_csv:
        for f in ("bt_prices.csv", "bt_load_pv.csv"):
            if not os.path.exists(os.path.join(HERE, f)):
                sys.exit(f"missing {f} — run without --from-csv first")
        print("using existing CSVs")
        return

    print("pulling prices...")
    prices = pull("select period_end, import_price, export_price from agile_rates order by period_end")
    prices["period_end"] = pd.to_datetime(prices["period_end"])
    prices["import_price"] = prices["import_price"].astype(float)
    prices["export_price"] = prices["export_price"].astype(float)
    prices = prices.drop_duplicates("period_end").set_index("period_end").sort_index()
    prices.index = prices.index.tz_localize("UTC")
    print(f"  {len(prices)} rows  {prices.index.min()} -> {prices.index.max()}")

    print("pulling demand + pv (5-min)...")
    raw = pull(
        "select period_end, variable, value from historic_energy_data "
        "where variable in ('loadsPower','pvPower') order by period_end"
    )
    raw["period_end"] = pd.to_datetime(raw["period_end"])
    raw["value"] = raw["value"].astype(float)
    raw["period_end"] = (
        raw["period_end"]
        .dt.tz_localize("Europe/London", ambiguous="infer", nonexistent="shift_forward")
        .dt.tz_convert("UTC")
    )
    raw = raw.drop_duplicates(["period_end", "variable"])

    hh = {}
    for var in ("loadsPower", "pvPower"):
        s = raw[raw["variable"] == var].set_index("period_end")["value"].sort_index()
        # 5-min kW samples -> half-hourly kWh
        hh[var] = s.resample("30min", label="right", closed="right").sum() * (5.0 / 60.0)
    df = pd.DataFrame(hh).dropna()

    prices.to_csv(os.path.join(HERE, "bt_prices.csv"))
    df.to_csv(os.path.join(HERE, "bt_load_pv.csv"))
    print(f"  {len(df)} half-hourly rows  {df.index.min()} -> {df.index.max()}")


if __name__ == "__main__":
    main()
