import os
import requests
import pandas as pd
from datetime import datetime, timedelta

OCTOPUS_API_KEY = os.environ.get("OCTOPUS_API_KEY")

def get_consumption(api_key: str | None, mpan: str, serial: str, days: int = 7) -> pd.DataFrame:
    """Fetch consumption records from Octopus Energy and return half-hourly energy kWh with PeriodEnd.

    Returns DataFrame with `interval_end` (UTC datetime) and `energy_kwh`.
    """
    if api_key is None:
        api_key = OCTOPUS_API_KEY
    if api_key is None:
        raise ValueError("Octopus API key required")

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)
    consumption_url = f"https://api.octopus.energy/v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    params = {
        "period_from": start_date.isoformat(),
        "period_to": end_date.isoformat(),
        "page_size": 25000,
    }
    r = requests.get(consumption_url, auth=(api_key, ""), params=params, timeout=20)
    r.raise_for_status()
    results = r.json().get("results", [])
    df = pd.DataFrame(results)
    if df.empty:
        return pd.DataFrame(columns=["interval_end", "energy_kwh"])
    df["interval_start"] = pd.to_datetime(df["interval_start"])
    df["interval_end"] = pd.to_datetime(df["interval_end"])
    df = df.rename(columns={"consumption": "energy_kwh"})
    return df[["interval_end", "energy_kwh"]]
