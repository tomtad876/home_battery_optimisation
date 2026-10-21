"""
Linear programming battery optimiser using CVXPY.
Minimises cost subject to energy balance, SOC bounds, and power constraints.
"""
import cvxpy as cp
import pandas as pd
import numpy as np


# Round-trip efficiency defaults, empirically fitted from FoxESS history
# (SoC vs AC charge/discharge energy) rather than a datasheet figure.
# Fit over 60 days (2026-07-28..2026-09-25): round-trip eta_c*eta_d = 0.901,
# per-direction 0.949, implied effective capacity 5.03 kWh (nameplate 5.0),
# R^2 = 0.864. Cold-weather runs slightly worse (0.885 at 25-30 C BMS temp).
# Re-derive with scripts/estimate_round_trip_efficiency.py.
DEFAULT_CHARGE_EFFICIENCY = 0.95
DEFAULT_DISCHARGE_EFFICIENCY = 0.95
# Grid (supply fuse / export limit) cap, deliberately generous so it never
# binds in normal operation but stops the LP being made infeasible by a demand
# spike that exceeds the battery's own power rating. The old code capped grid
# import/export at battery power, which is what broke on a kettle + oven draw.
DEFAULT_GRID_LIMIT_KW = 15.0

# Terminal salvage value: which percentile of the real import prices to value
# energy left in the battery at the end of the horizon.
#
# This used to be the *mean*, which was fine while Agile was quiet but is
# systematically wrong in the current regime: in the ten days to 2026-10-21
# every single day peaked at 47-58p with an export peak of 24-30p, i.e. a
# ~25p/kWh gap between exporting stored energy and buying it back at the peak.
# A mean of 24-37p undervalues stored energy, so the LP exports surplus at
# ~26p and buys it back at ~52p (seen 2026-10-20: battery at ~20% going into a
# 52p afternoon). The 85th percentile over the same ten days was 38-46p — high
# enough to make holding worth more than exporting, without pricing every kWh
# at a once-a-day spike. Tunable via `salvage_percentile` on the optimiser.
DEFAULT_SALVAGE_PERCENTILE = 85


def _default_salvage_value_pence(
    inputs_df: pd.DataFrame,
    percentile: float = DEFAULT_SALVAGE_PERCENTILE,
) -> float:
    """Default salvage value: a high percentile of the real (non-backfilled) prices.

    The salvage value is the price the optimiser uses to value energy left in the
    battery at the end of the horizon. Excluding the synthetic/backfilled tail
    stops estimated prices from setting that floor; using a percentile rather
    than the mean stops the optimiser valuing stored energy at the daily average
    on a tariff whose expensive hours are worth far more than it (see
    DEFAULT_SALVAGE_PERCENTILE for the evidence).
    """
    if not 0 <= percentile <= 100:
        raise ValueError("salvage percentile must be between 0 and 100")
    if "is_synthetic" in inputs_df.columns:
        real_prices = inputs_df.loc[~inputs_df["is_synthetic"].astype(bool), "price"]
    else:
        real_prices = inputs_df["price"]
    real_prices = real_prices.dropna()
    if real_prices.empty:
        return 0.0
    if percentile >= 100:
        return float(real_prices.max())
    return float(np.percentile(real_prices.to_numpy(dtype=float), percentile))


def mvp_cost_minimiser(
    inputs_df: pd.DataFrame,
    battery_capacity_kwh: float = 15.0,
    initial_soc_pct: float = 50.0,
    min_soc_pct: float = 20.0,
    max_soc_pct: float = 100.0,
    charge_power_kw: float = 3.0,
    discharge_power_kw: float = 3.0,
    salvage_value_pence: float | None = None,
    charge_efficiency: float = DEFAULT_CHARGE_EFFICIENCY,
    discharge_efficiency: float = DEFAULT_DISCHARGE_EFFICIENCY,
    grid_limit_kw: float = DEFAULT_GRID_LIMIT_KW,
    dt_hours: float = 0.5,
    salvage_percentile: float = DEFAULT_SALVAGE_PERCENTILE,
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
        salvage_value_pence: Value (pence/kWh) of energy left in the battery at
            the end of the horizon. Prevents the terminal timestep from dumping
            stored energy to the grid just because export price is positive —
            it must beat the cost of replacing that energy. Defaults to a high
            percentile (see `salvage_percentile`) of the *real* (non-backfilled)
            import prices.
        salvage_percentile: Percentile of the real import prices used for the
            default salvage value when `salvage_value_pence` is None. 50 gives
            the median, 100 the day's peak. Only used when the default applies.
        charge_efficiency: AC-to-stored-energy efficiency (0-1]. Applied in the
            SOC recursion, so the LP only cycles when the discharge price beats
            the charge price divided by the round-trip efficiency.
        discharge_efficiency: Stored-to-AC efficiency (0-1].
        grid_limit_kw: Grid import/export limit (fuse / export rating). Kept
            separate from battery power so a demand spike above the battery
            rating stays feasible.
        dt_hours: Length of one interval in hours (default 0.5 = half-hour).

    Returns:
        DataFrame with columns: period_end, demand, pv_estimate, price, batt_charge_kwh,
                                batt_discharge_kwh, grid_import_kwh, grid_export_kwh,
                                soc_kwh, soc_pct, net_battery_kwh, cost_gbp
    """
    inputs_df = inputs_df.sort_values("period_end").reset_index(drop=True)

    # Fail fast on impossible inputs rather than producing a meaningless plan.
    if battery_capacity_kwh <= 0:
        raise ValueError("battery_capacity_kwh must be greater than 0")
    if not (0 < charge_efficiency <= 1) or not (0 < discharge_efficiency <= 1):
        raise ValueError("charge_efficiency and discharge_efficiency must be in (0, 1]")
    if grid_limit_kw <= 0:
        raise ValueError("grid_limit_kw must be greater than 0")
    if min_soc_pct > max_soc_pct:
        raise ValueError("min_soc_pct must be less than or equal to max_soc_pct")

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
    # Expect a per-period export price column named `export_price` (pence/kWh)
    if "export_price" not in inputs_df.columns:
        raise ValueError("inputs_df must include an 'export_price' column with pence/kWh values")

    export_prices_pence = inputs_df["export_price"].values
    export_prices_gbp = export_prices_pence / 100.0

    # Terminal salvage value: energy left in the battery at the end of the
    # horizon is worth something (it will be used tomorrow). Default to a high
    # percentile of the real import prices so the optimiser only discharges into
    # the tail when the export price beats what that energy would cost to
    # replace at a typical expensive hour. A synthetic/backfilled tail is
    # excluded from the statistic — its prices are estimated and shouldn't set
    # the terminal floor.
    if salvage_value_pence is None:
        salvage_value_pence = _default_salvage_value_pence(inputs_df, salvage_percentile)
    salvage_value_gbp = salvage_value_pence / 100.0

    # Battery and system parameters
    dt = dt_hours
    eta_c = charge_efficiency
    eta_d = discharge_efficiency
    max_batt_charge_energy = charge_power_kw * dt
    max_batt_discharge_energy = discharge_power_kw * dt
    max_grid_energy = grid_limit_kw * dt
    soc_min_kwh = (min_soc_pct / 100.0) * battery_capacity_kwh
    soc_max_kwh = (max_soc_pct / 100.0) * battery_capacity_kwh
    init_soc_kwh = (initial_soc_pct / 100.0) * battery_capacity_kwh

    # Decision variables
    b_charge = cp.Variable(n, nonneg=True)  # Battery charge (kWh, AC side)
    b_discharge = cp.Variable(n, nonneg=True)  # Battery discharge (kWh, AC side)
    g_import = cp.Variable(n, nonneg=True)  # Grid import (kWh)
    g_export = cp.Variable(n, nonneg=True)  # Grid export (kWh)
    s_spill = cp.Variable(n, nonneg=True)  # Curtailed solar (kWh)
    soc = cp.Variable(n)  # State of charge (kWh)

    constraints = []

    # SOC dynamics and bounds
    for t in range(n):
        # SOC balance accounting for round-trip efficiency: charging loses
        # eta_c on the way in, discharging loses eta_d on the way out, so the
        # interval's ability to serve load/sell on the AC side is asymmetric.
        # This is what stops the LP cycling for a spread smaller than the
        # round-trip losses (e.g. charge at 27.9p, sell at 28p).
        if t == 0:
            constraints.append(soc[t] == init_soc_kwh + eta_c * b_charge[t] - b_discharge[t] / eta_d)
        else:
            constraints.append(soc[t] == soc[t - 1] + eta_c * b_charge[t] - b_discharge[t] / eta_d)

        # SOC bounds. If the battery starts below min SOC (reachable via the
        # API), a hard >= soc_min at t=0 would be infeasible. Instead allow a
        # recovery ramp: the lower bound is the min SOC, or however far max-rate
        # charging could have climbed by t — whichever is lower.
        soc_lb_t = min(soc_min_kwh, init_soc_kwh + t * eta_c * max_batt_charge_energy)
        constraints.append(soc[t] >= soc_lb_t)
        constraints.append(soc[t] <= soc_max_kwh)

        # Battery power limits
        constraints.append(b_charge[t] <= max_batt_charge_energy)
        constraints.append(b_discharge[t] <= max_batt_discharge_energy)

        # Grid limits are the fuse/export rating, NOT the battery rating — a
        # kettle + oven draw above the inverter power must stay feasible.
        constraints.append(g_import[t] <= max_grid_energy)
        constraints.append(g_export[t] <= max_grid_energy)

        # Energy balance: solar + discharge + import = demand + charge + export.
        # Any solar that can't be used, stored or exported is spilled (curtailed)
        # rather than making the problem infeasible.
        constraints.append(
            solar_gen[t] - s_spill[t] + b_discharge[t] + g_import[t] - b_charge[t] - g_export[t]
            == demand[t]
        )

    # Objective: minimise cost with small grid penalty
    grid_penalty_weight = 0.001
    penalty = grid_penalty_weight * cp.sum(g_import + g_export)
    # Use per-period export prices where available
    cost = cp.sum(cp.multiply(g_import, import_prices) - cp.multiply(g_export, export_prices_gbp)) + penalty
    # NB: the old `alpha * b_charge * (future_max_price - price)` term was
    # removed. Cross-period arbitrage is already priced by the SOC dynamics, and
    # the term paid the battery to charge even when that energy was never used,
    # which subsidised lossy cycling.

    # Terminal salvage: reward energy left in the battery at the horizon end so
    # the optimiser doesn't dump it to the grid for less than its replacement cost.
    cost = cost - salvage_value_gbp * soc[n - 1]

    problem = cp.Problem(cp.Minimize(cost), constraints)
    # Pin the solver and accept a slightly inaccurate optimum; the default
    # solver is non-deterministic across cvxpy builds, and rejecting
    # OPTIMAL_INACCURATE turned harmless numerical tolerance into a hard failure.
    try:
        problem.solve(solver=cp.CLARABEL, verbose=False)
    except cp.error.SolverError:
        problem.solve(verbose=False)

    if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        raise ValueError(f"Optimisation failed: {problem.status}")

    # Build results DataFrame
    # Per-timestep cost (GBP)
    timestep_cost = g_import.value * import_prices - g_export.value * export_prices_gbp
    soc_pct = (soc.value / battery_capacity_kwh) * 100

    result_df = inputs_df[["period_end"]].copy()
    # Carry through the synthetic-price flag so downstream (routes/UI) can tell
    # real forecast data from backfilled prices used only to shape the tail.
    if "is_synthetic" in inputs_df.columns:
        result_df["is_synthetic"] = inputs_df["is_synthetic"].astype(bool).to_numpy()
    result_df["demand"] = demand
    result_df["pv_estimate"] = solar_gen
    result_df["price"] = inputs_df["price"]
    # Compute net battery and grid flows and present only net charging OR discharging
    eps = 1e-6
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
    result_df["solar_spill_kwh"] = s_spill.value
    result_df["soc_kwh"] = soc.value
    result_df["soc_pct"] = soc_pct
    result_df["net_battery_kwh"] = net_batt
    result_df["net_grid_kwh"] = net_grid
    result_df["cost_gbp"] = timestep_cost
    # include export price used (pence/kWh) to make it available for downstream UI
    result_df["export_price_pence"] = export_prices_pence

    return result_df

