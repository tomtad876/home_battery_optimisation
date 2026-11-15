#!/usr/bin/env python3
"""Recompute recent cost history for every site (the nightly cron's work).

    ./venv/bin/python scripts/refresh_cost_history.py           # last 7 days
    ./venv/bin/python scripts/refresh_cost_history.py --days 30

Also exposed as POST /internal/refresh-cost-history for pg_cron
(supabase/cron/refresh_cost_history.sql). Full historical rebuild:
scripts/backfill_cost_history.py.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cost_history import refresh_recent  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    results = refresh_recent(args.days)
    if not results:
        print("no sites")
        return
    for r in results:
        if r["error"]:
            print(f"  {r['site']}: FAILED {r['error']}")
        else:
            print(f"  {r['site']}: {r['days']} days refreshed ({r['source']})")


if __name__ == "__main__":
    main()
