from fastapi import APIRouter, Depends, HTTPException, Header
import os
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional

from app.core.auth import verify_token
from app.core.optimiser import mvp_cost_minimiser
from app.services.data_provider import (
    get_optimiser_inputs, get_user_site, create_site,
    create_battery, create_tariff, get_user_battery, update_battery_provider_config,
    update_battery_config, get_battery_realtime
)
from app.services.foxess import classify_optimiser_output, _merge_groups, classify_and_push

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
    auto_push_enabled: bool | None = None

def _get_battery_for_user(user_id: str) -> dict:
    """Return the user's battery, mapping credential/decrypt failures to HTTP errors."""
    try:
        battery = get_user_battery(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Battery credentials error: {exc}") from exc
    if not battery:
        raise HTTPException(status_code=404, detail="No battery found. Complete setup first.")
    return battery

@router.put("/batteries/me")
def put_my_battery(req: UpdateBatteryRequest, user: dict = Depends(verify_token)):
    """Update the authenticated user's battery config."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    battery = _get_battery_for_user(user_id)
    from app.services.data_provider import update_battery_config
    try:
        updated = update_battery_config(battery["id"], req.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Battery credentials error: {exc}") from exc
    return {"battery": updated}


@router.get("/batteries/me")
def get_my_battery(user: dict = Depends(verify_token)):
    """Return the authenticated user's battery config."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")
    battery = _get_battery_for_user(user_id)
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
    battery = _get_battery_for_user(user_id)

    # Merge with existing config
    existing = battery.get("provider_config") or {}
    updates = req.model_dump(exclude_unset=True)
    merged = {**existing, **updates}

    # Remove keys with empty strings
    merged = {k: v for k, v in merged.items() if v is not None and v != ""}

    try:
        updated = update_battery_provider_config(str(battery["id"]), merged)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Battery credentials error: {exc}") from exc
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

    if req.min_soc_pct >= req.max_soc_pct:
        raise HTTPException(status_code=400, detail="min_soc_pct must be less than max_soc_pct")

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


class PushScheduleRequest(BaseModel):
    battery_capacity_kwh: float | None = None
    min_soc_pct: float | None = None
    max_soc_pct: float | None = None
    charge_power_kw: float | None = None
    discharge_power_kw: float | None = None


@router.post("/optimise/push")
def optimise_and_push(req: PushScheduleRequest, user: dict = Depends(verify_token)):
    """Run optimiser and push the resulting schedule to the FoxESS inverter."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user sub")

    battery = get_user_battery(user_id)
    if not battery:
        raise HTTPException(status_code=404, detail="No battery found. Complete setup first.")

    config = battery.get("provider_config") or {}
    foxess_key = config.get("foxess_api_key")
    device_sn = config.get("foxess_device_sn")
    if not foxess_key or not device_sn:
        raise HTTPException(status_code=400, detail="FoxESS credentials not configured. Add them in Settings.")

    site = get_user_site(user_id)
    if not site:
        raise HTTPException(status_code=404, detail="No site found. Complete setup first.")

    # 1. Get live SOC
    realtime = get_battery_realtime(user_id)
    soc_pct = realtime.get("soc_pct")
    if soc_pct is None:
        error = realtime.get("error", "Could not fetch live SOC from FoxESS")
        raise HTTPException(status_code=400, detail=f"Live SOC unavailable: {error}")

    # Use battery config as defaults — don't hardcode
    batt_capacity = req.battery_capacity_kwh or battery.get("capacity_kwh", 15.0)
    batt_min_soc = req.min_soc_pct or battery.get("min_soc_pct", 20.0)
    batt_max_soc = req.max_soc_pct or battery.get("max_soc_pct", 100.0)
    batt_charge_kw = req.charge_power_kw or battery.get("max_charge_kw", 3.0)
    batt_discharge_kw = req.discharge_power_kw or battery.get("max_discharge_kw", 3.0)

    # 2. Run optimiser
    try:
        inputs = get_optimiser_inputs(str(site["id"]))
        if inputs.empty:
            raise HTTPException(status_code=400, detail="No forecast data available. Check Solcast/FoxESS credentials.")

        schedule = mvp_cost_minimiser(
            inputs_df=inputs,
            battery_capacity_kwh=batt_capacity,
            initial_soc_pct=soc_pct,
            min_soc_pct=batt_min_soc,
            max_soc_pct=batt_max_soc,
            charge_power_kw=batt_charge_kw,
            discharge_power_kw=batt_discharge_kw,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Optimisation failed: {str(e)}")

    # 3. Classify and push to inverter
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)

    # Classify first so we can show the groups
    try:
        from app.services.foxess import init_api as _init_api
        import foxesscloud.openapi as _f

        _init_api(foxess_key)
        _f.device_sn = device_sn
        info = _f.get_flag()
        max_groups = _f.max_periods or 8

        groups = classify_optimiser_output(
            result_df=schedule,
            threshold=0.05,
            from_time=now,
            min_soc_pct=batt_min_soc,
            max_soc_pct=batt_max_soc,
            rated_power_w=batt_charge_kw * 1000,
            local_tz=site.get("timezone", "Europe/London"),
        )
        if len(groups) > max_groups:
            groups = _merge_groups(groups, max_groups)

        # Push to device
        _f.set_schedule(periods=groups, enable=True)
        pushed = True
    except Exception as e:
        groups = []
        pushed = False
        push_error = str(e)

    if not pushed:
        raise HTTPException(status_code=502, detail=f"FoxESS push failed: {push_error}")

    # Build human-readable summary of each group
    group_summaries = []
    for g in groups:
        mode = g.get("workMode", "?")
        start = f"{g['startHour']:02d}:{g['startMinute']:02d}"
        end = f"{g['endHour']:02d}:{g['endMinute']:02d}"
        params = g.get("extraParam", {})
        desc = f"{start}–{end} {mode}"
        if mode in ("ForceCharge", "ForceDischarge"):
            desc += f" (fdPwr={params.get('fdPwr', '?')}W, fdSoc={params.get('fdSoc', '?')}%)"
        if mode == "ForceCharge":
            desc += f" (maxSoc={params.get('maxSoc', '?')}%)"
        group_summaries.append({
            "start": start,
            "end": end,
            "mode": mode,
            "extraParam": params,
            "description": desc,
        })

    return {
        "status": "success",
        "pushed": pushed,
        "groups_sent": len(groups),
        "soc_at_push": soc_pct,
        "generated_at": now.isoformat(),
        "groups": group_summaries,
    }


# --- Internal endpoint for Edge Function calls (service-to-service) ---

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")


def verify_internal_key(x_internal_key: Optional[str] = Header(None)):
    """Verify internal API key for service-to-service calls."""
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=500, detail="INTERNAL_API_KEY not configured")
    if x_internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal API key")


class InternalOptimiseRequest(BaseModel):
    user_id: str
    battery_capacity_kwh: float = 15.0
    initial_soc_pct: float = 50.0
    min_soc_pct: float = 20.0
    max_soc_pct: float = 90.0
    charge_power_kw: float = 3.0
    discharge_power_kw: float = 3.0


@router.post("/internal/optimise")
def internal_optimise(req: InternalOptimiseRequest, _: dict = Depends(verify_internal_key)):
    """Internal endpoint: run optimiser for a user. Called by Edge Functions."""
    site = get_user_site(req.user_id)
    if not site:
        raise HTTPException(status_code=404, detail="No site found for user")

    inputs = get_optimiser_inputs(str(site["id"]))
    if inputs.empty:
        raise HTTPException(status_code=400, detail="No forecast data available")

    schedule = mvp_cost_minimiser(
        inputs_df=inputs,
        battery_capacity_kwh=req.battery_capacity_kwh,
        initial_soc_pct=req.initial_soc_pct,
        min_soc_pct=req.min_soc_pct,
        max_soc_pct=req.max_soc_pct,
        charge_power_kw=req.charge_power_kw,
        discharge_power_kw=req.discharge_power_kw,
    )

    return {
        "status": "success",
        "schedule": schedule.to_dict(orient="records"),
    }
