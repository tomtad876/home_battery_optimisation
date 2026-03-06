from fastapi import APIRouter, HTTPException
import os
from datetime import datetime, timezone
from pydantic import BaseModel

from app.core.optimiser import mvp_cost_minimiser
from app.services.data_provider import get_optimiser_inputs

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
        # Prefer single DB-joined inputs (solar, price, demand aggregated)
        inputs = get_optimiser_inputs()
    
        # Use the joined inputs directly
        schedule = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=req.battery_capacity_kwh,
            initial_soc_pct=req.initial_soc_pct,
            min_soc_pct=req.min_soc_pct,
            max_soc_pct=req.max_soc_pct,
            charge_power_kw=req.charge_power_kw,
            discharge_power_kw=req.discharge_power_kw,
        )

        # Compute summary stats
        total_cost = float(schedule["cost_gbp"].sum())
        total_solar = float(schedule["pv_estimate"].sum())
        total_demand = float(schedule["demand"].sum())
        total_import = float(schedule["grid_import_kwh"].sum())
        total_export = float(schedule["grid_export_kwh"].sum())
        # compute export revenue using per-timestep export price if provided
        # Compute export revenue from per-timestep export price column (expected name: `export_price` in pence/kWh)
        if "export_price" in schedule.columns:
            total_export_revenue = float((schedule["grid_export_kwh"] * schedule["export_price"] / 100.0).sum())
        else:
            total_export_revenue = 0.0

        return {
            "status": "success",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_cost_gbp": total_cost,
                "total_solar_kwh": total_solar,
                "total_demand_kwh": total_demand,
                "total_grid_import_kwh": total_import,
                "total_grid_export_kwh": total_export,
                "total_grid_export_revenue_gbp": total_export_revenue,
            },
            "schedule": schedule.to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Optimisation failed: {str(e)}")