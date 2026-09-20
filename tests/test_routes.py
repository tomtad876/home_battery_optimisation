"""Tests for FastAPI routes."""
import pytest
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import verify_token


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock verify_token so tests don't need real Supabase credentials."""
    def _fake_verify():
        return {"sub": "test-user-id", "email": "test@example.com"}
    app.dependency_overrides[verify_token] = _fake_verify
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_user_site():
    """Mock get_user_site so optimiser tests pass auth/site checks."""
    with patch('app.api.routes.get_user_site') as mock:
        mock.return_value = {"id": "test-site-id", "user_id": "test-user-id", "name": "Test"}
        yield mock


@pytest.fixture(autouse=True)
def mock_user_battery():
    """Mock get_user_battery so /optimise/mvp doesn't hit the real DB."""
    with patch('app.api.routes.get_user_battery') as mock:
        mock.return_value = {
            "id": "test-battery-id",
            "site_id": "test-site-id",
            "capacity_kwh": 5.0,
            "max_charge_kw": 3.0,
            "max_discharge_kw": 3.0,
            "min_soc_pct": 20.0,
            "max_soc_pct": 100.0,
            "provider_type": "foxess",
            "provider_config": {},
        }
        yield mock


@pytest.fixture(autouse=True)
def mock_realtime():
    """Mock get_battery_realtime so /optimise/mvp's SOC fallback doesn't hit FoxESS."""
    with patch('app.api.routes.get_battery_realtime') as mock:
        mock.return_value = {"soc_pct": 50.0, "history": []}
        yield mock


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
        mock_inputs.return_value = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })

        request_data = {
            "battery_capacity_kwh": 15.0,
            "initial_soc_pct": 50.0,
            "min_soc_pct": 20.0,
            "max_soc_pct": 90.0,
            "charge_power_kw": 3.0,
            "discharge_power_kw": 3.0,
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
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })

        response = client.post("/optimise/mvp", json={})
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
            "period_end", "demand", "pv_estimate", "price",
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
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })

        request_data = {
            "battery_capacity_kwh": 20.0,
            "initial_soc_pct": 75.0,
            "min_soc_pct": 10.0,
            "max_soc_pct": 95.0,
            "charge_power_kw": 5.0,
            "discharge_power_kw": 5.0,
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
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [None, None, None, None]
        })

        response = client.post("/optimise/mvp", json={})
        assert response.status_code == 400

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_invalid_soc_bounds(self, mock_inputs, client):
        """Test that min_soc >= max_soc raises error."""
        mock_inputs.return_value = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })

        request_data = {
            "min_soc_pct": 90.0,
            "max_soc_pct": 20.0,  # Invalid: max < min
        }
        response = client.post("/optimise/mvp", json=request_data)
        assert response.status_code == 400

    @patch('app.api.routes.mvp_cost_minimiser')
    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_reads_saved_battery_row(self, mock_inputs, mock_optimiser, client, mock_user_battery):
        """An empty body must use the saved battery row, not hardcoded defaults."""
        mock_inputs.return_value = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })
        mock_optimiser.return_value = pd.DataFrame({
            "cost_gbp": [1.0, 2.0],
            "pv_estimate": [0.5, 0.5],
            "demand": [0.5, 0.5],
            "grid_import_kwh": [0.0, 0.0],
            "grid_export_kwh": [0.0, 0.0],
            "export_price": [6.0, 6.0],
        })
        # A battery that is NOT the historical 5 kWh / 3 kW default.
        mock_user_battery.return_value = {
            "id": "test-battery-id",
            "site_id": "test-site-id",
            "capacity_kwh": 10.0,
            "max_charge_kw": 4.0,
            "max_discharge_kw": 4.0,
            "min_soc_pct": 30.0,
            "max_soc_pct": 95.0,
            "provider_type": "foxess",
            "provider_config": {},
        }

        response = client.post("/optimise/mvp", json={})
        assert response.status_code == 200

        kwargs = mock_optimiser.call_args.kwargs
        assert kwargs["battery_capacity_kwh"] == 10.0
        assert kwargs["min_soc_pct"] == 30.0
        assert kwargs["max_soc_pct"] == 95.0
        assert kwargs["charge_power_kw"] == 4.0
        assert kwargs["discharge_power_kw"] == 4.0
        # initial SOC falls back to live SOC from the (mocked) realtime call
        assert kwargs["initial_soc_pct"] == 50.0

    @patch('app.api.routes.mvp_cost_minimiser')
    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_returns_full_schedule_with_synthetic_flag(self, mock_inputs, mock_optimiser, client):
        """Summary covers real rows only, but the schedule returns the full tail, flagged."""
        mock_inputs.return_value = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5],
            "is_synthetic": [False, False, True, True],
        })
        mock_optimiser.return_value = pd.DataFrame({
            "cost_gbp": [1.0, 2.0, 999.0, 999.0],
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "demand": [0.5, 0.5, 0.5, 0.5],
            "grid_import_kwh": [0.1, 0.1, 5.0, 5.0],
            "grid_export_kwh": [0.2, 0.2, 5.0, 5.0],
            "export_price_pence": [6.0, 4.8, 20.0, 8.0],
            "is_synthetic": [False, False, True, True],
        })

        response = client.post("/optimise/mvp", json={})
        assert response.status_code == 200
        data = response.json()

        # Full schedule returned, with the flag preserved and JSON-safe
        assert len(data["schedule"]) == 4
        assert [r["is_synthetic"] for r in data["schedule"]] == [False, False, True, True]

        # Summary covers real rows only (cost 1+2, solar 0.5, demand 1.0, import 0.2, export 0.4)
        summary = data["summary"]
        assert summary["total_cost_gbp"] == pytest.approx(3.0)
        assert summary["total_solar_kwh"] == pytest.approx(0.5)
        assert summary["total_demand_kwh"] == pytest.approx(1.0)
        assert summary["total_grid_import_kwh"] == pytest.approx(0.2)
        assert summary["total_grid_export_kwh"] == pytest.approx(0.4)
        # export revenue uses export_price_pence: (0.2*6 + 0.2*4.8)/100
        assert summary["total_grid_export_revenue_gbp"] == pytest.approx((0.2 * 6.0 + 0.2 * 4.8) / 100.0)

    @patch('app.api.routes.get_optimiser_inputs')
    def test_optimise_mvp_requires_initial_soc(self, mock_inputs, client, mock_realtime):
        """With no initial SOC and no live SOC, refuse rather than guess 50%."""
        mock_inputs.return_value = pd.DataFrame({
            "period_end": pd.date_range("2025-09-20", periods=4, freq="30min", tz="UTC"),
            "pv_estimate": [0.0, 0.5, 1.0, 0.3],
            "price": [15.0, 12.0, 50.0, 20.0],
            "export_price": [6.0, 4.8, 20.0, 8.0],
            "demand": [0.5, 0.5, 0.5, 0.5]
        })
        mock_realtime.return_value = {"soc_pct": None, "history": [], "error": "no FoxESS creds"}

        response = client.post("/optimise/mvp", json={})
        assert response.status_code == 400
        assert "Initial SOC required" in response.json()["detail"]
