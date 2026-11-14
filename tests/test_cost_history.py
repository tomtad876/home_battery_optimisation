"""Tests for the cost-history layers and the self-use battery simulation.

The attribution identity is the thing worth protecting:

    solar_value + battery_value + optimiser_value == total_value

If that ever stops holding, the dashboard is lying about which bit saved what.
"""
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.services import cost_history as ch


class TestSelfUseSimulation:
    def test_charges_only_from_surplus(self):
        """A 'self-use' battery never imports in order to charge."""
        pv = pd.Series([0.0, 0.0])
        load = pd.Series([1.0, 1.0])
        out = ch.simulate_selfuse(pv, load, {"capacity_kwh": 5.0}, start_soc_pct=50)
        # 2.5 kWh stored: slot 1 covered from the battery, slot 2 runs into the
        # 20% floor and imports the remainder
        assert out["self_import_kwh"].iloc[0] == pytest.approx(0.0)
        assert out["self_import_kwh"].iloc[1] == pytest.approx(0.575, abs=1e-3)
        assert out["self_soc_kwh"].is_monotonic_decreasing

    def test_surplus_charges_then_exports_the_rest(self):
        pv = pd.Series([4.0, 0.0])
        load = pd.Series([1.0, 1.0])
        out = ch.simulate_selfuse(pv, load, {"capacity_kwh": 5.0, "max_charge_kw": 3.0},
                                  start_soc_pct=20)
        # slot 1: 3 kWh surplus; 3 kW * 0.5h = 1.5 kWh can be absorbed
        assert out["self_import_kwh"].iloc[0] == 0
        assert out["self_export_kwh"].iloc[0] == pytest.approx(1.5, abs=1e-6)
        # slot 2: deficit 1 kWh, battery has ~1.425 kWh in -> covers it
        assert out["self_import_kwh"].iloc[1] == pytest.approx(0.0, abs=1e-6)

    def test_never_discharges_below_floor_after_losses(self):
        load = pd.Series([3.0] * 8)
        pv = pd.Series([0.0] * 8)
        out = ch.simulate_selfuse(pv, load, {"capacity_kwh": 5.0, "min_soc_pct": 20.0},
                                  start_soc_pct=100)
        floor = 5.0 * 0.20
        assert out["self_soc_kwh"].min() >= floor - 1e-6
        # ends near the floor and imports the rest
        assert out["self_import_kwh"].sum() > 0

    def test_respects_power_limit(self):
        load = pd.Series([10.0])
        pv = pd.Series([0.0])
        out = ch.simulate_selfuse(pv, load, {"max_discharge_kw": 3.0}, start_soc_pct=100)
        assert out["self_import_kwh"].iloc[0] == pytest.approx(8.5)  # 3 kW * 0.5h covered

    def test_capacity_headroom_is_respected(self):
        pv = pd.Series([10.0, 10.0, 10.0, 10.0])
        load = pd.Series([0.0, 0.0, 0.0, 0.0])
        out = ch.simulate_selfuse(pv, load, {"capacity_kwh": 5.0, "max_charge_kw": 3.0},
                                  start_soc_pct=20)
        assert out["self_soc_kwh"].max() <= 5.0 + 1e-6


class TestDstDays:
    def test_dst_days_are_not_48_slots(self):
        assert ch.expected_slots_for(date(2026, 10, 25)) == 50   # clocks go back
        assert ch.expected_slots_for(date(2026, 3, 29)) == 46    # clocks go forward
        assert ch.expected_slots_for(date(2026, 11, 14)) == 48
        assert ch._is_dst_day(date(2026, 10, 25)) is True
        assert ch._is_dst_day(date(2026, 11, 14)) is False


class TestLayerIdentity:
    def _days(self, monkeypatch, pv, load, imp_kwh, exp_kwh, imp_p=20.0, exp_p=10.0):
        # a whole local day, so the rows are 48 slots (a UTC-aligned window
        # straddles local midnight and splits into two partial days)
        slots = pd.date_range("2026-06-01", periods=48, freq="30min",
                              tz="Europe/London").tz_convert("UTC")
        frame = pd.DataFrame({
            "pv_kwh": pv, "load_kwh": load,
            "fox_import_kwh": imp_kwh, "fox_export_kwh": exp_kwh,
            "soc_pct": [50.0] * 48,
        }, index=slots)

        monkeypatch.setattr(ch, "load_series", lambda *a, **k: frame)
        monkeypatch.setattr(ch, "resolve_rates",
                            lambda site, idx: pd.DataFrame({"import_pence": imp_p,
                                                            "export_pence": exp_p}, index=idx))
        monkeypatch.setattr(ch, "standing_pence_for", lambda site, day: 58.63)
        return ch.compute_days("site", slots[0].to_pydatetime(), slots[-1].to_pydatetime())

    def test_layers_sum_to_total(self, monkeypatch):
        pv = [max(0.0, 2 * (1 - abs((i - 24) / 24))) for i in range(48)]
        load = [0.3] * 48
        imp = [0.1] * 48
        exp = [0.2] * 48
        days = self._days(monkeypatch, pv, load, imp, exp)
        row = days.iloc[0]
        assert row["total_value_gbp"] == pytest.approx(
            row["solar_value_gbp"] + row["battery_value_gbp"] + row["optimiser_value_gbp"], abs=1e-9)
        assert row["total_value_gbp"] == pytest.approx(
            row["nokit_cost_gbp"] - row["net_cost_gbp"], abs=1e-9)

    def test_standing_charge_is_in_every_layer_and_never_in_the_saving(self, monkeypatch):
        """It must cancel: adding standing to the baseline must not create savings."""
        pv = [0.0] * 48
        load = [1.0] * 48
        imp = [1.0] * 48   # meter agrees with the modelled load
        exp = [0.0] * 48
        days = self._days(monkeypatch, pv, load, imp, exp)
        row = days.iloc[0]
        # no PV, no shifting to do: every layer costs the same, so the standing
        # charge must vanish from the delta
        assert row["standing_gbp"] == pytest.approx(0.5863, abs=1e-6)
        assert row["nokit_cost_gbp"] == pytest.approx(row["net_cost_gbp"], abs=1e-6)
        assert row["total_value_gbp"] == pytest.approx(0.0, abs=1e-6)

    def test_no_kit_is_load_at_import_price(self, monkeypatch):
        pv = [0.0] * 48
        load = [1.0] * 48
        days = self._days(monkeypatch, pv, load, [1.0] * 48, [0.0] * 48, imp_p=20.0)
        row = days.iloc[0]
        assert row["nokit_cost_gbp"] == pytest.approx(48 * 1.0 * 0.20 + 0.5863, abs=1e-6)


class TestTariffShaping:
    def test_period_becomes_resolvable_tariff(self):
        period = {
            "import_type": "fixed", "export_type": "fixed",
            "import_config": {"flat_pence": 24.5, "standing_pence": 58.63},
            "export_config": {"flat_pence": 12.0},
        }
        tariff = ch._period_tariff(period)
        assert tariff["import_type"] == "fixed"
        assert tariff["export_type"] == "fixed"
        assert tariff["import"]["flat_pence"] == 24.5
        assert tariff["export"]["flat_pence"] == 12.0
