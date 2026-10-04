"""Holiday mode: site endpoint + baseload/planned-event demand composition."""
import pandas as pd
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import verify_token
from app.services import data_provider
from app.services.data_provider import _add_planned_events, _holiday_active


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal stand-in for a SQLAlchemy session returning canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.last_sql = None
        self.last_params = None

    def execute(self, sql, params=None):
        self.last_sql = str(sql)
        self.last_params = params
        return _Result(self._rows)


# --- _holiday_active ------------------------------------------------------

class TestHolidayActive:
    def test_false_when_flag_off(self):
        s = _FakeSession([{"holiday_mode": False, "holiday_until": None}])
        assert _holiday_active(s, "site-1") is False

    def test_true_when_flag_on_no_expiry(self):
        s = _FakeSession([{"holiday_mode": True, "holiday_until": None}])
        assert _holiday_active(s, "site-1") is True

    def test_false_after_expiry(self):
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        s = _FakeSession([{"holiday_mode": True, "holiday_until": expired}])
        assert _holiday_active(s, "site-1") is False

    def test_true_before_expiry(self):
        future = datetime.now(timezone.utc) + timedelta(days=2)
        s = _FakeSession([{"holiday_mode": True, "holiday_until": future}])
        assert _holiday_active(s, "site-1") is True

    def test_false_when_no_site(self):
        assert _holiday_active(_FakeSession([]), "site-1") is False


# --- _add_planned_events --------------------------------------------------

def _slot_frame(start, n):
    return pd.DataFrame({
        "period_end": pd.date_range(start, periods=n, freq="30min", tz="UTC"),
        "demand": [0.05] * n,
    })


class TestAddPlannedEvents:
    def _event(self, appliance, start_offset_min, dur_min, energy=None):
        base = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
        return {
            "appliance": appliance,
            "start_time": base + timedelta(minutes=start_offset_min),
            "end_time": base + timedelta(minutes=start_offset_min + dur_min),
            "energy_kwh": energy,
        }

    def test_energy_spread_across_overlapping_slots(self):
        df = _slot_frame("2026-10-10 00:00", 9)  # 00:00–04:00
        # 03:00–04:00, explicitly 1.0 kWh → 2 half-hour slots of 0.5 each
        s = _FakeSession([self._event("cosy", 180, 60, energy=1.0)])
        _add_planned_events(df, s, "site-1", datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc))

        # slots ending 03:30 and 04:00 get +0.5; others unchanged
        got = dict(zip(df["period_end"].dt.strftime("%H:%M"), df["demand"]))
        assert got["03:30"] == pytest.approx(0.55)
        assert got["04:00"] == pytest.approx(0.55)
        assert got["02:00"] == pytest.approx(0.05)

    def test_fallback_energy_when_none(self):
        df = _slot_frame("2026-10-10 02:00", 2)  # ends 02:30, 03:00
        s = _FakeSession([self._event("cosy", 120, 30, energy=None)])
        _add_planned_events(df, s, "site-1", datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc))
        # fallback cosy = 0.8 kWh in the slot ending 02:30
        assert df["demand"].tolist() == [pytest.approx(0.05), pytest.approx(0.85)]

    def test_event_outside_horizon_ignored(self):
        df = _slot_frame("2026-10-10 00:00", 4)
        s = _FakeSession([])  # query filtered it out upstream
        before = df["demand"].tolist()
        _add_planned_events(df, s, "site-1", datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc))
        assert df["demand"].tolist() == before


# --- PATCH /sites/me ------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_auth():
    app.dependency_overrides[verify_token] = lambda: {"sub": "test-user-id"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestPatchSite:
    def test_sets_holiday_mode(self, client):
        with patch("app.api.routes.get_user_site") as mock_site, \
             patch("app.api.routes.update_site_holiday") as mock_update:
            mock_site.return_value = {"id": "site-1", "name": "Home", "holiday_mode": False}
            mock_update.return_value = {"id": "site-1", "holiday_mode": True, "holiday_until": None}
            resp = client.patch("/sites/me", json={"holiday_mode": True})
            assert resp.status_code == 200
            assert resp.json()["site"]["holiday_mode"] is True
            assert mock_update.call_args.args[1] == {"holiday_mode": True}

    def test_clears_holiday_until_explicitly(self, client):
        with patch("app.api.routes.get_user_site") as mock_site, \
             patch("app.api.routes.update_site_holiday") as mock_update:
            mock_site.return_value = {"id": "site-1", "name": "Home"}
            mock_update.return_value = {"id": "site-1", "holiday_mode": True, "holiday_until": None}
            resp = client.patch("/sites/me", json={"holiday_until": None})
            assert resp.status_code == 200
            assert mock_update.call_args.args[1] == {"holiday_until": None}

    def test_no_site_returns_404(self, client):
        with patch("app.api.routes.get_user_site") as mock_site:
            mock_site.return_value = None
            resp = client.patch("/sites/me", json={"holiday_mode": True})
            assert resp.status_code == 404

    def test_empty_body_is_noop(self, client):
        with patch("app.api.routes.get_user_site") as mock_site, \
             patch("app.api.routes.update_site_holiday") as mock_update:
            mock_site.return_value = {"id": "site-1", "name": "Home"}
            resp = client.patch("/sites/me", json={})
            assert resp.status_code == 200
            mock_update.assert_not_called()
