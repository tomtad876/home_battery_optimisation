from fastapi import APIRouter, Depends, HTTPException
import os
from datetime import datetime, timezone
from pydantic import BaseModel

from app.core.auth import verify_token
from app.core.optimiser import mvp_cost_minimiser
from app.services.data_provider import (
    get_optimiser_inputs, get_user_site, create_site,
    create_battery, create_tariff, get_user_battery, update_battery_provider_config,
    update_battery_config, get_battery_realtime
)

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}


# --- Site management ---

@router.get("/sites/me")
def get_my_site(user: dict = Depends(verify_token)):
    """Return the authenticated user's site, or 404 if none exists."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    site = get_user_site(user_id)
    if not site:
        raise HTTPException(status_code=404, detail="No site found. Complete setup first.")
    return {"site": site}


class CreateSiteRequest(BaseModel):
    name: str = "Home"
    timezone: str = "Europe/London"

@router.post("/sites")
def post_site(req: CreateSiteRequest, user: dict = Depends(verify_token)):
    """Create a new site for the authenticated user."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")

    existing = get_user_site(user_id)
    if existing:
        raise HTTPException(status_code=409, detail="Site already exists")

    site = create_site(user_id, req.name, req.timezone)
    return {"site": site}


# --- Battery config ---

class CreateBatteryRequest(BaseModel):
    site_id: str
    capacity_kwh: float = 5.0
    max_charge_kw: float = 3.0
    max_discharge_kw: float = 3.0
    min_soc_pct: float = 20.0
    max_soc_pct: float = 100.0
    provider_type: str = "foxess"
    provider_config: dict | None = None

@router.post("/batteries")
def post_battery(req: CreateBatteryRequest, user: dict = Depends(verify_token)):
    """Create battery config for a site."""
    user_id = user.get("sub")
    site = get_user_site(user_id)
    if not site:
        raise HTTPException(status_code=404, detail="No site found")
    if str(site["id"]) != req.site_id:
        raise HTTPException(status_code=403, detail="Not your site")

    battery = create_battery(
        site_id=req.site_id,
        capacity_kwh=req.capacity_kwh,
        max_charge_kw=req.max_charge_kw,
        max_discharge_kw=req.max_discharge_kw,
        min_soc_pct=req.min_soc_pct,
        max_soc_pct=req.max_soc_pct,
        provider_type=req.provider_type,
        provider_config=req.provider_config,
    )
    return {"battery": battery}


class UpdateBatteryRequest(BaseModel):
    capacity_kwh: float | None = None
    max_charge_kw: float | None = None
    max_discharge_kw: float | None = None
    min_soc_pct: float | None = None
    max_soc_pct: float | None = None

@router.put("/batteries/me")
def put_my_battery(req: UpdateBatteryRequest, user: dict = Depends(verify_token)):
    """Update the authenticated user's battery config."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    battery = get_user_battery(user_id)
    if not battery:
        raise HTTPException(status_code=404, detail="No battery found. Complete setup first.")
    from app.services.data_provider import update_battery_config
    updated = update_battery_config(battery["id"], req.model_dump(exclude_unset=True))
    return {"battery": updated}


@router.get("/batteries/me")
def get_my_battery(user: dict = Depends(verify_token)):
    """Return the authenticated user's battery config."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    battery = get_user_battery(user_id)
    if not battery:
        raise HTTPException(status_code=404, detail="No battery found. Complete setup first.")
    return {"battery": battery}


class UpdateProviderConfigRequest(BaseModel):
    solcast_api_key: str | None = None
    solcast_system_id: str | None = None
    foxess_api_key: str | None = None
    foxess_device_sn: str | None = None

@router.put("/batteries/me/provider_config")
def put_provider_config(req: UpdateProviderConfigRequest, user: dict = Depends(verify_token)):
    """Update the authenticated user's API credentials in provider_config."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    battery = get_user_battery(user_id)
    if not battery:
        raise HTTPException(status_code=404, detail="No battery found. Complete setup first.")

    # Merge with existing config
    existing = battery.get("provider_config") or {}
    updates = req.model_dump(exclude_unset=True)
    merged = {**existing, **updates}

    # Remove keys with empty strings
    merged = {k: v for k, v in merged.items() if v is not None and v != ""}

    updated = update_battery_provider_config(str(battery["id"]), merged)
    return {"battery": updated}


# --- Tariff config ---

class CreateTariffRequest(BaseModel):
    site_id: str
    import_type: str = "agile"
    export_type: str = "agile"
    config_json: dict | None = None

@router.post("/tariffs")
def post_tariff(req: CreateTariffRequest, user: dict = Depends(verify_token)):
    """Create tariff config for a site."""
    user_id = user.get("sub")
    site = get_user_site(user_id)
    if not site:
        raise HTTPException(status_code=404, detail="No site found")
    if str(site["id"]) != req.site_id:
        raise HTTPException(status_code=403, detail="Not your site")

    tariff = create_tariff(
        site_id=req.site_id,
        import_type=req.import_type,
        export_type=req.export_type,
        config_json=req.config_json,
    )
    return {"tariff": tariff}


@router.get("/tariff/prices")
def get_prices(user: dict = Depends(verify_token)):
    """Return all Agile prices for today (past + future) from agile_rates."""
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from datetime import timezone, timedelta
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT period_end, import_price, export_price
            FROM agile_rates
            WHERE period_end >= date_trunc('day', now() AT TIME ZONE 'Europe/London')
              AND period_end < date_trunc('day', now() AT TIME ZONE 'Europe/London') + interval '1 day'
            ORDER BY period_end
        """))
        rows = []
        bst = timezone(timedelta(hours=1))
        for r in result.mappings().all():
            pe = r["period_end"]
            # Ensure timezone-aware: if naive, assume UTC then convert to BST
            if pe.tzinfo is None:
                pe = pe.replace(tzinfo=timezone.utc).astimezone(bst)
            rows.append({
                "period_end": pe.isoformat(),
                "import_price": float(r["import_price"]),
                "export_price": float(r["export_price"]),
            })
        return {"prices": rows}
    finally:
        session.close()


# --- Real-time battery data ---

@router.get("/battery/realtime")
def get_realtime(user: dict = Depends(verify_token)):
    """Fetch real-time SOC and last 4 hours of history from FoxESS."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    data = get_battery_realtime(user_id)
    return data


# --- Optimiser ---

class MVPOptimiseRequest(BaseModel):
    pv_system_id: str | None = None
    battery_capacity_kwh: float = 5.0
    initial_soc_pct: float = 50.0
    min_soc_pct: float = 20.0
    max_soc_pct: float = 100.0
    charge_power_kw: float = 3.0
    discharge_power_kw: float = 3.0



@router.post("/optimise/mvp")
def optimise_mvp(req: MVPOptimiseRequest, user: dict = Depends(verify_token)):
    """
    MVP optimiser endpoint: compute optimal battery dispatch schedule for lowest cost.
    Scoped to the authenticated user's site.
    """
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")

    site = get_user_site(user_id)
    if not site:
        raise HTTPException(status_code=404, detail="No site found. Complete setup first.")

    try:
        inputs = get_optimiser_inputs(str(site["id"]))

        if inputs.empty:
            raise HTTPException(
                status_code=400,
                detail="NO_DATA: No forecast data available yet. This usually means your Solcast and FoxESS API credentials haven't been configured. Please add them in your site settings."
            )
    
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
