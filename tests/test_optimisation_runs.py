"""Tests for persisting optimiser runs (the plan, not just the push)."""
import logging

import pandas as pd
import pytest

from app.services import optimisation_runs as runs


def _schedule(n=4, tz="UTC"):
    periods = pd.date_range("2026-10-21 12:00", periods=n, freq="30min", tz=tz)
    rows = []
    for i, p in enumerate(periods):
        rows.append({
            "period_end": p,
            "demand": 0.5 + i * 0.1,
            "batt_charge_kwh": 0.25 * i,
            "batt_discharge_kwh": 0.0,
            "soc_kwh": 2.0 + i * 0.1,
            "grid_import_kwh": 0.4,
            "grid_export_kwh": 0.0,
            "cost_gbp": 0.1 * i,
            "is_synthetic": i == n - 1,
            # the inputs the plan was built on
            "price": 30.0 + i,
            "export_price_pence": 12.0,
            "pv_estimate": 0.8,
        })
    return pd.DataFrame(rows)


class _FakeSession:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, params=None):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append((str(statement), params))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class TestBuildIntervalRows:
    def test_maps_optimiser_columns_to_table_columns(self):
        rows = runs.build_interval_rows(_schedule(2), "run-1")
        assert len(rows) == 2
        first = rows[0]
        assert first["charge_kwh"] == 0.0
        assert first["discharge_kwh"] == 0.0
        assert first["cost"] == 0.0
        assert first["demand_kwh"] == 0.5
        assert first["optimisation_run_id"] == "run-1"
        assert first["is_synthetic"] is False
        assert rows[1]["is_synthetic"] is True
        assert rows[0]["id"] != rows[1]["id"]

    def test_persists_the_inputs_the_plan_was_built_on(self):
        """Prices and PV forecast must be stored with the plan, not just re-joinable."""
        row = runs.build_interval_rows(_schedule(2), "run-1")[0]
        assert row["price_pence"] == 30.0
        assert row["export_price_pence"] == 12.0
        assert row["pv_kwh"] == 0.8

    def test_rows_without_period_end_are_dropped_not_fatal(self):
        """period_end is NOT NULL; one NaT must not lose the whole plan."""
        schedule = _schedule(3)
        schedule.loc[1, "period_end"] = pd.NaT
        rows = runs.build_interval_rows(schedule, "run-1")
        assert len(rows) == 2

    def test_period_end_is_naive_utc(self):
        rows = runs.build_interval_rows(_schedule(1, tz="Europe/London"), "run-1")
        period = rows[0]["period_end"]
        assert period.tzinfo is None
        # 12:00 London in October = 11:00 UTC (BST).
        assert (period.hour, period.minute) == (11, 0)

    def test_missing_and_nan_values_become_null(self):
        schedule = _schedule(1)
        schedule.loc[0, "demand"] = float("nan")
        schedule = schedule.drop(columns=["is_synthetic"])
        row = runs.build_interval_rows(schedule, "run-1")[0]
        assert row["demand_kwh"] is None
        assert row["is_synthetic"] is None


class TestPersistRun:
    def test_writes_run_then_intervals(self, monkeypatch):
        fake = _FakeSession()
        monkeypatch.setattr(runs, "SessionLocal", lambda: fake)

        run_id = runs.persist_optimisation_run(
            "site-1",
            _schedule(4),
            trigger_source="cron",
            initial_soc_pct=40.0,
            battery_capacity_kwh=5.0,
            total_cost_estimate=1.23,
            total_cost_estimate_real=1.0,
            salvage_value_pence=33.5,
        )

        assert run_id is not None
        assert fake.committed and not fake.rolled_back and fake.closed
        assert len(fake.calls) == 2

        run_params = fake.calls[0][1]
        assert run_params["id"] == run_id
        assert run_params["site_id"] == "site-1"
        assert run_params["initial_soc_kwh"] == pytest.approx(2.0)  # 40% of 5 kWh
        assert run_params["trigger_source"] == "cron"
        assert run_params["salvage_value_pence"] == 33.5
        assert run_params["total_cost_estimate"] == 1.23
        assert run_params["total_cost_estimate_real"] == 1.0
        assert run_params["status"] == "pending"

        interval_rows = fake.calls[1][1]
        assert len(interval_rows) == 4
        assert all(r["optimisation_run_id"] == run_id for r in interval_rows)

    def test_failure_is_logged_and_does_not_raise(self, monkeypatch, caplog):
        fake = _FakeSession(fail=True)
        monkeypatch.setattr(runs, "SessionLocal", lambda: fake)

        with caplog.at_level(logging.ERROR):
            run_id = runs.persist_optimisation_run(
                "site-1",
                _schedule(2),
                trigger_source="cron",
                initial_soc_pct=40.0,
                battery_capacity_kwh=5.0,
            )

        assert run_id is None
        assert fake.rolled_back and fake.closed
        assert any("not persisted" in r.message for r in caplog.records)


class TestMarkRunStatus:
    def test_updates_status_for_a_known_run(self, monkeypatch):
        fake = _FakeSession()
        monkeypatch.setattr(runs, "SessionLocal", lambda: fake)

        runs.mark_run_status("run-1", "push_failed")

        assert fake.committed and fake.closed
        params = fake.calls[0][1]
        assert params == {"id": "run-1", "status": "push_failed"}

    def test_no_run_id_is_a_no_op(self, monkeypatch):
        fake = _FakeSession()
        monkeypatch.setattr(runs, "SessionLocal", lambda: fake)

        runs.mark_run_status(None, "ok")

        assert fake.calls == []
        assert not fake.committed

    def test_failure_is_logged_not_raised(self, monkeypatch, caplog):
        fake = _FakeSession(fail=True)
        monkeypatch.setattr(runs, "SessionLocal", lambda: fake)

        with caplog.at_level(logging.ERROR):
            runs.mark_run_status("run-1", "ok")

        assert fake.rolled_back and fake.closed
        assert any("could not mark" in r.message for r in caplog.records)
