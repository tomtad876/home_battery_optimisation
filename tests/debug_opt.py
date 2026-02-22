import pandas as pd
from app.core.optimiser import mvp_cost_minimiser

solar = pd.DataFrame({
    "PeriodEnd": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
    "PvEstimate": [0.0,0.0]
})
prices = pd.DataFrame({
    "PeriodEnd": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
    "price": [10.0,50.0]
})
demand_profile = pd.DataFrame({
    "time_of_day": [pd.Timestamp("2025-09-20 00:00").time()] * 2,
    "energy_kwh": [0.5,0.5]
})
params = {"battery_capacity_kwh":15.0,"initial_soc_pct":50.0,"min_soc_pct":20.0,"max_soc_pct":90.0,"charge_power_kw":3.0,"discharge_power_kw":3.0,"export_price_pence":15.0}
res = mvp_cost_minimiser(solar, prices, demand_profile, **params)
print(res.to_string(index=False))
