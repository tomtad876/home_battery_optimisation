from fastapi import APIRouter, HTTPException
import os
from datetime import datetime, timezone
from pydantic import BaseModel

from app.core.optimiser import mvp_cost_minimiser
from app.services import solcast, forecast

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}


class MVPOptimiseRequest(BaseModel):
    pv_system_id: str | None = None
    battery_capacity_kwh: float = 5.0
    initial_soc_pct: float = 50.0
    min_soc_pct: float = 20.0
    max_soc_pct: float = 100.0
    charge_power_kw: float = 3.0
    discharge_power_kw: float = 3.0
    export_price_pence: float = 15.0


@router.post("/optimise/mvp")
def optimise_mvp(req: MVPOptimiseRequest):
    """
    MVP optimiser endpoint: compute optimal battery dispatch schedule for lowest cost.
    Uses linear programming (CVXPY) to minimise electricity costs over forecast horizon.
    
    Returns a schedule with half-hourly breakdown of:
    - demand, solar generation, import/export prices
    - battery charge/discharge, grid import/export
    - state of charge (SOC) and total cost
    """
    try:
        # Determine PV system ID: prefer request, fallback to environment variable
        pv_system_id = req.pv_system_id or os.environ.get("SOLCAST_PV_SYSTEM_ID")
        # Get solar forecast and prices (next 24-48h from providers)
        solar_prices = forecast.forecast_solar_and_prices(pv_system_id)
        if solar_prices.empty:
            raise ValueError("Unable to fetch solar/price forecast")

        # Get last-week demand profile
        demand_profile = forecast.forecast_demand_last_week_avg()
        if demand_profile.empty:
            # Fallback: assume avg 0.5 kWh per half-hour if no history available
            raise ValueError("Unable to fetch demand forecast from FoxESS")

        # Run LP optimiser
        schedule = mvp_cost_minimiser(
            solar_df=solar_prices[["PeriodEnd", "PvEstimate"]],
            prices_df=solar_prices[["PeriodEnd", "price"]],
            demand_profile=demand_profile,
            battery_capacity_kwh=req.battery_capacity_kwh,
            initial_soc_pct=req.initial_soc_pct,
            min_soc_pct=req.min_soc_pct,
            max_soc_pct=req.max_soc_pct,
            charge_power_kw=req.charge_power_kw,
            discharge_power_kw=req.discharge_power_kw,
            export_price_pence=req.export_price_pence,
        )

        # Compute summary stats
        total_cost = schedule["cost_gbp"].sum()
        total_solar = schedule["solar"].sum()
        total_demand = schedule["demand"].sum()
        total_import = schedule["grid_import_kwh"].sum()
        total_export = schedule["grid_export_kwh"].sum()

        return {
            "status": "success",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_cost_gbp": float(total_cost),
                "total_solar_kwh": float(total_solar),
                "total_demand_kwh": float(total_demand),
                "total_grid_import_kwh": float(total_import),
                "total_grid_export_kwh": float(total_export),
            },
            "schedule": schedule.to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Optimisation failed: {str(e)}")