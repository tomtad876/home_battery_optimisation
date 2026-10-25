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
from app.services.event_detector import _suggest, _as_utc
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


class TestAsUtc:
    """Stored timestamps -> aware UTC after the 2026-10-26 UTC migration.

    2026-10-25 (Sentry 3aeae13d): /events/detect 500'd with "Cannot infer dst
    time" because `period_end` was naive *local* and 01:00-02:00 happens twice.
    It is timestamptz now; naive leftovers are read as UTC.
    """

    def test_naive_is_read_as_utc(self):
        from datetime import datetime, timezone
        import pandas as pd
        assert _as_utc(pd.Timestamp("2026-10-25 01:03:32")) == datetime(
            2026, 10, 25, 1, 3, 32, tzinfo=timezone.utc
        )

    def test_offset_is_normalised(self):
        from datetime import datetime, timezone
        import pandas as pd
        # 11:03 BST is 10:03Z.
        assert _as_utc(pd.Timestamp("2026-07-15 11:03:33+01:00")) == datetime(
            2026, 7, 15, 10, 3, 33, tzinfo=timezone.utc
        )

    def test_aware_utc_is_passed_through(self):
        from datetime import datetime, timezone
        import pandas as pd
        ts = pd.Timestamp("2026-10-25 00:03:32", tz="UTC")
        assert _as_utc(ts) == datetime(2026, 10, 25, 0, 3, 32, tzinfo=timezone.utc)

    def test_both_passes_of_the_ambiguous_hour_are_distinct(self):
        from datetime import timezone
        import pandas as pd
        a = _as_utc(pd.Timestamp("2026-10-25 00:03:32", tz="UTC"))
        b = _as_utc(pd.Timestamp("2026-10-25 01:03:32", tz="UTC"))
        assert (b - a).total_seconds() == 3600
        assert a.tzinfo == timezone.utc and b.tzinfo == timezone.utc


class TestSuggest:
    """Heuristic suggestions — deliberately capped below the 'confident' badge."""

    def test_long_steady_run_suggests_heating_not_cosy(self):
        # The documented mislabel: a long, flat overnight run is the heat pump's
        # space-heating mode, not the Cosy (same appliance, other mode).
        appliance, conf = _suggest(3.0, 2.9, 3.0, 0.1, 120)
        assert appliance == "heating"
        assert conf < 0.7

    def test_midday_steady_run_suggests_cosy(self):
        appliance, conf = _suggest(11.5, 1.4, 1.5, 0.1, 35)
        assert appliance == "cosy"
        assert conf < 0.7

    def test_evening_multiring_suggests_hob(self):
        # Tom's 17:58 event: peak 3.46 kW over 30 min.
        appliance, _ = _suggest(17.96, 2.64, 3.46, 0.29, 30)
        assert appliance == "hob"

    def test_evening_long_sustained_suggests_oven(self):
        appliance, _ = _suggest(18.0, 2.0, 2.5, 0.3, 60)
        assert appliance == "oven"

    def test_short_low_power_evening_is_cooking_not_dishwasher(self):
        # The old heuristic called every evening spike a dishwasher; Tom's
        # evening loads are cooking.
        appliance, _ = _suggest(19.13, 1.95, 2.29, 0.19, 25)
        assert appliance == "cooking"

    def test_short_midday_flat_burst_is_not_confidently_cosy(self):
        # Tom labelled 2026-09-21 11:47 as a hob-only cook (1.29 kW, 15 min,
        # flatness 0.03) — the old heuristic would have said "cosy" at 0.60.
        appliance, conf = _suggest(11.78, 1.29, 1.29, 0.03, 15)
        assert appliance == "cooking"
        assert conf < 0.7

    def test_no_suggestion_is_ever_confident(self):
        # Nothing is trustworthy enough for the confident badge until templates
        # are fit from clean labels.
        for hod in (2, 3, 11, 13, 17, 20):
            for mean_kw in (0.6, 1.4, 2.9):
                for flatness in (0.05, 0.4):
                    for dur_min in (20, 60, 120):
                        _, conf = _suggest(hod, mean_kw, mean_kw * 1.3, flatness, dur_min)
                        assert conf < 0.7

    def test_duty_cycled_run_is_not_preloaded_as_cosy(self):
        appliance, _ = _suggest(3.0, 1.2, 1.5, 0.4, 40)
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
