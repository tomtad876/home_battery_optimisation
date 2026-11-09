"""Octopus Energy public product API.

Only the *product* endpoints are used, and they need no credentials: unit rates
are public tariff information. That is deliberate — the optimiser must not
depend on a customer API key just to know what the tariff costs.

Docs: https://developer.octopus.energy/rest/guides/
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.octopus.energy/v1"
# Unit rates change on a cap-review cadence (a few times a year), so an hour of
# caching is plenty and keeps a 30-minute cron from hammering the API.
CACHE_TTL_SECONDS = 3600
_REQUEST_TIMEOUT = 8

_cache: dict[str, tuple[float, list[dict]]] = {}


def tariff_code(product_code: str, region_code: str) -> str:
    """Standard variable single-rate tariff code, e.g. E-1R-COSY-22-12-08-E."""
    return f"E-1R-{product_code}-{region_code.upper()}"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def get_standard_unit_rates(
    product_code: str,
    region_code: str,
    period_from: datetime,
    period_to: datetime,
) -> list[dict] | None:
    """Return published unit rates overlapping ``[period_from, period_to]``.

    Each item is ``{"valid_from": datetime, "valid_to": datetime | None,
    "pence": float}`` with VAT included. Returns ``None`` on any failure so the
    caller can fall back to configured rates instead of failing the optimiser.
    """
    code = tariff_code(product_code, region_code)
    key = f"{code}:{period_from.date()}:{period_to.date()}"
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{BASE_URL}/products/{product_code}/electricity-tariffs/{code}/standard-unit-rates/"
    params = {
        "period_from": period_from.astimezone(timezone.utc).isoformat(),
        "period_to": period_to.astimezone(timezone.utc).isoformat(),
        "page_size": 250,
    }
    results: list[dict] = []
    try:
        # Follow `next` defensively; a 48 h horizon is normally one page.
        for _ in range(5):
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            if not resp.ok:
                return None
            payload = resp.json()
            for r in payload.get("results", []):
                valid_from = _parse_dt(r.get("valid_from"))
                if valid_from is None:
                    continue
                results.append(
                    {
                        "valid_from": valid_from,
                        "valid_to": _parse_dt(r.get("valid_to")),
                        "pence": float(r["value_inc_vat"]),
                    }
                )
            next_url = payload.get("next")
            if not next_url:
                break
            url, params = next_url, {}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None

    if not results:
        return None
    results.sort(key=lambda r: r["valid_from"])
    _cache[key] = (time.time(), results)
    return results


def clear_cache() -> None:
    """Drop cached rates (tests)."""
    _cache.clear()
