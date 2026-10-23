#!/usr/bin/env python3
"""Backtest battery strategies against real history.

This is the "measure first" harness: give it a set of candidate optimiser
strategies and it walks forward day by day over the recorded prices, demand and
PV, executes each plan against what actually happened, and reports the cost
difference with a bootstrap confidence interval.

Method
------
For each day D it builds the forecast the app would really have had:
  * demand — the 7-day trailing average by half-hour-of-day (the app's method)
  * PV     — actual ("perfect") or yesterday's ("persistence")
  * prices — actual Agile (published day-ahead)
then solves, and executes the plan against ACTUAL demand/PV/prices with an
energy balance that closes every slot:

    grid = demand - pv + charge - discharge

Battery behaviour mirrors the inverter: ForceCharge takes the planned charge,
ForceDischarge takes the commanded rate, SelfUse meets actual demand (or absorbs
PV surplus) and never goes below the floor. SOC carries across days.

Usage
-----
    python scripts/backtest/prep.py               # build the CSVs from the DB
    python scripts/backtest/backtest.py           # compare all strategies
    python scripts/backtest/backtest.py --strategies baseline,curve
    python scripts/backtest/backtest.py --pv-mode persistence --bootstrap 4000

Strategies (add your own to STRATEGIES):
  baseline  flat 20% floor + flat salvage (today)
  reserve   price-aware reserve (PR #26) — backtested negative, kept as a control
  curve     concave terminal value curve (Stage 3)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from app.core.optimiser import mvp_cost_minimiser, resolve_value_curve  # noqa: E402

CAP = 5.0
POWER = 3.0
ETA_C = ETA_D = 0.95
FIXED_FLOOR = 20.0


# --- data -------------------------------------------------------------------

def load(data_dir: str = HERE):
    prices = pd.read_csv(os.path.join(data_dir, "bt_prices.csv"),
                         parse_dates=["period_end"], index_col="period_end")
    lp = pd.read_csv(os.path.join(data_dir, "bt_load_pv.csv"),
                     parse_dates=["period_end"], index_col="period_end")
    prices.index = pd.to_datetime(prices.index, utc=True)
    lp.index = pd.to_datetime(lp.index, utc=True)
    return prices, lp


def demand_forecast(lp: pd.DataFrame, day: dt.date):
    """7-day trailing average by half-hour-of-day (the app's forecast)."""
    t0 = pd.Timestamp(day, tz="UTC")
    hist = lp.loc[t0 - pd.Timedelta(days=7): t0 - pd.Timedelta(minutes=1), "loadsPower"]
    if hist.empty:
        return None
    return hist.groupby(hist.index.hour * 2 + hist.index.minute // 30).mean()


def build_inputs(prices, lp, day, fc_demand, pv_mode="actual", hours=72):
    t0 = pd.Timestamp(day, tz="UTC")
    idx = pd.date_range(t0, t0 + pd.Timedelta(hours=hours) - pd.Timedelta(minutes=30), freq="30min")
    px = prices.reindex(idx)
    if pv_mode == "persistence":
        prev = lp["pvPower"].reindex(idx - pd.Timedelta(days=1))
        pv = pd.Series(prev.values, index=idx)
    else:
        pv = lp["pvPower"].reindex(idx)
    slot = idx.hour * 2 + idx.minute // 30
    dem = pd.Series([fc_demand.get(s, np.nan) for s in slot], index=idx)
    df = pd.DataFrame({
        "period_end": idx,
        "price": px["import_price"].values,
        "export_price": px["export_price"].values,
        "pv_estimate": pv.values,
        "demand": dem.values,
        "is_synthetic": False,
    })
    return df.dropna().reset_index(drop=True)


# --- execution --------------------------------------------------------------

def execute_day(plan, lp, day, soc_kwh, floor_pct):
    """Run the plan's first 48 slots against actuals. Returns (cost, end_soc)."""
    t0 = pd.Timestamp(day, tz="UTC")
    idx = pd.date_range(t0, t0 + pd.Timedelta(hours=24) - pd.Timedelta(minutes=30), freq="30min")
    act = lp.reindex(idx)
    floor_kwh = floor_pct / 100.0 * CAP
    max_step = POWER * 0.5
    cost = 0.0
    for i in range(min(len(plan), len(idx))):
        row = plan.iloc[i]
        demand = act["loadsPower"].iloc[i]
        pv = act["pvPower"].iloc[i]
        price = row["price"] / 100.0
        exp_price = row["export_price_pence"] / 100.0
        net = demand - pv

        if row["batt_charge_kwh"] > 0.05:
            charge = min(row["batt_charge_kwh"], max(0.0, CAP - soc_kwh))
            discharge = 0.0
        elif row["batt_discharge_kwh"] > 0.05 and row["grid_export_kwh"] > 0.05:
            discharge = min(row["batt_discharge_kwh"], max(0.0, soc_kwh - floor_kwh), max_step)
            charge = 0.0
        elif net > 0:
            discharge = min(net, max_step, max(0.0, soc_kwh - floor_kwh))
            charge = 0.0
        else:
            charge = min(-net, max_step, max(0.0, CAP - soc_kwh))
            discharge = 0.0

        soc_kwh = min(CAP, max(0.0, soc_kwh + charge * ETA_C - discharge / ETA_D))
        grid = demand - pv + charge - discharge
        cost += max(0.0, grid) * price - max(0.0, -grid) * exp_price
    return cost, soc_kwh


# --- strategies -------------------------------------------------------------

def make_strategies():
    """Each strategy is f(inputs_df, soc_pct, bounds) -> (plan, exec_floor_pct).

    `inputs_df` is a 72h horizon; strategies that only look 48h slice `[:96]`.
    `bounds` is (high_pence, low_pence) from the trailing price history.

    "banking" / "banking_curve" see the full 72h — the Stage 3 idea that seeing a
    third day lets the LP bank energy across days.
    """

    def _solve(df, soc_pct, **kw):
        return mvp_cost_minimiser(df, battery_capacity_kwh=CAP, initial_soc_pct=soc_pct,
                                  min_soc_pct=FIXED_FLOOR, max_soc_pct=100.0,
                                  reserve_floor_pct=FIXED_FLOOR, **kw)

    def baseline(inputs, soc_pct, bounds):
        return _solve(inputs.iloc[:96], soc_pct), FIXED_FLOOR

    def reserve(inputs, soc_pct, bounds):
        from app.core.optimiser import resolve_reserve_floor_pct
        df = inputs.iloc[:96]
        floor = resolve_reserve_floor_pct(df)
        return _solve(df, soc_pct, reserve_floor_pct=floor), max(FIXED_FLOOR, floor)

    def curve(inputs, soc_pct, bounds):
        return (_solve(inputs.iloc[:96], soc_pct, value_curve_segments=5,
                       value_curve_high_pence=bounds[0], value_curve_low_pence=bounds[1]),
                FIXED_FLOOR)

    def banking(inputs, soc_pct, bounds):
        return _solve(inputs, soc_pct), FIXED_FLOOR

    def banking_curve(inputs, soc_pct, bounds):
        return (_solve(inputs, soc_pct, value_curve_segments=5,
                       value_curve_high_pence=bounds[0], value_curve_low_pence=bounds[1]),
                FIXED_FLOOR)

    return {"baseline": baseline, "reserve": reserve, "curve": curve,
            "banking": banking, "banking_curve": banking_curve}


def trailing_bounds(prices, day, window_days=90):
    """P90 import / P10 export from the trailing window (no look-ahead)."""
    t0 = pd.Timestamp(day, tz="UTC")
    hist = prices.loc[t0 - pd.Timedelta(days=window_days): t0 - pd.Timedelta(minutes=1)]
    if len(hist) < 48:
        return (30.0, 8.0)
    return (float(np.percentile(hist["import_price"].dropna(), 90)),
            float(np.percentile(hist["export_price"].dropna(), 10)))


# --- engine -----------------------------------------------------------------

def run(prices, lp, days, strategy, pv_mode):
    rows = []
    soc = 0.5 * CAP
    for day in days:
        fc = demand_forecast(lp, day)
        if fc is None:
            continue
        inputs = build_inputs(prices, lp, day, fc, pv_mode)
        if len(inputs) < 96:
            continue
        bounds = trailing_bounds(prices, day)
        plan, floor = strategy(inputs, soc / CAP * 100, bounds)
        cost, soc = execute_day(plan, lp, day, soc, floor)
        rows.append({"day": day, "cost": cost, "soc_end": soc, "high": bounds[0], "low": bounds[1]})
    return pd.DataFrame(rows)


def block_bootstrap(values, block=7, n=4000, seed=0):
    """Bootstrap the mean of a daily series, resampling contiguous day-blocks."""
    rng = np.random.default_rng(seed)
    v = np.asarray(values, dtype=float)
    n_blocks = int(np.ceil(len(v) / block))
    means = []
    for _ in range(n):
        starts = rng.integers(0, max(1, len(v) - block), size=n_blocks)
        sample = np.concatenate([v[s:s + block] for s in starts])[:len(v)]
        means.append(sample.mean())
    return np.percentile(means, [2.5, 97.5])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=HERE)
    ap.add_argument("--strategies", default="baseline,reserve,curve")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-10-20")
    ap.add_argument("--pv-mode", default="actual", choices=["actual", "persistence"])
    ap.add_argument("--bootstrap", type=int, default=4000)
    args = ap.parse_args()

    prices, lp = load(args.data_dir)
    strategies = make_strategies()
    names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    if "baseline" not in names:
        names = ["baseline"] + names
    for n in names:
        if n not in strategies:
            sys.exit(f"unknown strategy {n!r}; choose from {list(strategies)}")

    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    print(f"{len(days)} days  {start} -> {end}   pv={args.pv_mode}")

    results = {}
    for n in names:
        frame = run(prices, lp, days, strategies[n], args.pv_mode)
        results[n] = frame
        print(f"  ran {n:10} {len(frame)} days  "
              f"(trailing P90/P10 {frame['high'].mean():.1f}/{frame['low'].mean():.1f}p)")

    base = results["baseline"]["cost"]
    print(f"\n{'strategy':12} {'mean £/day':>11} {'saving £/day':>13} {'total £':>9} "
          f"{'cheaper %':>10} {'95% CI':>22}")
    for n in names:
        c = results[n]["cost"]
        saving = base - c
        lo, hi = block_bootstrap(saving.values, n=args.bootstrap)
        print(f"{n:12} {c.mean():11.3f} {saving.mean():13.4f} {saving.sum():9.2f} "
              f"{(saving > 0).mean() * 100:9.1f}%  {lo:+.4f} .. {hi:+.4f}")


if __name__ == "__main__":
    main()
