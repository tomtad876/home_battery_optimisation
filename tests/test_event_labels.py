"""Tests for appliance-labelling calibration logic (demand-forecasting Phase 2).

Covers the two things this change introduced:
- the detector suggestion heuristic (which previously emitted high-confidence
  "cosy" for flat overnight runs that are actually the heat pump's heating mode);
- the cleanliness schema gate on labelled events.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.core.auth import verify_token
from app.services.event_detector import _suggest
from app.api.routes import _inventory_to_dict
from app.models.demandevent import DemandDayInventory


@pytest.fixture(autouse=True)
def mock_auth():
    app.dependency_overrides[verify_token] = lambda: {"sub": "test-user-id"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_user_site():
    with patch("app.api.routes.get_user_site") as mock:
        mock.return_value = {"id": "test-site-id", "user_id": "test-user-id", "name": "Test"}
        yield mock


@pytest.fixture
def client():
    return TestClient(app)


class TestSuggest:
    """Heuristic suggestions — deliberately capped below the 'confident' badge."""

    def test_long_steady_run_suggests_heating_not_cosy(self):
        # The documented mislabel: a long, flat overnight run is the heat pump's
        # space-heating mode, not the Cosy (same appliance, other mode).
        appliance, conf = _suggest(hod=3.0, mean_kw=2.9, flatness=0.1, dur_min=120)
        assert appliance == "heating"
        assert conf < 0.7

    def test_midday_steady_run_suggests_cosy(self):
        appliance, conf = _suggest(hod=11.5, mean_kw=1.4, flatness=0.1, dur_min=35)
        assert appliance == "cosy"
        assert conf < 0.7

    def test_no_suggestion_is_ever_confident(self):
        # Nothing is trustworthy enough for the confident badge until templates
        # are fit from clean labels.
        for hod in (2, 3, 11, 13, 17, 20):
            for mean_kw in (0.6, 1.4, 2.9):
                for flatness in (0.05, 0.4):
                    for dur_min in (20, 60, 120):
                        _, conf = _suggest(hod, mean_kw, flatness, dur_min)
                        assert conf < 0.7

    def test_duty_cycled_run_is_not_preloaded_as_cosy(self):
        appliance, _ = _suggest(hod=3.0, mean_kw=1.2, flatness=0.4, dur_min=40)
        assert appliance in {"washing_machine", "dishwasher"}


class TestCleanlinessValidation:
    def test_create_rejects_unknown_cleanliness(self, client):
        resp = client.post("/events", json={
            "appliance": "cosy",
            "start_time": "2026-09-20T02:00:00Z",
            "cleanliness": "definitely",
        })
        assert resp.status_code == 422


class TestInventorySerialisation:
    def test_inventory_dict_shape(self):
        row = DemandDayInventory(
            day=date(2026, 9, 20),
            appliances=["cosy", "washing_machine"],
            notes="guests over",
        )
        assert _inventory_to_dict(row) == {
            "day": "2026-09-20",
            "appliances": ["cosy", "washing_machine"],
            "notes": "guests over",
        }

    def test_inventory_null_appliances_serialises_as_empty_list(self):
        row = DemandDayInventory(day=date(2026, 9, 21), appliances=None)
        assert _inventory_to_dict(row)["appliances"] == []
