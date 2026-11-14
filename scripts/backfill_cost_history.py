"""Backfill daily_cost_summary for one site or all sites.

    ./venv/bin/python scripts/backfill_cost_history.py --seed-tariffs
    ./venv/bin/python scripts/backfill_cost_history.py --site-id <uuid>
    ./venv/bin/python scripts/backfill_cost_history.py --start 2026-10-01 --end 2026-11-13

Read-only against the supplier: it pulls Octopus half-hourly readings where the
site has credentials and falls back to FoxESS otherwise.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services import cost_history, octopus_meter  # noqa: E402

# Tom's site: recovered from the Octopus account agreements on 2026-11-13.
# Export fixed was 15p until 28 Feb 2026, then 12p; Agile Outgoing from 18 Aug.
STROUD_SITE_ID = 'e17919c0-e7d5-477d-9634-e491450f6b18'
STROUD_PERIODS = [
    ('2025-09-20T00:00:00+01:00', 'agile', {'flat_pence': 24.5, 'standing_pence': 58.63}, 'fixed',
     {'flat_pence': 15.0}, 'Agile import + Outgoing Fixed 15p'),
    ('2026-03-01T00:00:00Z', 'agile', {'flat_pence': 24.5, 'standing_pence': 58.63}, 'fixed',
     {'flat_pence': 12.0}, 'Outgoing Fixed cut to 12p'),
    ('2026-08-18T00:00:00+01:00', 'agile', {'flat_pence': 24.5, 'standing_pence': 58.63}, 'agile',
     {'flat_pence': 15.0}, 'Agile Outgoing'),
    ('2026-11-09T00:00:00Z', 'cosy', {'flat_pence': 24.5, 'standing_pence': 56.61}, 'agile',
     {'flat_pence': 15.0}, 'Cosy import'),
]


def seed_tariffs(site_id: str, periods=STROUD_PERIODS) -> int:
    session = SessionLocal()
    try:
        n = 0
        for valid_from, imp_type, imp_cfg, exp_type, exp_cfg, note in periods:
            session.execute(
                text(
                    """INSERT INTO site_tariff_history
                        (site_id, valid_from, import_type, import_config, export_type, export_config, note)
                       VALUES (:sid, :vf, :it, cast(:ic AS json), :et, cast(:ec AS json), :note)
                       ON CONFLICT (site_id, valid_from) DO UPDATE
                         SET import_type = EXCLUDED.import_type,
                             import_config = EXCLUDED.import_config,
                             export_type = EXCLUDED.export_type,
                             export_config = EXCLUDED.export_config,
                             note = EXCLUDED.note"""
                ),
                {"sid": site_id, "vf": datetime.fromisoformat(valid_from),
                 "it": imp_type, "ic": _json(imp_cfg), "et": exp_type,
                 "ec": _json(exp_cfg), "note": note},
            )
            n += 1
        session.commit()
        return n
    finally:
        session.close()


def seed_from_current(site_id: str) -> int:
    """For every other site: one open period reflecting its current tariff."""
    session = SessionLocal()
    try:
        row = session.execute(
            text("SELECT import_type, export_type, config_json FROM tariffs WHERE site_id = :sid LIMIT 1"),
            {"sid": site_id},
        ).mappings().first()
        if not row:
            return 0
        cfg = row['config_json'] or {}
        if isinstance(cfg, str):
            import json

            cfg = json.loads(cfg)
        session.execute(
            text(
                """INSERT INTO site_tariff_history
                    (site_id, valid_from, import_type, import_config, export_type, export_config, note)
                   VALUES (:sid, :vf, :it, cast(:ic AS json), :et, cast(:ec AS json), :note)
                   ON CONFLICT (site_id, valid_from) DO NOTHING"""
            ),
            {"sid": site_id, "vf": datetime(2020, 1, 1, tzinfo=timezone.utc),
             "it": row['import_type'], "ic": _json(cfg.get('import') or {}),
             "et": row['export_type'], "ec": _json(cfg.get('export') or {}),
             "note": 'seeded from current tariff'},
        )
        session.commit()
        return 1
    finally:
        session.close()


def _json(value) -> str:
    import json

    return json.dumps(value)


def sites() -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.execute(text("SELECT id, name FROM sites ORDER BY name")).mappings().all()
    finally:
        session.close()
    return [dict(r) for r in rows]


def data_window(site_id: str) -> tuple[datetime, datetime] | None:
    session = SessionLocal()
    try:
        row = session.execute(
            text("""SELECT min(period_end) AS first FROM historic_energy_data
                    WHERE site_id = :sid AND variable = 'loadsPower'"""),
            {"sid": site_id},
        ).mappings().first()
    finally:
        session.close()
    if not row or not row['first']:
        return None
    return row['first'], datetime.now(timezone.utc)


def battery_params(site_id: str) -> dict | None:
    session = SessionLocal()
    try:
        row = session.execute(
            text("""SELECT capacity_kwh, max_charge_kw, max_discharge_kw, min_soc_pct, max_soc_pct
                    FROM batteries WHERE site_id = :sid LIMIT 1"""),
            {"sid": site_id},
        ).mappings().first()
    finally:
        session.close()
    return dict(row) if row else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-id')
    ap.add_argument('--start')
    ap.add_argument('--end')
    ap.add_argument('--seed-tariffs', action='store_true')
    ap.add_argument('--no-meter', action='store_true', help='ignore Octopus readings, use FoxESS only')
    args = ap.parse_args()

    all_sites = sites()
    targets = [s for s in all_sites if not args.site_id or str(s['id']) == args.site_id]
    if not targets:
        raise SystemExit('no matching sites')

    if args.seed_tariffs:
        for s in targets:
            sid = str(s['id'])
            n = seed_tariffs(sid) if sid == STROUD_SITE_ID else seed_from_current(sid)
            print(f"seeded {n} tariff period(s) for {s['name']}")

    for s in targets:
        sid = str(s['id'])
        window = data_window(sid)
        if not window:
            print(f"{s['name']}: no historic data, skipped")
            continue
        first, now = window
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) if args.start else first
        end = (datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) + timedelta(days=1)) if args.end else now

        meter = None if args.no_meter else octopus_meter.fetch_half_hourly(sid, start, end)
        days = cost_history.compute_days(sid, start, end, battery=battery_params(sid), meter=meter)
        if days is None or days.empty:
            print(f"{s['name']}: nothing to write ({start.date()} -> {end.date()})")
            continue
        n = cost_history.upsert_days(sid, days)
        src = 'octopus meter + foxess' if meter else 'foxess'
        print(f"{s['name']}: {n} days {days['day'].min()} -> {days['day'].max()} ({src})")
        print(f"   total value £{days['total_value_gbp'].sum():.2f}  "
              f"solar £{days['solar_value_gbp'].sum():.2f}  "
              f"battery £{days['battery_value_gbp'].sum():.2f}  "
              f"optimiser £{days['optimiser_value_gbp'].sum():.2f}")


if __name__ == '__main__':
    main()
