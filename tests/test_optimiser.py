"""Tests for the battery optimiser (LP solver)."""
import pytest
import pandas as pd
import numpy as np
from app.core.optimiser import (
    mvp_cost_minimiser,
    DEFAULT_CHARGE_EFFICIENCY,
    DEFAULT_DISCHARGE_EFFICIENCY,
)


class TestOptimiser:
    """Test suite for LP battery optimiser."""

    def _build_inputs(self, solar_df, prices_df, demand_profile):
        """Merge fixtures into a single optimiser-ready DataFrame."""
        inputs = solar_df.merge(prices_df, on="period_end", how="left")
        demand_map = demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["period_end"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        return inputs

    def test_optimiser_returns_dataframe(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that optimiser returns a DataFrame with expected columns."""
        inputs = self._build_inputs(sample_solar_df, sample_prices_df, sample_demand_profile)
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        assert isinstance(result, pd.DataFrame)
        expected_cols = [
            "period_end", "demand", "pv_estimate", "price",
            "batt_charge_kwh", "batt_discharge_kwh",
            "grid_import_kwh", "grid_export_kwh",
            "soc_kwh", "soc_pct", "net_battery_kwh", "cost_gbp"
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_optimiser_respects_soc_bounds(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that SOC stays within min/max bounds."""
        inputs = self._build_inputs(sample_solar_df, sample_prices_df, sample_demand_profile)
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        min_soc_kwh = optimiser_params["min_soc_pct"] / 100 * optimiser_params["battery_capacity_kwh"]
        max_soc_kwh = optimiser_params["max_soc_pct"] / 100 * optimiser_params["battery_capacity_kwh"]

        assert (result["soc_kwh"] >= min_soc_kwh - 1e-6).all(), "SOC below minimum"
        assert (result["soc_kwh"] <= max_soc_kwh + 1e-6).all(), "SOC above maximum"

    def test_optimiser_energy_balance(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test energy balance: solar + discharge + import = demand + charge + export + spill."""
        inputs = self._build_inputs(sample_solar_df, sample_prices_df, sample_demand_profile)
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        lhs = result["pv_estimate"] + result["batt_discharge_kwh"] + result["grid_import_kwh"] - result["solar_spill_kwh"]
        rhs = result["demand"] + result["batt_charge_kwh"] + result["grid_export_kwh"]

        # Allow small numerical tolerance
        np.testing.assert_allclose(lhs, rhs, rtol=1e-5, atol=1e-6)

    def test_optimiser_respects_power_limits(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that charge/discharge power limits are respected."""
        inputs = self._build_inputs(sample_solar_df, sample_prices_df, sample_demand_profile)
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        dt = 0.5  # half-hour
        max_charge_energy = optimiser_params["charge_power_kw"] * dt
        max_discharge_energy = optimiser_params["discharge_power_kw"] * dt

        assert (result["batt_charge_kwh"] <= max_charge_energy + 1e-6).all()
        assert (result["batt_discharge_kwh"] <= max_discharge_energy + 1e-6).all()

    def test_optimiser_soc_continuity(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """SOC follows the efficiency-aware balance: SOC[t] = SOC[t-1] + eta_c*charge - discharge/eta_d."""
        inputs = self._build_inputs(sample_solar_df, sample_prices_df, sample_demand_profile)
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        init_soc_kwh = optimiser_params["initial_soc_pct"] / 100 * optimiser_params["battery_capacity_kwh"]

        # Check first period
        expected_soc_0 = (
            init_soc_kwh
            + DEFAULT_CHARGE_EFFICIENCY * result.iloc[0]["batt_charge_kwh"]
            - result.iloc[0]["batt_discharge_kwh"] / DEFAULT_DISCHARGE_EFFICIENCY
        )
        np.testing.assert_allclose(result.iloc[0]["soc_kwh"], expected_soc_0, rtol=1e-5)

        # Check subsequent periods
        for t in range(1, len(result)):
            expected_soc_t = (
                result.iloc[t-1]["soc_kwh"]
                + DEFAULT_CHARGE_EFFICIENCY * result.iloc[t]["batt_charge_kwh"]
                - result.iloc[t]["batt_discharge_kwh"] / DEFAULT_DISCHARGE_EFFICIENCY
            )
            np.testing.assert_allclose(result.iloc[t]["soc_kwh"], expected_soc_t, rtol=1e-5)

    def test_optimiser_charges_at_low_price(self, optimiser_params):
        """Test that optimiser tends to charge during low-price periods."""
        # 4-period scenario: cheap import first, expensive later, zero solar
        # With initial SOC at minimum, optimiser must import to meet demand
        solar = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.0, 0.0, 0.0]
        })
        prices = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "price": [5.0, 5.0, 50.0, 50.0],
            "export_price": [2.0, 2.0, 25.0, 25.0],
        })
        demand_profile = pd.DataFrame({
            "time_of_day": [pd.Timestamp("2025-09-20 00:00").time()] * 4,
            "energy_kwh": [0.5, 0.5, 0.5, 0.5]
        })

        inputs = solar.merge(prices, on="period_end", how="left")
        demand_map = demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["period_end"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=15.0,
            initial_soc_pct=20.0,  # Start at minimum SOC
            min_soc_pct=20.0,
            max_soc_pct=90.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
        )
        # With SOC at minimum, battery can't discharge to meet demand,
        # so it must import. Total import across 4 periods should be
        # higher in cheap periods (0-1) than expensive periods (2-3).
        import_cheap = result.iloc[:2]["grid_import_kwh"].sum()
        import_expensive = result.iloc[2:]["grid_import_kwh"].sum()
        assert import_cheap >= import_expensive, (
            f"Should import more in cheap periods: cheap={import_cheap:.2f}, expensive={import_expensive:.2f}"
        )

    def test_optimiser_initial_soc_set_correctly(self, sample_solar_df, sample_prices_df, sample_demand_profile):
        """Test that initial SOC is set from parameter."""
        inputs = sample_solar_df.merge(sample_prices_df, on="period_end", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["period_end"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=10.0,
            initial_soc_pct=60.0,
            min_soc_pct=20.0,
            max_soc_pct=90.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
        )
        # First SOC should be approximately 60% of 10 kWh
        expected_first_soc = 0.60 * 10.0
        # Account for first period's (efficiency-aware) charge/discharge
        first_net = (
            DEFAULT_CHARGE_EFFICIENCY * result.iloc[0]["batt_charge_kwh"]
            - result.iloc[0]["batt_discharge_kwh"] / DEFAULT_DISCHARGE_EFFICIENCY
        )
        expected_soc_after_first = expected_first_soc + first_net
        np.testing.assert_allclose(result.iloc[0]["soc_kwh"], expected_soc_after_first, rtol=1e-5)

    def _constant_price_inputs(self, n=12, price=20.0, export_price=8.0):
        """Flat-price, no-solar, no-demand inputs — isolates terminal behaviour."""
        periods = pd.date_range("2025-09-20", periods=n, freq="30min", tz="UTC")
        return pd.DataFrame({
            "period_end": periods,
            "pv_estimate": [0.0] * n,
            "price": [price] * n,
            "export_price": [export_price] * n,
            "demand": [0.0] * n,
        })

    def _flat_params(self):
        return dict(
            battery_capacity_kwh=5.0,
            initial_soc_pct=50.0,
            min_soc_pct=20.0,
            max_soc_pct=90.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
        )

    def test_salvage_value_prevents_terminal_dump(self):
        """A salvage value above the export price stops the end-of-horizon dump."""
        inputs = self._constant_price_inputs()

        # No salvage: positive export price and no future obligation → dump to min SOC.
        dumped = mvp_cost_minimiser(inputs_df=inputs, **self._flat_params(), salvage_value_pence=0.0)
        assert dumped["soc_pct"].iloc[-1] < 25.0, (
            f"Without salvage the battery should dump to ~min SOC, got {dumped['soc_pct'].iloc[-1]:.1f}%"
        )

        # Salvage above export price (40p vs 8p export): holding charge is worth
        # more than exporting it, so the battery should stay near its initial SOC.
        held = mvp_cost_minimiser(inputs_df=inputs, **self._flat_params(), salvage_value_pence=40.0)
        assert held["soc_pct"].iloc[-1] > 45.0, (
            f"With salvage above export the battery should hold charge, got {held['soc_pct'].iloc[-1]:.1f}%"
        )

    def test_default_salvage_excludes_synthetic_prices(self):
        """Default salvage = mean of real prices; synthetic tail must not inflate it."""
        from app.core.optimiser import _default_salvage_value_pence
        inputs = self._constant_price_inputs(n=8, price=20.0)
        # Mark the last 4 periods as synthetic (backfilled) at 200p/kWh.
        inputs["is_synthetic"] = [False] * 4 + [True] * 4
        inputs.loc[inputs["is_synthetic"], "price"] = 200.0
        assert _default_salvage_value_pence(inputs) == 20.0

        # Without the flag column, the default is the mean of all prices.
        plain = inputs.drop(columns=["is_synthetic"])
        assert _default_salvage_value_pence(plain) == 110.0  # (4*20 + 4*200)/8

    def test_is_synthetic_propagates_to_result(self):
        """The synthetic flag is carried through to the optimiser output."""
        inputs = self._constant_price_inputs(n=4)
        inputs["is_synthetic"] = [False, False, True, True]
        result = mvp_cost_minimiser(inputs_df=inputs, **self._flat_params())
        assert "is_synthetic" in result.columns
        assert list(result["is_synthetic"]) == [False, False, True, True]


class TestRoundTripEfficiency:
    """§4a — the LP must only cycle when the spread beats the round-trip losses."""

    def _cycle_inputs(self, export_pence):
        """Two periods: sell into period 0, buy back in period 1.

        min == initial == max SOC so the battery can only cycle (never
        stockpile), and the terminal salvage equals the export price so an
        unreplaced dump is cost-neutral. That isolates the arbitrage decision.
        """
        return pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.0],
            "price": [100.0, 27.9],          # import: expensive then 27.9p
            "export_price": [export_pence, 1.0],
            "demand": [0.0, 0.0],
        })

    def _cycle_params(self, **overrides):
        params = dict(
            battery_capacity_kwh=10.0,
            initial_soc_pct=50.0,
            min_soc_pct=20.0,
            max_soc_pct=50.0,   # can't stockpile above the start
            charge_power_kw=10.0,
            discharge_power_kw=10.0,
            salvage_value_pence=29.0,
        )
        params.update(overrides)
        return params

    def test_lossless_would_cycle_on_a_thin_spread(self):
        """Baseline: with no losses the 27.9 -> 29p spread is (barely) worth it."""
        result = mvp_cost_minimiser(
            inputs_df=self._cycle_inputs(29.0),
            **self._cycle_params(charge_efficiency=1.0, discharge_efficiency=1.0),
        )
        assert result["batt_discharge_kwh"].sum() > 1.0, "lossless LP should cycle"

    def test_efficiency_blocks_the_marginal_cycle(self):
        """Tom's case: exporting at 29p to buy back at 27.9p is not worth ~0.90 round-trip."""
        result = mvp_cost_minimiser(
            inputs_df=self._cycle_inputs(29.0), **self._cycle_params()
        )
        assert result["batt_discharge_kwh"].sum() < 0.2, (
            f"efficient LP should not cycle for a 1.1p spread, discharged "
            f"{result['batt_discharge_kwh'].sum():.3f} kWh"
        )

    def test_efficiency_allows_a_wide_spread(self):
        """A spread that clears buy/(eta_c*eta_d) (~30.9p) should still cycle."""
        result = mvp_cost_minimiser(
            inputs_df=self._cycle_inputs(35.0), **self._cycle_params()
        )
        assert result["batt_discharge_kwh"].sum() > 1.0, "wide spread should still arbitrage"

    def test_efficiency_below_one_drains_more_soc_to_export(self):
        """To deliver 1 kWh AC the battery must give up 1/eta_d stored kWh."""
        result = mvp_cost_minimiser(
            inputs_df=self._cycle_inputs(35.0), **self._cycle_params()
        )
        discharge = result["batt_discharge_kwh"].iloc[0]
        soc_drop = self._cycle_params()["initial_soc_pct"] / 100 * 10.0 - result["soc_kwh"].iloc[0]
        np.testing.assert_allclose(
            soc_drop, discharge / DEFAULT_DISCHARGE_EFFICIENCY, rtol=1e-4
        )


class TestGridLimits:
    """§4c — grid import/export decoupled from battery power, plus solar spill."""

    def test_demand_spike_above_battery_power_is_feasible(self):
        """Kettle + oven (4 kWh in a half hour) at min SOC must not make the LP infeasible."""
        inputs = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.0],
            "price": [20.0, 20.0],
            "export_price": [5.0, 5.0],
            "demand": [4.0, 0.5],
        })
        result = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=10.0,
            initial_soc_pct=20.0,
            min_soc_pct=20.0,
            max_soc_pct=100.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
        )
        # Battery can't help (at min SOC), so the grid must cover the spike.
        assert result["grid_import_kwh"].iloc[0] >= 3.9

    def test_grid_limit_binds_and_solar_spills(self):
        """Full battery + huge solar: export is capped at the grid limit, the rest spills."""
        inputs = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "pv_estimate": [10.0, 0.0],   # 20 kW for a half hour
            "price": [20.0, 20.0],
            "export_price": [5.0, 5.0],
            "demand": [0.5, 0.5],
        })
        result = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=10.0,
            initial_soc_pct=100.0,
            min_soc_pct=20.0,
            max_soc_pct=100.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
            grid_limit_kw=5.0,   # export capped at 2.5 kWh per half hour
        )
        assert result["grid_export_kwh"].iloc[0] <= 2.5 + 1e-6
        assert result["solar_spill_kwh"].iloc[0] > 6.0


class TestRobustness:
    """§4e / §4g — below-min start recovery and input validation."""

    def test_initial_soc_below_min_recovers_without_error(self):
        """Starting below min SOC used to be infeasible at t=0."""
        inputs = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.0, 0.0, 0.0],
            "price": [20.0, 20.0, 20.0, 20.0],
            "export_price": [5.0, 5.0, 5.0, 5.0],
            "demand": [0.5, 0.5, 0.5, 0.5],
        })
        result = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=10.0,
            initial_soc_pct=10.0,   # below min
            min_soc_pct=20.0,
            max_soc_pct=100.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
        )
        # No discharge below the start while recovering, and it climbs.
        assert (result["batt_discharge_kwh"] < 1e-6).all()
        assert result["soc_kwh"].iloc[-1] > 1.0

    def test_zero_capacity_raises(self):
        inputs = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.0],
            "price": [20.0, 20.0],
            "export_price": [5.0, 5.0],
            "demand": [0.5, 0.5],
        })
        with pytest.raises(ValueError, match="battery_capacity_kwh"):
            mvp_cost_minimiser(inputs_df=inputs, battery_capacity_kwh=0.0)

    def test_invalid_efficiency_raises(self):
        inputs = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.0],
            "price": [20.0, 20.0],
            "export_price": [5.0, 5.0],
            "demand": [0.5, 0.5],
        })
        with pytest.raises(ValueError, match="efficiency"):
            mvp_cost_minimiser(inputs_df=inputs, charge_efficiency=1.5)
