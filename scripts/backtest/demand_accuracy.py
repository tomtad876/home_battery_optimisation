#!/usr/bin/env python3
"""Forecast accuracy for the demand variants — the other half of the picture.

`compare_demand.py` answers "which forecast produces the cheaper plan". That is a
*decision* metric: it tells you what the optimiser did with the forecast, not how
good the forecast was. A forecast can be more accurate and produce a worse plan
(MAE treats a 3am error like an evening-peak one), or less accurate and produce a
better one (the LP may be exploiting the bias).

So report both, and a bridge: price-weighted error, which asks "was it wrong in
the slots that cost money", not "was it wrong on average".

    python scripts/backtest/demand_accuracy.py
    python scripts/backtest/demand_accuracy.py --methods mean,median --start 2026-03-01
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
sys.path.insert(0, HERE)

from backtest import demand_forecast, load  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=HERE)
    ap.add_argument("--methods", default="mean,median")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-10-20")
    args = ap.parse_args()

    prices, lp = load(args.data_dir)
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]

    actual_all = lp["loadsPower"]

    print(f"{len(days)} days  {start} -> {end}\n")
    print(f"{'method':8} {'bias kWh':>9} {'MAE kWh':>9} {'RMSE kWh':>9} "
          f"{'£-weighted err':>15} {'n slots':>8}")

    summary = {}
    for method in methods:
        errs, px_errs = [], []
        for day in days:
            fc = demand_forecast(lp, day, method)
            if fc is None:
                continue
            t0 = pd.Timestamp(day, tz="UTC")
            idx = pd.date_range(t0, t0 + pd.Timedelta(hours=24) - pd.Timedelta(minutes=30), freq="30min")
            slot = idx.hour * 2 + idx.minute // 30
            pred = pd.Series(fc.reindex(slot).values, index=idx)
            act = actual_all.reindex(idx)
            ok = pred.notna() & act.notna()
            if not ok.any():
                continue
            err = (act[ok] - pred[ok])          # positive = under-forecast
            # import price only: that is what a kWh of unmet demand costs
            px = prices.reindex(idx)["import_price"][ok].fillna(0.0)
            errs.append(err)
            # error in pence: a kWh of error at 40p costs more than at 5p
            px_errs.append((err.abs() * px / 100.0))

        if not errs:
            continue
        e = pd.concat(errs)
        pe = pd.concat(px_errs)
        m = {
            "bias": e.mean(),
            "mae": e.abs().mean(),
            "rmse": float(np.sqrt((e ** 2).mean())),
            "px_err": pe.mean(),
            "n": len(e),
        }
        summary[method] = m
        print(f"{method:8} {m['bias']:+9.4f} {m['mae']:9.4f} {m['rmse']:9.4f} "
              f"{m['px_err']:15.4f} {m['n']:8d}")

    if len(summary) > 1:
        base = methods[0]
        print(f"\nvs {base}:")
        for method in methods[1:]:
            b, c = summary[base], summary[method]
            print(f"  {method:8} bias {c['bias'] - b['bias']:+.4f} kWh   "
                  f"MAE {c['mae'] - b['mae']:+.4f} kWh   "
                  f"price-weighted error {c['px_err'] - b['px_err']:+.4f} £/slot   "
                  f"({'better' if c['mae'] < b['mae'] else 'worse'} on accuracy)")

    print("\npositive bias = under-forecasting demand (plan under-provisions)")
    print("price-weighted error is the bridge: it says whether the error landed in")
    print("expensive slots, which is what a decision metric is really reacting to.")


if __name__ == "__main__":
    main()
