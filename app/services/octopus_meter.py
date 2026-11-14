"""Octopus half-hourly meter readings (import and export).

The supplier's meter is the authority for money: on Tom's site the inverter
under-reads grid import by ~8%, and export is billed from the meter, not from
the inverter. Where a site has Octopus credentials we use the meter; where it
doesn't, cost history falls back to FoxESS.

Read-only: this module never touches the account, only the consumption endpoints.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.encryption import decrypt_provider_config

REST = 'https://api.octopus.energy/v1'
TIMEOUT = 60
PAGE_SIZE = 1500


def _credentials(site_id: str) -> tuple[str, str] | None:
    session = SessionLocal()
    try:
        row = session.execute(
            text(
                """SELECT provider_config FROM batteries
                   WHERE site_id = :sid LIMIT 1"""
            ),
            {"sid": site_id},
        ).mappings().first()
    finally:
        session.close()
    if not row or not row['provider_config']:
        return None

    raw = row['provider_config']
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    try:
        cfg = decrypt_provider_config(raw['encrypted']) if 'encrypted' in raw else raw
    except Exception:
        return None

    key = cfg.get('octopus_api_key')
    account = cfg.get('octopus_account_number')
    return (key, account) if key and account else None


def _meter_points(key: str, account: str) -> dict[str, dict] | None:
    """{'import': {...}, 'export': {...}} with mpan and the smart meter serial."""
    try:
        acct = requests.get(f'{REST}/accounts/{account}/', auth=(key, ''), timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        return None

    points: dict[str, dict] = {}
    for prop in acct.get('properties', []):
        for mp in prop.get('electricity_meter_points', []):
            meters = mp.get('meters', [])
            # the smart meter is the serial that carries agreements
            smart = [m.get('serial_number') for m in meters if m.get('agreements')] or \
                    [m.get('serial_number') for m in meters]
            direction = 'export' if mp.get('is_export') else 'import'
            points[direction] = {'mpan': str(mp['mpan']), 'serial': smart[-1] if smart else None}
    return points or None


def _consumption(key: str, mpan: str, serial: str, start: datetime, end: datetime) -> dict:
    """Half-hourly kWh keyed by slot start (UTC)."""
    out: dict[datetime, float] = {}
    url = f'{REST}/electricity-meter-points/{mpan}/meters/{serial}/consumption/'
    params = {'period_from': start.isoformat(), 'period_to': end.isoformat(), 'page_size': PAGE_SIZE}
    pages = 0
    while url:
        try:
            r = requests.get(url, auth=(key, ''), params=params, timeout=TIMEOUT)
        except requests.RequestException:
            return out
        if r.status_code != 200:
            return out
        body = r.json()
        for item in body.get('results', []):
            slot = datetime.fromisoformat(item['interval_start']).astimezone(timezone.utc).replace(tzinfo=None)
            out[slot] = float(item['consumption'])
        url, params = body.get('next'), None
        pages += 1
        if pages > 200:
            break
    return out


def fetch_half_hourly(site_id: str, start: datetime, end: datetime) -> dict | None:
    """{'import': {slot: kwh}, 'export': {slot: kwh}} or None when unavailable.

    Returns None (never raises) so a missing API key or an outage simply falls
    back to inverter data rather than breaking the backfill.
    """
    creds = _credentials(site_id)
    if not creds:
        return None
    key, account = creds
    points = _meter_points(key, account)
    if not points:
        return None

    out: dict[str, dict] = {}
    for direction in ('import', 'export'):
        point = points.get(direction)
        if not point or not point.get('serial'):
            continue
        data = _consumption(key, point['mpan'], point['serial'], start, end)
        if data:
            out[direction] = data
    return out or None
