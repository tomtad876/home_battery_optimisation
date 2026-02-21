import pandas as pd
import os
from app.services import solcast, foxess

SOLCAST_API_KEY = os.environ.get("SOLCAST_API_KEY")
FOXESS_API_KEY = os.environ.get("FOXESS_API_KEY")

def forecast_demand_last_week_avg(api_key: str | None = None) -> pd.DataFrame:
    """Simple MVP demand forecast: average last 7 days of FoxESS load history by half-hour-of-day.

    Returns DataFrame with `time_of_day` (time) and `energy_kwh` (float) columns.
    """
    if api_key is None:
        api_key = FOXESS_API_KEY
    if api_key is None:
        raise ValueError("FoxESS API key required for demand forecast")
    
    foxess.init_api(api_key)
    return foxess.get_demand_forecast(days=7)

def forecast_solar_and_prices(pv_system_id: str | None = None) -> pd.DataFrame:
    """Fetch solar forecast + Octopus Agile prices from FoxESS for the next 24-48 hours.

    Returns merged DataFrame with PeriodEnd, PvEstimate, and price columns.
    """
    solcast_key = os.environ.get("SOLCAST_API_KEY")
    foxess_key = os.environ.get("FOXESS_API_KEY")
    
    if not foxess_key:
        raise ValueError("FoxESS API key required for prices")
    
    solar = solcast.get_solar_forecast(solcast_key, pv_system_id)

    # Parse PeriodEnd robustly (accept date-only or timezone-less strings)
    solar["PeriodEnd"] = pd.to_datetime(solar["PeriodEnd"], utc=True, errors="coerce")
    # Drop unparseable rows
    solar = solar.dropna(subset=["PeriodEnd"]) 
    solar["time_of_day"] = solar["PeriodEnd"].dt.time
    
    foxess.init_api(foxess_key)
    prices = foxess.get_agile_prices()

    merged = solar.merge(prices, on="PeriodEnd", how="left")
    return merged

