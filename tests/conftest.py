"""Pytest configuration and shared fixtures."""
import pytest
import pandas as pd
from datetime import datetime, timedelta


@pytest.fixture
def sample_solar_df():
    """Sample solar forecast DataFrame."""
    periods = pd.date_range("2025-09-20 00:00", periods=48, freq="30min", tz="UTC")
    data = []
    for i, period in enumerate(periods):
        # Simple curve: low at night, peak at midday
        hour = period.hour + period.minute / 60
        pv_estimate = max(0, 3 * (1 - abs(hour - 12) / 12) ** 2)  # kWh
        data.append({"PeriodEnd": period, "PvEstimate": pv_estimate})
    return pd.DataFrame(data)


@pytest.fixture
def sample_prices_df():
    """Sample Octopus Agile prices DataFrame."""
    periods = pd.date_range("2025-09-20 00:00", periods=48, freq="30min", tz="UTC")
    data = []
    for i, period in enumerate(periods):
        # Vary prices: low at night (10p), mid-day high (50p)
        hour = period.hour + period.minute / 60
        price = 25 + 20 * (1 - abs(hour - 12) / 12) ** 2  # pence
        data.append({"PeriodEnd": period, "price": price})
    return pd.DataFrame(data)


@pytest.fixture
def sample_demand_profile():
    """Sample demand profile by time of day."""
    times = [datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time() for h in range(24) for m in [0, 30]]
    data = []
    for time in times:
        hour = time.hour + time.minute / 60
        # Assume higher demand in evening, lower at night
        energy_kwh = 0.5 + 0.3 * (1 if 6 <= hour <= 22 else 0)
        data.append({"time_of_day": time, "energy_kwh": energy_kwh})
    return pd.DataFrame(data)


@pytest.fixture
def optimiser_params():
    """Standard optimiser parameters."""
    return {
        "battery_capacity_kwh": 15.0,
        "initial_soc_pct": 50.0,
        "min_soc_pct": 20.0,
        "max_soc_pct": 90.0,
        "charge_power_kw": 3.0,
        "discharge_power_kw": 3.0,
        "export_price_pence": 15.0,
    }
