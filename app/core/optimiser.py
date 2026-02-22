"""
Linear programming battery optimiser using CVXPY.
Minimises cost subject to energy balance, SOC bounds, and power constraints.
"""
import cvxpy as cp
import pandas as pd
import numpy as np


def mvp_cost_minimiser(
    inputs_df: pd.DataFrame,
    battery_capacity_kwh: float = 15.0,
    initial_soc_pct: float = 50.0,
    min_soc_pct: float = 20.0,
    max_soc_pct: float = 90.0,
    charge_power_kw: float = 3.0,
    discharge_power_kw: float = 3.0,
    export_price_pence: float = 15.0,
) -> pd.DataFrame:
    """
    Linear programming optimiser: minimise electricity cost over forecast horizon.

    Solves a convex optimisation problem to determine optimal battery
    charge/discharge schedule given solar forecast, prices, and demand.

    Args:
        inputs_df: DataFrame with period_end (UTC), pv_estimate (kWh), price (pence/kWh), and demand (kWh)
        battery_capacity_kwh: Total battery capacity
        initial_soc_pct: Starting state of charge %
        min_soc_pct, max_soc_pct: Bounds on SOC
        charge_power_kw: Max charge power (kW)
        discharge_power_kw: Max discharge power (kW)
        export_price_pence: Fixed export price

    Returns:
        DataFrame with columns: period_end, demand, pv_estimate, price, batt_charge_kwh,
                                batt_discharge_kwh, grid_import_kwh, grid_export_kwh,
                                soc_kwh, soc_pct, net_battery_kwh, cost_gbp
    """
    inputs_df = inputs_df.sort_values("period_end").reset_index(drop=True)

    # Ensure we only keep rows with finite price, solar and demand values
    numeric_cols = [c for c in ["price", "pv_estimate", "demand"] if c in inputs_df.columns]
    if not numeric_cols:
        raise ValueError("Missing numeric columns (price/pv_estimate/demand) in inputs data")
    mask = inputs_df[numeric_cols].notna().all(axis=1)
    # also ensure values are finite
    for c in numeric_cols:
        mask &= np.isfinite(inputs_df[c])
    dropped = (~mask).sum()
    if dropped > 0:
        # drop any rows where we don't have complete finite data
        inputs_df = inputs_df.loc[mask].reset_index(drop=True)
    if inputs_df.empty:
        raise ValueError("No overlapping data available for optimisation after joining solar, price and demand")
    # fill any remaining small missing solar/demand values with conservative defaults
    if "pv_estimate" in inputs_df.columns:
        inputs_df["pv_estimate"] = inputs_df["pv_estimate"].fillna(0.0)
    if "demand" in inputs_df.columns:
        inputs_df["demand"] = inputs_df["demand"].fillna(0.5)

    n = len(inputs_df)
    import_prices = inputs_df["price"].values / 100.0  # Convert pence to £/kWh
    solar_gen = inputs_df["pv_estimate"].values
    demand = inputs_df["demand"].values
    export_price_gbp = export_price_pence / 100.0

    # Battery and system parameters
    dt = 0.5  # half-hour in hours
    max_batt_charge_energy = charge_power_kw * dt
    max_batt_discharge_energy = discharge_power_kw * dt
    soc_min_kwh = (min_soc_pct / 100.0) * battery_capacity_kwh
    soc_max_kwh = (max_soc_pct / 100.0) * battery_capacity_kwh
    init_soc_kwh = (initial_soc_pct / 100.0) * battery_capacity_kwh

    # Decision variables
    b_charge = cp.Variable(n, nonneg=True)  # Battery charge (kWh)
    b_discharge = cp.Variable(n, nonneg=True)  # Battery discharge (kWh)
    g_import = cp.Variable(n, nonneg=True)  # Grid import (kWh)
    g_export = cp.Variable(n, nonneg=True)  # Grid export (kWh)
    soc = cp.Variable(n)  # State of charge (kWh)

    constraints = []

    # SOC dynamics and bounds
    for t in range(n):
        # SOC balance: SOC[t] = SOC[t-1] + charge[t] - discharge[t]
        if t == 0:
            constraints.append(soc[t] == init_soc_kwh + b_charge[t] - b_discharge[t])
        else:
            constraints.append(soc[t] == soc[t - 1] + b_charge[t] - b_discharge[t])

        # SOC bounds
        constraints.append(soc[t] >= soc_min_kwh)
        constraints.append(soc[t] <= soc_max_kwh)

        # Power limits
        constraints.append(b_charge[t] <= max_batt_charge_energy)
        constraints.append(b_discharge[t] <= max_batt_discharge_energy)

        # Grid limits (same as battery for simplicity)
        constraints.append(g_import[t] <= max_batt_charge_energy)
        constraints.append(g_export[t] <= max_batt_discharge_energy)

        # Energy balance: solar + discharge + import = demand + charge + export
        constraints.append(
            solar_gen[t] + b_discharge[t] + g_import[t] - b_charge[t] - g_export[t] == demand[t]
        )

    # Objective: minimise cost with small grid penalty
    grid_penalty_weight = 0.001
    penalty = grid_penalty_weight * cp.sum(g_import + g_export)
    cost = cp.sum(cp.multiply(g_import, import_prices) - g_export * export_price_gbp) + penalty
    # Small incentive to charge in periods where future prices are higher
    try:
        future_max_price = float(import_prices.max())
        price_diff = future_max_price - import_prices
        alpha = 0.01
        cost = cost - alpha * cp.sum(cp.multiply(b_charge, price_diff))
    except Exception:
        pass

    problem = cp.Problem(cp.Minimize(cost), constraints)
    problem.solve(verbose=False)

    if problem.status != cp.OPTIMAL:
        raise ValueError(f"Optimisation failed: {problem.status}")

    # Build results DataFrame
    timestep_cost = g_import.value * import_prices - g_export.value * export_price_gbp
    soc_pct = (soc.value / battery_capacity_kwh) * 100

    result_df = inputs_df[["period_end"]].copy()
    result_df["demand"] = demand
    result_df["pv_estimate"] = solar_gen
    result_df["price"] = inputs_df["price"]
    # Compute net battery and grid flows and present only net charging OR discharging
    eps = 1e-3
    net_batt = (b_charge.value - b_discharge.value)
    disp_batt_charge = np.where(net_batt > eps, net_batt, 0.0)
    disp_batt_discharge = np.where(net_batt < -eps, -net_batt, 0.0)

    net_grid = (g_import.value - g_export.value)
    disp_grid_import = np.where(net_grid > eps, net_grid, 0.0)
    disp_grid_export = np.where(net_grid < -eps, -net_grid, 0.0)

    result_df["batt_charge_kwh"] = disp_batt_charge
    result_df["batt_discharge_kwh"] = disp_batt_discharge
    result_df["grid_import_kwh"] = disp_grid_import
    result_df["grid_export_kwh"] = disp_grid_export
    result_df["soc_kwh"] = soc.value
    result_df["soc_pct"] = soc_pct
    result_df["net_battery_kwh"] = net_batt
    result_df["net_grid_kwh"] = net_grid
    result_df["cost_gbp"] = timestep_cost

    return result_df

