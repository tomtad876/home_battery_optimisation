"""Persist an optimiser run: the plan, not just the push that followed it.

`optimisation_runs` / `optimisation_intervals` existed but nothing ever wrote
them, so the only record of a decision was the schedule actually pushed. That
made every "did this change help?" question unanswerable. This service stores
the plan for a run — including the prices and solar forecast it was built on —
so plans can be scored against what really happened.

Deliberately NOT wired into the dashboard auto-run (`/optimise/mvp`): that fires
on every page load and would multiply rows for no analytical value.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import text

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

# Columns of optimisation_intervals that come straight from the optimiser
# output, mapped to the name used in the schedule DataFrame.
_INTERVAL_FIELDS = {
    "charge_kwh": "batt_charge_kwh",
    "discharge_kwh": "batt_discharge_kwh",
    "soc_kwh": "soc_kwh",
    "grid_import_kwh": "grid_import_kwh",
    "grid_export_kwh": "grid_export_kwh",
    "cost": "cost_gbp",
    "demand_kwh": "demand",
    # The inputs, not just the outputs: without these the plan can't be scored
    # against what it assumed. Solcast is overwritten on every fetch, so the PV
    # forecast a plan used is unrecoverable unless copied here.
    "price_pence": "price",
    "export_price_pence": "export_price_pence",
    "pv_kwh": "pv_estimate",
}


def _naive_utc(value: Any) -> Any:
    """`period_end` is a timestamptz column in the DB and tz-aware in pandas.

    The intervals table stores `timestamp without time zone`, so convert to
    naive UTC rather than letting the driver guess at the session timezone.
    """
    ts = pd.Timestamp(value)
    if ts is pd.NaT or pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


def build_interval_rows(schedule: pd.DataFrame, run_id: str) -> list[dict]:
    """Turn an optimiser output frame into insertable interval rows.

    Pure (no DB access) so it can be unit-tested without a database.
    """
    rows: list[dict] = []
    skipped = 0
    for record in schedule.to_dict(orient="records"):
        period_end = _naive_utc(record.get("period_end"))
        if period_end is None:
            # period_end is NOT NULL in the table; one bad row would fail the
            # whole run's insert (and lose the plan), so drop it instead.
            skipped += 1
            continue
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "optimisation_run_id": run_id,
            "period_end": period_end,
        }
        for column, source in _INTERVAL_FIELDS.items():
            value = record.get(source)
            row[column] = None if value is None or pd.isna(value) else float(value)
        synthetic = record.get("is_synthetic")
        row["is_synthetic"] = None if synthetic is None or pd.isna(synthetic) else bool(synthetic)
        rows.append(row)
    if skipped:
        logger.warning("dropped %d optimiser interval(s) with no period_end for run %s", skipped, run_id)
    return rows


def persist_optimisation_run(
    site_id: str,
    schedule: pd.DataFrame,
    *,
    trigger_source: str,
    initial_soc_pct: float,
    battery_capacity_kwh: float,
    total_cost_estimate: float | None = None,
    total_cost_estimate_real: float | None = None,
    salvage_value_pence: float | None = None,
    status: str = "pending",
) -> str | None:
    """Store one optimiser plan and its 30-minute intervals.

    Returns the run id, or None if persistence failed. A failed write must not
    take the battery offline, so the caller keeps the plan either way — but the
    failure is logged loudly (Sentry picks up `logger.error`) instead of being
    swallowed, which is how `schedules` stayed silently empty for a week.

    `status` starts as "pending": the caller (or the Edge Function, on the cron
    path) sets it once it knows whether the plan was actually pushed. A run left
    at "pending" is therefore a push that never reported back.
    """
    run_id = str(uuid.uuid4())
    initial_soc_kwh = (initial_soc_pct / 100.0) * battery_capacity_kwh
    rows = build_interval_rows(schedule, run_id)

    session = SessionLocal()
    try:
        session.execute(
            text(
                """INSERT INTO optimisation_runs
                       (id, site_id, initial_soc_kwh, total_cost_estimate,
                        total_cost_estimate_real, status, trigger_source,
                        salvage_value_pence)
                   VALUES
                       (:id, :site_id, :initial_soc_kwh, :total_cost_estimate,
                        :total_cost_estimate_real, :status, :trigger_source,
                        :salvage_value_pence)"""
            ),
            {
                "id": run_id,
                "site_id": site_id,
                "initial_soc_kwh": initial_soc_kwh,
                "total_cost_estimate": total_cost_estimate,
                "total_cost_estimate_real": total_cost_estimate_real,
                "status": status,
                "trigger_source": trigger_source,
                "salvage_value_pence": salvage_value_pence,
            },
        )
        if rows:
            session.execute(
                text(
                    """INSERT INTO optimisation_intervals
                           (id, optimisation_run_id, period_end, charge_kwh,
                            discharge_kwh, soc_kwh, grid_import_kwh,
                            grid_export_kwh, cost, demand_kwh, is_synthetic,
                            price_pence, export_price_pence, pv_kwh)
                       VALUES
                           (:id, :optimisation_run_id, :period_end, :charge_kwh,
                            :discharge_kwh, :soc_kwh, :grid_import_kwh,
                            :grid_export_kwh, :cost, :demand_kwh, :is_synthetic,
                            :price_pence, :export_price_pence, :pv_kwh)"""
                ),
                rows,
            )
        session.commit()
        return run_id
    except Exception:
        session.rollback()
        logger.error(
            "optimisation run not persisted (site=%s trigger=%s) — plan was still used",
            site_id,
            trigger_source,
            exc_info=True,
        )
        return None
    finally:
        session.close()


def mark_run_status(run_id: str | None, status: str) -> None:
    """Record the push outcome on an existing run. Never raises.

    A run that is inserted but never updated stays "pending", which is a signal
    in itself (the push path died before reporting).
    """
    if not run_id:
        return
    session = SessionLocal()
    try:
        session.execute(
            text("UPDATE optimisation_runs SET status = :status WHERE id = :id"),
            {"id": run_id, "status": status},
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.error("could not mark optimisation run %s as %s", run_id, status, exc_info=True)
    finally:
        session.close()
