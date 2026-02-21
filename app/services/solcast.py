import os
import io
import requests
import pandas as pd
from datetime import timedelta

SOLCAST_API_KEY = os.environ.get("SOLCAST_API_KEY")

def get_solar_forecast(solcast_api_key: str | None = None, pv_system_id: str | None = None) -> pd.DataFrame:
    """Fetch rooftop PV forecast from Solcast and return half-hourly kWh estimates.

    Returns a DataFrame with columns `PeriodEnd` (UTC datetime) and `PvEstimate` (kWh).
    """
    if solcast_api_key is None:
        solcast_api_key = SOLCAST_API_KEY
    if solcast_api_key is None or pv_system_id is None:
        raise ValueError("Solcast API key and PV system ID must be provided")

    url = f"https://api.solcast.com.au/rooftop_sites/{pv_system_id}/forecasts"
    credentials = requests.auth.HTTPBasicAuth(solcast_api_key, "")
    params = {"format": "csv"}
    resp = requests.get(url, auth=credentials, params=params, timeout=20)
    resp.raise_for_status()
    df = pd.read_csv(io.BytesIO(resp.content), parse_dates=["PeriodEnd"])  # PeriodEnd in UTC
    # Convert PV power (kW) to energy over 30 minutes (kWh)
    if "PvEstimate" in df.columns:
        df["PvEstimate"] = df["PvEstimate"] * 0.5
    else:
        df["PvEstimate"] = 0
    df = df[["PeriodEnd", "PvEstimate"]]
    return df
