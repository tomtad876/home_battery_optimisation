"""CORS configuration tests.

Regression guard for the 2026-09-20 incident: the Vercel branch preview
(home-battery-optimisation-git-agent-63cd07-<team>.vercel.app) had every API call
blocked, because the Render allowlist held only the exact production origin.
Vercel issues a *new* hostname per branch preview, so an exact-origin allowlist
can never cover them — previews are allowed by pattern instead.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app, origin_regex, origins

PROD_ORIGIN = "https://home-battery-optimisation.vercel.app"
PREVIEW_ORIGIN = "https://home-battery-optimisation-git-agent-63cd07-tomtad876s-projects.vercel.app"
PER_DEPLOY_ORIGIN = "https://home-battery-optimisation-abc123-tomtad876s-projects.vercel.app"


def preflight(origin: str):
    client = TestClient(app)
    return client.options(
        "/sites/me",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


@pytest.mark.parametrize("origin", [PROD_ORIGIN, PREVIEW_ORIGIN, PER_DEPLOY_ORIGIN])
def test_allowed_origins_get_an_allow_origin_header(origin):
    response = preflight(origin)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_localhost_dev_origin_is_allowed():
    response = preflight("http://localhost:3000")
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_unrelated_origin_is_not_allowed():
    response = preflight("https://someone-elses-app.vercel.app")
    assert "access-control-allow-origin" not in response.headers


def test_preview_pattern_does_not_allow_arbitrary_vercel_apps():
    # The pattern must stay tight: any *.vercel.app would let any user's
    # deployment talk to this API.
    assert re.match(origin_regex, PREVIEW_ORIGIN)
    assert not re.match(origin_regex, "https://evil.vercel.app")
    assert not re.match(origin_regex, "https://home-battery-optimisation.evil.com")
    assert PROD_ORIGIN in origins


def test_preview_origin_can_reach_a_real_endpoint():
    """A blocked preflight is what broke the preview; check a plain GET too."""
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": PREVIEW_ORIGIN})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == PREVIEW_ORIGIN
