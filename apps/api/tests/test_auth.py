"""Internal-token gate.

A publicly reachable backend with no gate is an open proxy to the operator's
Anthropic and Google quota. These tests pin both halves: off by default so
local development stays trivial, enforced the moment a token is configured.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-internal-token-value"


def _client_with_token(monkeypatch, token: str | None):
    """Client with a specific token setting.

    The middleware reads `settings.api_internal_token` per request, so patching
    the live settings object is enough — the app does not need rebuilding.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "api_internal_token", token)
    import main

    return TestClient(main.app)


@pytest.fixture
def gated(monkeypatch):
    with _client_with_token(monkeypatch, TOKEN) as client:
        yield client


@pytest.fixture
def ungated(monkeypatch):
    with _client_with_token(monkeypatch, None) as client:
        yield client


# -- gate off (local development default) ----------------------------------


def test_no_token_configured_means_no_gate(ungated):
    assert ungated.post(
        "/v1/tokenize", json={"text": "hi", "models": ["gpt-4o"]}
    ).status_code == 200


# -- gate on ----------------------------------------------------------------


def test_request_without_a_token_is_rejected(gated):
    resp = gated.post("/v1/tokenize", json={"text": "hi", "models": ["gpt-4o"]})
    assert resp.status_code == 401
    error = resp.json()["error"]
    assert error["code"] == "unauthorized"
    assert error["request_id"]


def test_request_with_the_wrong_token_is_rejected(gated):
    resp = gated.post(
        "/v1/tokenize",
        json={"text": "hi", "models": ["gpt-4o"]},
        headers={"Authorization": "Bearer not-the-right-token"},
    )
    assert resp.status_code == 401


def test_wrong_scheme_is_rejected(gated):
    """Basic auth carrying the right secret is still the wrong shape."""
    resp = gated.post(
        "/v1/tokenize",
        json={"text": "hi", "models": ["gpt-4o"]},
        headers={"Authorization": f"Basic {TOKEN}"},
    )
    assert resp.status_code == 401


def test_correct_token_passes(gated):
    resp = gated.post(
        "/v1/tokenize",
        json={"text": "hi", "models": ["gpt-4o"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["tokens"] > 0


@pytest.mark.parametrize("path", ["/health", "/v1/health", "/", "/openapi.json"])
def test_health_and_schema_stay_open(gated, path):
    """The platform's health check has no way to present a bearer token.

    Gating /health would make the service look permanently unhealthy and get
    it restarted in a loop.
    """
    assert gated.get(path).status_code == 200


def test_analyze_is_gated_too(gated):
    """The expensive endpoint is the one that actually needs protecting."""
    assert gated.post(
        "/v1/analyze", json={"text": "hi", "models": ["gpt-4o"]}
    ).status_code == 401
