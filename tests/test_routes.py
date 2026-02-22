"""Tests for FastAPI routes."""
import pytest
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthRoute:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test that /health returns ok status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestOptimiserRoute:
    """Test /optimise/mvp endpoint."""

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_success(self, mock_inputs, client):
        """Test successful optimisation run."""
        # Mock forecast data
        mock_inputs.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "PvEstimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })
        
        request_data = {
            "pv_system_id": "test-id",
            "battery_capacity_kwh": 15.0,
            "initial_soc_pct": 50.0,
            "min_soc_pct": 20.0,
            "max_soc_pct": 90.0,
            "charge_power_kw": 3.0,
            "discharge_power_kw": 3.0,
            "export_price_pence": 15.0,
        }
        response = client.post("/optimise/mvp", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "generated_at" in data
        assert "summary" in data
        assert "schedule" in data
        assert len(data["schedule"]) > 0

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_response_structure(self, mock_inputs, client):
        """Test that response contains all required fields."""
        mock_inputs.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "PvEstimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })
        
        response = client.post("/optimise/mvp", json={"pv_system_id": "test-id"})
        assert response.status_code == 200
        data = response.json()
        
        # Check summary structure
        summary = data["summary"]
        assert "total_cost_gbp" in summary
        assert "total_solar_kwh" in summary
        assert "total_demand_kwh" in summary
        assert "total_grid_import_kwh" in summary
        assert "total_grid_export_kwh" in summary
        
        # Check schedule structure
        assert len(data["schedule"]) > 0
        first_period = data["schedule"][0]
        expected_fields = [
            "PeriodEnd", "demand", "solar", "price",
            "batt_charge_kwh", "batt_discharge_kwh",
            "grid_import_kwh", "grid_export_kwh",
            "soc_kwh", "soc_pct", "net_battery_kwh", "cost_gbp"
        ]
        for field in expected_fields:
            assert field in first_period, f"Missing field: {field}"

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_with_custom_params(self, mock_inputs, client):
        """Test that custom parameters are respected."""
        mock_inputs.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "PvEstimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })
        
        request_data = {
            "pv_system_id": "test-id",
            "battery_capacity_kwh": 20.0,
            "initial_soc_pct": 75.0,
            "min_soc_pct": 10.0,
            "max_soc_pct": 95.0,
            "charge_power_kw": 5.0,
            "discharge_power_kw": 5.0,
            "export_price_pence": 20.0,
        }
        response = client.post("/optimise/mvp", json=request_data)
        assert response.status_code == 200

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_no_solar_data(self, mock_inputs, client):
        """Test error handling when solar forecast is empty."""
        mock_inputs.return_value = pd.DataFrame()

        response = client.post("/optimise/mvp", json={})
        assert response.status_code == 400

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_no_demand_data(self, mock_inputs, client):
        """Test error handling when demand forecast is empty."""
        # return rows but with missing demand
        mock_inputs.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "PvEstimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "demand": [None, None, None, None]
        })

        response = client.post("/optimise/mvp", json={})
        assert response.status_code == 400

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_invalid_soc_bounds(self, mock_inputs, client):
        """Test that min_soc >= max_soc raises error."""
        mock_inputs.return_value = pd.DataFrame({
            "PeriodEnd": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "PvEstimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })

        request_data = {
            "min_soc_pct": 90.0,
            "max_soc_pct": 20.0,  # Invalid: max < min
        }
        response = client.post("/optimise/mvp", json=request_data)
        assert response.status_code == 400
