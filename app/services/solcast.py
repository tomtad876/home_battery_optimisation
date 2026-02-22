import os
import io
import requests
import pandas as pd
from datetime import datetime, timezone

from app.services.data_provider import get_optimiser_inputs


def get_solar_forecast(solcast_api_key: str | None = None, pv_system_id: str | None = None, days: int = 7) -> pd.DataFrame:
    """Return the solar forecast, preferring DB but falling back to Solcast API.

    Signature kept for compatibility; when DB has data it will be used.
    """
    # Require explicit credentials for API usage (keeps behaviour predictable in tests)
    if solcast_api_key is None or pv_system_id is None:
        raise ValueError("Solcast API key and PV system ID must be provided")
    # Try DB first (if available)
    try:
        df = get_optimiser_inputs(days=days)
        if not df.empty:
            return df[["PeriodEnd", "PvEstimate"]].copy()
    except Exception:
        pass

    url = f"https://api.solcast.com.au/rooftop_sites/{pv_system_id}/forecasts"
    credentials = requests.auth.HTTPBasicAuth(solcast_api_key, "")
    params = {"format": "csv"}
    resp = requests.get(url, auth=credentials, params=params, timeout=20)
    resp.raise_for_status()
    df = pd.read_csv(io.BytesIO(resp.content), parse_dates=["PeriodEnd"])  # PeriodEnd in UTC
    if "PvEstimate" in df.columns:
        df["PvEstimate"] = df["PvEstimate"] * 0.5
    else:
        df["PvEstimate"] = 0
    return df[["PeriodEnd", "PvEstimate"]]
