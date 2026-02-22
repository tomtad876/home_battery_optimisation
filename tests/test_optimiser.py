"""Tests for the battery optimiser (LP solver)."""
import pytest
import pandas as pd
import numpy as np
from app.core.optimiser import mvp_cost_minimiser


class TestOptimiser:
    """Test suite for LP battery optimiser."""

    def test_optimiser_returns_dataframe(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that optimiser returns a DataFrame with expected columns."""
        # build single inputs_df from fixtures
        inputs = sample_solar_df.merge(sample_prices_df, on="PeriodEnd", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        assert isinstance(result, pd.DataFrame)
        expected_cols = [
            "PeriodEnd", "demand", "solar", "price",
            "batt_charge_kwh", "batt_discharge_kwh",
            "grid_import_kwh", "grid_export_kwh",
            "soc_kwh", "soc_pct", "net_battery_kwh", "cost_gbp"
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_optimiser_respects_soc_bounds(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that SOC stays within min/max bounds."""
        inputs = sample_solar_df.merge(sample_prices_df, on="PeriodEnd", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        min_soc_kwh = optimiser_params["min_soc_pct"] / 100 * optimiser_params["battery_capacity_kwh"]
        max_soc_kwh = optimiser_params["max_soc_pct"] / 100 * optimiser_params["battery_capacity_kwh"]
        
        assert (result["soc_kwh"] >= min_soc_kwh - 1e-6).all(), "SOC below minimum"
        assert (result["soc_kwh"] <= max_soc_kwh + 1e-6).all(), "SOC above maximum"

    def test_optimiser_energy_balance(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test energy balance: solar + discharge + import = demand + charge + export."""
        inputs = sample_solar_df.merge(sample_prices_df, on="PeriodEnd", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        lhs = result["solar"] + result["batt_discharge_kwh"] + result["grid_import_kwh"]
        rhs = result["demand"] + result["batt_charge_kwh"] + result["grid_export_kwh"]
        
        # Allow small numerical tolerance
        np.testing.assert_allclose(lhs, rhs, rtol=1e-5, atol=1e-6)

    def test_optimiser_respects_power_limits(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that charge/discharge power limits are respected."""
        inputs = sample_solar_df.merge(sample_prices_df, on="PeriodEnd", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        dt = 0.5  # half-hour
        max_charge_energy = optimiser_params["charge_power_kw"] * dt
        max_discharge_energy = optimiser_params["discharge_power_kw"] * dt
        
        assert (result["batt_charge_kwh"] <= max_charge_energy + 1e-6).all()
        assert (result["batt_discharge_kwh"] <= max_discharge_energy + 1e-6).all()

    def test_optimiser_soc_continuity(self, sample_solar_df, sample_prices_df, sample_demand_profile, optimiser_params):
        """Test that SOC follows balance equation: SOC[t] = SOC[t-1] + charge - discharge."""
        inputs = sample_solar_df.merge(sample_prices_df, on="PeriodEnd", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        init_soc_kwh = optimiser_params["initial_soc_pct"] / 100 * optimiser_params["battery_capacity_kwh"]
        
        # Check first period
        expected_soc_0 = init_soc_kwh + result.iloc[0]["batt_charge_kwh"] - result.iloc[0]["batt_discharge_kwh"]
        np.testing.assert_allclose(result.iloc[0]["soc_kwh"], expected_soc_0, rtol=1e-5)
        
        # Check subsequent periods
        for t in range(1, len(result)):
            expected_soc_t = result.iloc[t-1]["soc_kwh"] + result.iloc[t]["batt_charge_kwh"] - result.iloc[t]["batt_discharge_kwh"]
            np.testing.assert_allclose(result.iloc[t]["soc_kwh"], expected_soc_t, rtol=1e-5)

    def test_optimiser_charges_at_low_price(self, optimiser_params):
        """Test that optimiser tends to charge during low-price periods."""
        # Create scenario: 2 periods, cheap then expensive
        solar = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "PvEstimate": [0.0, 0.0]  # No solar
        })
        prices = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "price": [10.0, 50.0]  # Cheap, then expensive
        })
        demand_profile = pd.DataFrame({
            "time_of_day": [pd.Timestamp("2025-09-20 00:00").time()] * 2,
            "energy_kwh": [0.5, 0.5]
        })
        
        # build inputs_df for the two-period scenario
        inputs = solar.merge(prices, on="PeriodEnd", how="left")
        demand_map = demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(inputs_df=inputs, **optimiser_params)
        # In period 0 (cheap), battery should charge (net battery > 0); period 1 should discharge
        assert result.iloc[0]["net_battery_kwh"] > 0, "Should charge battery in cheap period"

    def test_optimiser_initial_soc_set_correctly(self, sample_solar_df, sample_prices_df, sample_demand_profile):
        """Test that initial SOC is set from parameter."""
        inputs = sample_solar_df.merge(sample_prices_df, on="PeriodEnd", how="left")
        demand_map = sample_demand_profile.set_index("time_of_day")["energy_kwh"].to_dict()
        inputs["demand"] = inputs["PeriodEnd"].dt.time.map(lambda t: demand_map.get(t, 0.5))
        result = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=10.0,
            initial_soc_pct=60.0,
            min_soc_pct=20.0,
            max_soc_pct=90.0,
            charge_power_kw=3.0,
            discharge_power_kw=3.0,
            export_price_pence=15.0,
        )
        # First SOC should be approximately 60% of 10 kWh
        expected_first_soc = 0.60 * 10.0
        # Account for first period's charge/discharge
        first_net = result.iloc[0]["batt_charge_kwh"] - result.iloc[0]["batt_discharge_kwh"]
        expected_soc_after_first = expected_first_soc + first_net
        np.testing.assert_allclose(result.iloc[0]["soc_kwh"], expected_soc_after_first, rtol=1e-5)
