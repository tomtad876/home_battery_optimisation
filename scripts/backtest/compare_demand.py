#!/usr/bin/env python3
"""Compare demand forecast variants on the same days (paired).

`backtest.py` compares *strategies* within one run, but the demand method is
global to a run — so comparing forecasters needs two runs over identical days and
a paired difference. That is also the right statistic: the days are shared, so
the variance of the *difference* is what matters, not the variance of either
level.

    python scripts/backtest/compare_demand.py
    python scripts/backtest/compare_demand.py --methods mean,median --start 2026-03-01
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

from backtest import block_bootstrap, load, make_strategies, run  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=HERE)
    ap.add_argument("--methods", default="mean,median")
    ap.add_argument("--strategy", default="baseline")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-10-20")
    ap.add_argument("--pv-mode", default="actual", choices=["actual", "persistence"])
    ap.add_argument("--bootstrap", type=int, default=4000)
    args = ap.parse_args()

    prices, lp = load(args.data_dir)
    strategies = make_strategies()
    if args.strategy not in strategies:
        sys.exit(f"unknown strategy {args.strategy!r}; choose from {list(strategies)}")

    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]

    runs: dict[str, pd.Series] = {}
    for method in methods:
        frame = run(prices, lp, days, strategies[args.strategy], args.pv_mode, method)
        runs[method] = frame.set_index("day")["cost"]
        print(f"  {method:8s} {len(frame)} days   mean £{frame['cost'].mean():+.3f}/day")

    base = methods[0]
    print(f"\n{'method':10} {'£/day':>9} {'total £':>9} "
          f"{'vs ' + base + ' £/day':>18} {'95% CI (paired)':>24}")
    for method in methods:
        c = runs[method]
        # paired on the shared days only
        shared = c.index.intersection(runs[base].index)
        delta = (runs[base].loc[shared] - c.loc[shared])  # positive = method cheaper
        if method == base:
            print(f"{method:10} {c.mean():+9.3f} {c.sum():9.2f} {0.0:18.4f} {'—':>24}")
            continue
        lo, hi = block_bootstrap(delta.values, n=args.bootstrap)
        verdict = "cheaper" if lo > 0 else ("worse" if hi < 0 else "neutral")
        print(f"{method:10} {c.mean():+9.3f} {c.sum():9.2f} {delta.mean():18.4f} "
              f"{lo:+.4f} .. {hi:+.4f}  {verdict}")

    shared = runs[methods[0]].index.intersection(runs[methods[-1]].index)
    if len(shared) < len(days):
        print(f"\n  note: paired on {len(shared)} of {len(days)} days (some days lacked history)")


if __name__ == "__main__":
    main()
