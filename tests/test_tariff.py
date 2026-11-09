"""Tariff switching: Cosy/Agile/Fixed import vectors and export handling."""
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import verify_token
from app.services import octopus, tariff as tariff_module
from app.services.tariff import (
    normalise_tariff,
    resolve_prices,
    cosy_prices,
    upsert_tariff,
)


def _index(start: str, periods: int = 48) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="30min", tz="UTC")


@pytest.fixture
def no_live_rates():
    """Default: the Octopus API is unavailable, so windows/config are used."""
    with patch.object(tariff_module.octopus, "get_standard_unit_rates", return_value=None):
        yield


class TestNormalise:
    def test_legacy_row_is_agile_with_cosy_defaults_available(self):
        t = normalise_tariff(
            {"import_type": "agile", "export_type": "agile", "config_json": {"region_code": "L"}}
        )
        assert t["import_type"] == "agile"
        assert t["export_type"] == "agile"
        assert t["region_code"] == "L"
        assert t["import"]["rates"]["cheap_pence"] > 0
        assert t["import"]["windows"]["cheap"][0] == ["04:00", "07:00"]

    def test_unknown_type_falls_back_to_agile(self):
        assert normalise_tariff({"import_type": "time_of_use"})["import_type"] == "agile"

    def test_upsert_rejects_unknown_type(self):
        with pytest.raises(ValueError):
            upsert_tariff("site", "time_of_use", "agile", {})


class TestCosyWindows:
    @pytest.fixture(autouse=True)
    def _offline(self, no_live_rates):
        yield

    def test_winter_windows(self):
        """GMT: local time == UTC. Slot start decides the window."""
        tariff = normalise_tariff({"import_type": "cosy"})
        index = _index("2026-11-09 00:30", periods=50)
        prices = cosy_prices(index, tariff)
        by_end = dict(zip(index, prices))

        def at(hhmm, day="2026-11-09"):
            ts = pd.Timestamp(f"{day} {hhmm}", tz="UTC")
            return by_end[ts]

        # Slot ending 04:30 covers 04:00-04:30 -> cheap
        assert at("04:30") == tariff["import"]["rates"]["cheap_pence"]
        # Last cheap slot is 06:30-07:00, ending 07:00
        assert at("07:00") == tariff["import"]["rates"]["cheap_pence"]
        # 07:00-07:30 is day
        assert at("07:30") == tariff["import"]["rates"]["day_pence"]
        # Peak 16:00-19:00
        assert at("16:30") == tariff["import"]["rates"]["peak_pence"]
        assert at("19:00") == tariff["import"]["rates"]["peak_pence"]
        assert at("19:30") == tariff["import"]["rates"]["day_pence"]
        # 22:00-24:00 cheap
        assert at("22:30") == tariff["import"]["rates"]["cheap_pence"]
        assert at("00:30", "2026-11-10") == tariff["import"]["rates"]["day_pence"]

    def test_windows_follow_bst(self):
        """July (BST): 04:00 local is 03:00 UTC, so the window shifts in UTC."""
        tariff = normalise_tariff({"import_type": "cosy"})
        index = _index("2026-07-15 02:30")
        prices = cosy_prices(index, tariff)
        by_end = dict(zip(index, prices))
        # 03:30 UTC = 04:30 local -> cheap
        assert by_end[pd.Timestamp("2026-07-15 03:30", tz="UTC")] == tariff["import"]["rates"]["cheap_pence"]
        # 02:30 UTC = 03:30 local -> day
        assert by_end[pd.Timestamp("2026-07-15 02:30", tz="UTC")] == tariff["import"]["rates"]["day_pence"]

    def test_live_api_rates_win(self):
        """Published Octopus rates override the configured fallback."""
        tariff = normalise_tariff({"import_type": "cosy"})
        index = _index("2026-11-09 00:30", periods=4)
        live = [{
            "valid_from": datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc),
            "pence": 99.0,
        }]
        with patch.object(tariff_module.octopus, "get_standard_unit_rates", return_value=live):
            prices = cosy_prices(index, tariff)
        assert list(prices) == [99.0, 99.0, 99.0, 99.0]

    def test_api_gap_falls_back_to_windows(self):
        tariff = normalise_tariff({"import_type": "cosy"})
        index = _index("2026-11-09 00:30", periods=2)
        live = [{
            "valid_from": datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 11, 9, 0, 30, tzinfo=timezone.utc),
            "pence": 99.0,
        }]
        with patch.object(tariff_module.octopus, "get_standard_unit_rates", return_value=live):
            prices = cosy_prices(index, tariff)
        assert prices.iloc[0] == 99.0
        assert prices.iloc[1] == tariff["import"]["rates"]["day_pence"]


class TestResolvePrices:
    @pytest.fixture(autouse=True)
    def _offline(self, no_live_rates):
        yield

    def test_agile_passthrough_and_synthetic_tail(self):
        tariff = normalise_tariff({"import_type": "agile", "export_type": "agile"})
        index = _index("2026-11-09 00:30", periods=3)
        imp, exp, synthetic = resolve_prices(
            tariff,
            pd.Series(index),
            agile_import=pd.Series([10.0, None, 20.0]),
            agile_export=pd.Series([8.0, 9.0, None]),
            avg_import=pd.Series([5.0, 5.0, 5.0]),
            avg_export=pd.Series([1.0, 1.0, 1.0]),
        )
        assert list(imp) == [10.0, 5.0, 20.0]
        assert list(exp) == [8.0, 9.0, 1.0]
        # slot 1: import estimated; slot 2: export estimated
        assert list(synthetic) == [False, True, True]

    def test_cosy_import_is_never_synthetic_but_export_can_be(self):
        tariff = normalise_tariff({"import_type": "cosy", "export_type": "agile"})
        index = _index("2026-11-09 00:30", periods=2)
        imp, exp, synthetic = resolve_prices(
            tariff,
            pd.Series(index),
            agile_import=pd.Series([10.0, 10.0]),  # ignored on Cosy
            agile_export=pd.Series([8.0, None]),
        )
        assert list(imp) == [tariff["import"]["rates"]["day_pence"]] * 2
        assert list(synthetic) == [False, True]

    def test_fixed_import_and_export(self):
        tariff = normalise_tariff({
            "import_type": "fixed",
            "export_type": "fixed",
            "config_json": {"import": {"flat_pence": 24.5}, "export": {"flat_pence": 15.0}},
        })
        index = _index("2026-11-09 00:30", periods=2)
        imp, exp, synthetic = resolve_prices(tariff, pd.Series(index))
        assert list(imp) == [24.5, 24.5]
        assert list(exp) == [15.0, 15.0]
        assert not synthetic.any()

    def test_cosy_peak_is_more_expensive_than_cheap(self):
        tariff = normalise_tariff({"import_type": "cosy"})
        index = _index("2026-11-09 03:30", periods=30)  # 03:30 -> 18:00
        prices = cosy_prices(index, tariff)
        assert prices.max() == tariff["import"]["rates"]["peak_pence"]
        assert prices.min() == tariff["import"]["rates"]["cheap_pence"]


class TestOctopusClient:
    def test_parse_rates_and_cache(self):
        octopus.clear_cache()
        payload = {
            "results": [
                {"valid_from": "2026-11-09T00:00:00Z", "valid_to": "2026-11-09T04:00:00Z", "value_inc_vat": 27.72},
                {"valid_from": "2026-11-09T04:00:00Z", "valid_to": "2026-11-09T07:00:00Z", "value_inc_vat": 13.59},
            ],
            "next": None,
        }

        class FakeResponse:
            ok = True

            def json(self):
                return payload

        with patch.object(octopus.requests, "get", return_value=FakeResponse()) as get:
            rates = octopus.get_standard_unit_rates(
                "COSY-22-12-08", "E",
                datetime(2026, 11, 9, tzinfo=timezone.utc),
                datetime(2026, 11, 10, tzinfo=timezone.utc),
            )
            assert rates is not None
            assert rates[0]["pence"] == 27.72  # sorted by valid_from
            assert rates[1]["pence"] == 13.59
            # Second call is served from cache
            octopus.get_standard_unit_rates(
                "COSY-22-12-08", "E",
                datetime(2026, 11, 9, tzinfo=timezone.utc),
                datetime(2026, 11, 10, tzinfo=timezone.utc),
            )
            assert get.call_count == 1
        octopus.clear_cache()

    def test_failure_returns_none(self):
        octopus.clear_cache()

        class FakeResponse:
            ok = False
            status_code = 500

        with patch.object(octopus.requests, "get", return_value=FakeResponse()):
            assert octopus.get_standard_unit_rates(
                "COSY-22-12-08", "E",
                datetime(2026, 11, 9, tzinfo=timezone.utc),
                datetime(2026, 11, 10, tzinfo=timezone.utc),
            ) is None
        octopus.clear_cache()


class TestTariffRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        def _fake_verify():
            return {"sub": "test-user-id", "email": "test@example.com"}

        app.dependency_overrides[verify_token] = _fake_verify
        with patch("app.api.routes.get_user_site") as site:
            site.return_value = {"id": "test-site-id", "user_id": "test-user-id"}
            yield
        app.dependency_overrides.clear()

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_get_returns_active_tariff(self, client):
        with patch("app.api.routes.get_active_tariff") as get_tariff:
            get_tariff.return_value = normalise_tariff(
                {"import_type": "cosy", "export_type": "agile"}
            )
            resp = client.get("/tariff")
        assert resp.status_code == 200
        assert resp.json()["tariff"]["import_type"] == "cosy"
        assert resp.json()["live_rates"] is None

    def test_put_switches_tariff(self, client):
        with patch("app.api.routes.upsert_tariff") as upsert:
            upsert.return_value = normalise_tariff(
                {"import_type": "cosy", "export_type": "agile"}
            )
            resp = client.put(
                "/tariff",
                json={
                    "import_type": "cosy",
                    "export_type": "agile",
                    "config_json": {"region_code": "L"},
                },
            )
        assert resp.status_code == 200
        upsert.assert_called_once()
        assert upsert.call_args.args[1] == "cosy"
        assert upsert.call_args.args[2] == "agile"

    def test_put_rejects_unknown_tariff(self, client):
        with patch("app.api.routes.upsert_tariff", side_effect=ValueError("bad tariff")):
            resp = client.put("/tariff", json={"import_type": "nonsense", "export_type": "agile"})
        assert resp.status_code == 400
        assert "bad tariff" in resp.json()["detail"]
