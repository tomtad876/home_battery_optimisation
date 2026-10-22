"""Price-aware reserve floor (Stage 1 of the smarter-battery ladder).

The reserve is the SOC the battery may not discharge below. These tests cover
the helper that raises it with the next-24h price peak, and the optimiser
behaviour that follows: a day with an expensive evening should arrive at it
holding more charge than a cheap day.
"""
import pandas as pd
import numpy as np

from app.core.optimiser import (
    mvp_cost_minimiser,
    resolve_reserve_floor_pct,
)


def _frame(prices, n=None):
    prices = np.asarray(prices, dtype=float)
    periods = pd.date_range("2026-10-22 00:00", periods=len(prices), freq="30min", tz="UTC")
    return pd.DataFrame({
        "period_end": periods,
        "price": prices,
        "export_price": prices * 0.5,
        "pv_estimate": 0.0,
        "demand": 0.3,
    })


def _peak_day():
    """10p overnight, a sharp 80p peak (3 slots), then 15p — 96 slots (48h)."""
    prices = np.full(96, 15.0)
    prices[:17] = 10.0
    prices[17:20] = 80.0
    return _frame(prices)


class TestResolveReserveFloorPct:
    def test_cheap_day_keeps_base_floor(self):
        assert resolve_reserve_floor_pct(_frame(np.full(48, 20.0))) == 20.0

    def test_peak_at_reference_is_base(self):
        prices = np.full(48, 20.0)
        prices[10] = 30.0
        assert resolve_reserve_floor_pct(_frame(prices)) == 20.0

    def test_expensive_peak_raises_floor(self):
        # 20 + 1.5 * (55 - 30) = 57.5
        prices = np.full(48, 20.0)
        prices[10] = 55.0
        assert resolve_reserve_floor_pct(_frame(prices)) == 57.5

    def test_floor_is_capped(self):
        # 20 + 1.5 * (90 - 30) = 110 -> capped at 80
        prices = np.full(48, 20.0)
        prices[10] = 90.0
        assert resolve_reserve_floor_pct(_frame(prices)) == 80.0

    def test_peak_beyond_24h_is_ignored(self):
        # 48 slots = 24h. A peak at slot 49+ is outside the reserve window.
        prices = np.full(96, 20.0)
        prices[49] = 90.0
        assert resolve_reserve_floor_pct(_frame(prices)) == 20.0

    def test_synthetic_prices_are_ignored(self):
        df = _frame(np.full(96, 20.0))
        df["is_synthetic"] = False
        # A backfilled 90p "typical day" tail must not set the floor.
        df.loc[50:, "is_synthetic"] = True
        df.loc[50:, "price"] = 90.0
        assert resolve_reserve_floor_pct(df) == 20.0

    def test_empty_prices_return_min(self):
        assert resolve_reserve_floor_pct(_frame([])) == 20.0


class TestOptimiserReserve:
    def test_holds_more_before_an_expensive_peak(self):
        df = _peak_day()
        auto = mvp_cost_minimiser(
            inputs_df=df, battery_capacity_kwh=5.0, initial_soc_pct=90.0,
            min_soc_pct=20.0, max_soc_pct=100.0,
        )
        disabled = mvp_cost_minimiser(
            inputs_df=df, battery_capacity_kwh=5.0, initial_soc_pct=90.0,
            min_soc_pct=20.0, max_soc_pct=100.0, reserve_floor_pct=20.0,
        )
        # 80p peak -> auto floor capped at 80%. Off -> free to drain to 20%.
        assert auto["soc_pct"].min() >= 75.0
        assert disabled["soc_pct"].min() < 30.0

    def test_explicit_reserve_floor_is_respected(self):
        out = mvp_cost_minimiser(
            inputs_df=_peak_day(), battery_capacity_kwh=5.0, initial_soc_pct=90.0,
            min_soc_pct=20.0, max_soc_pct=100.0, reserve_floor_pct=80.0,
        )
        assert out["soc_pct"].min() >= 75.0

    def test_configured_min_soc_still_binds(self):
        # A user min of 40% must never be undercut even on a cheap day.
        out = mvp_cost_minimiser(
            inputs_df=_frame(np.full(96, 15.0)), battery_capacity_kwh=5.0,
            initial_soc_pct=90.0, min_soc_pct=40.0, max_soc_pct=100.0,
        )
        assert out["soc_pct"].min() >= 39.0
