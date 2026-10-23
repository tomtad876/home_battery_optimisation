"""Terminal value curve (Stage 3): a concave value of stored energy.

A flat salvage values every stored kWh the same. The curve says the last kWh
before empty is worth more than the last kWh before full — the reservoir
intuition. These tests cover the helper and its effect on the plan.
"""
import numpy as np
import pandas as pd

from app.core.optimiser import mvp_cost_minimiser, resolve_value_curve


def _frame(price=25.0, export=12.0, n=96):
    idx = pd.date_range("2026-10-22", periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({
        "period_end": idx,
        "price": np.full(n, price),
        "export_price": np.full(n, export),
        "pv_estimate": 0.0,
        "demand": 0.3,
    })


class TestResolveValueCurve:
    def test_slopes_decrease(self):
        width, slopes = resolve_value_curve(_frame(), 5.0, 5)
        assert width == 1.0
        assert slopes == sorted(slopes, reverse=True)

    def test_explicit_bounds(self):
        width, slopes = resolve_value_curve(_frame(), 5.0, 5, high_pence=58, low_pence=12)
        assert slopes[0] == 58 and slopes[-1] == 12
        assert len(slopes) == 5

    def test_defaults_from_horizon(self):
        # P90 of a flat series is the flat price; P10 export likewise.
        _, slopes = resolve_value_curve(_frame(price=40.0, export=10.0), 5.0, 5)
        assert slopes[0] == 40.0 and slopes[-1] == 10.0

    def test_segment_width_scales_with_capacity(self):
        width, _ = resolve_value_curve(_frame(), 10.0, 5)
        assert width == 2.0


class TestValueCurveEffect:
    def test_curve_holds_a_core_reserve(self):
        """With low-SOC energy valued above the flat price, the LP keeps a core
        reserve and discharges the surplus instead of holding everything."""
        df = _frame(price=25.0, export=12.0)
        flat = mvp_cost_minimiser(
            inputs_df=df, battery_capacity_kwh=5.0, initial_soc_pct=90.0,
            min_soc_pct=20.0, max_soc_pct=100.0,
        )
        curve = mvp_cost_minimiser(
            inputs_df=df, battery_capacity_kwh=5.0, initial_soc_pct=90.0,
            min_soc_pct=20.0, max_soc_pct=100.0,
            value_curve_segments=5, value_curve_high_pence=58, value_curve_low_pence=12,
        )
        # The curve sells the high-SOC (cheap) surplus, so it ends below flat...
        assert curve["soc_pct"].iloc[-1] < flat["soc_pct"].iloc[-1]
        # ...but never dumps into the floor: it keeps the precious low-SOC core.
        assert curve["soc_pct"].min() > 20.0

    def test_curve_plan_is_feasible(self):
        df = _frame(price=25.0, export=12.0)
        out = mvp_cost_minimiser(
            inputs_df=df, battery_capacity_kwh=5.0, initial_soc_pct=50.0,
            min_soc_pct=20.0, max_soc_pct=100.0, value_curve_segments=5,
        )
        assert out["soc_pct"].between(19.9, 100.1).all()
        # energy balance: grid = demand - pv + charge - discharge
        grid = out["grid_import_kwh"] - out["grid_export_kwh"]
        expected = out["demand"] - out["pv_estimate"] + out["batt_charge_kwh"] - out["batt_discharge_kwh"]
        np.testing.assert_allclose(grid, expected, atol=1e-6)
