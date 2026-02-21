"""Tests for service integrations (with mocks)."""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from app.services import solcast, foxess, forecast


class TestSolcast:
    """Test Solcast service."""

    @patch('app.services.solcast.requests.get')
    def test_get_solar_forecast_returns_dataframe(self, mock_get):
        """Test that get_solar_forecast returns DataFrame with correct columns."""
        # Mock CSV response
        mock_response = MagicMock()
        mock_response.content = b"PeriodEnd,PvEstimate\n2025-09-20T00:00:00Z,0.1\n2025-09-20T00:30:00Z,0.2"
        mock_get.return_value = mock_response
        
        result = solcast.get_solar_forecast("test_key", "test_id")
        assert isinstance(result, pd.DataFrame)
        assert "PeriodEnd" in result.columns
        assert "PvEstimate" in result.columns

    def test_get_solar_forecast_requires_credentials(self):
        """Test that get_solar_forecast raises error if credentials missing."""
        with pytest.raises(ValueError, match="Solcast API key"):
            solcast.get_solar_forecast(None, None)


class TestFoxess:
    """Test FoxESS service."""

    @patch('app.services.foxess.f.get_agile_times')
    def test_get_agile_prices_returns_dataframe(self, mock_agile):
        """Test that get_agile_prices returns DataFrame with prices."""
        mock_agile.return_value = {
            "base_time": "2025-09-20T00:00:00Z",
            "prices": [
                {"hour": 0, "price": 10.5},
                {"hour": 1, "price": 12.3},
            ]
        }
        foxess.init_api("test_key")
        result = foxess.get_agile_prices()
        assert isinstance(result, pd.DataFrame)
        assert "PeriodEnd" in result.columns
        assert "price" in result.columns

    @patch('app.services.foxess.f.get_history')
    def test_get_demand_forecast_returns_dataframe(self, mock_history):
        """Test that get_demand_forecast processes load data correctly."""
        # Mock load history data structure
        mock_history.return_value = [
            {
                "variable": "loadsPower",
                "data": [
                    {"time": "2025-09-20T00:00:00Z", "value": 1.5},
                    {"time": "2025-09-20T00:30:00Z", "value": 1.4},
                ]
            }
        ]
        foxess.init_api("test_key")
        result = foxess.get_demand_forecast()
        assert isinstance(result, pd.DataFrame)
        assert "time_of_day" in result.columns
        assert "energy_kwh" in result.columns

    @patch('app.services.foxess.FOXESS_API_KEY', None)
    def test_init_api_requires_key(self):
        """Test that init_api raises error when key is missing."""
        with pytest.raises(ValueError, match="FoxESS API key"):
            foxess.init_api(None)


class TestForecast:
    """Test forecast helpers."""

    @patch('app.services.forecast.foxess.init_api')
    @patch('app.services.forecast.foxess.get_demand_forecast')
    def test_forecast_demand_last_week_avg(self, mock_demand, mock_init):
        """Test demand forecast aggregation."""
        mock_demand.return_value = pd.DataFrame({
            "time_of_day": [pd.Timestamp("00:00").time(), pd.Timestamp("00:30").time()],
            "energy_kwh": [0.5, 0.6]
        })
        result = forecast.forecast_demand_last_week_avg("test_key")
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    @patch('app.services.forecast.solcast.get_solar_forecast')
    @patch('app.services.forecast.foxess.init_api')
    @patch('app.services.forecast.foxess.get_agile_prices')
    def test_forecast_solar_and_prices(self, mock_prices, mock_init, mock_solar):
        """Test combined solar + prices forecast."""
        mock_solar.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "PvEstimate": [0.1, 0.2]
        })
        mock_prices.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=2, freq="30min", tz="UTC"),
            "price": [15.0, 20.0]
        })
        result = forecast.forecast_solar_and_prices("test_id")
        assert isinstance(result, pd.DataFrame)
        assert "PeriodEnd" in result.columns
        assert "PvEstimate" in result.columns
        assert "price" in result.columns

    @patch('app.services.forecast.FOXESS_API_KEY', None)
    def test_forecast_demand_requires_api_key(self):
        """Test that forecast_demand requires API key."""
        with pytest.raises(ValueError, match="FoxESS API key"):
            forecast.forecast_demand_last_week_avg(None)

    @patch('app.services.forecast.os.environ.get')
    def test_forecast_solar_requires_api_key(self, mock_get):
        """Test that forecast_solar_and_prices requires API key."""
        # Make FOXESS_API_KEY return None
        def get_env(key, default=None):
            if key == "FOXESS_API_KEY":
                return None
            return default
        mock_get.side_effect = get_env
        
        with pytest.raises(ValueError, match="FoxESS API key"):
            forecast.forecast_solar_and_prices("test_id")

