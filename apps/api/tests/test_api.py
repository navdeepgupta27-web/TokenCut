"""End-to-end tests through the ASGI app.

Runs with no provider credentials configured — which is the point: the service
must boot and stay useful with the OpenAI path alone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_reports_per_provider_status(client):
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["providers"]["openai"]["available"] is True
    assert body["providers"]["openai"]["local"] is True
    assert body["providers"]["anthropic"]["offsets"] is False
    assert "X-Request-Id" in resp.headers


def test_models_separates_counting_availability_from_pricing(client):
    body = client.get("/v1/models").json()
    by_id = {m["id"]: m for m in body["models"]}

    gpt = by_id["gpt-4o"]
    assert gpt["counting"] == "offline"
    assert gpt["supports_offsets"] is True
    assert gpt["pricing_verified"] is True
    assert gpt["input_per_mtok"] == 2.5
    assert gpt["output_per_mtok"] == 10.0

    claude = by_id["claude-opus-5"]
    # Countable exactly, but only via a keyed endpoint and with no offsets.
    assert claude["supports_offsets"] is False
    assert claude["pricing_verified"] is True
    assert claude["input_per_mtok"] == 5.0


def test_every_priced_model_carries_a_source_and_date(client):
    """The no-fabricated-numbers policy, enforced through the public API."""
    body = client.get("/v1/models").json()
    for model in body["models"]:
        if model["pricing_verified"]:
            assert model["pricing_source_url"], f"{model['id']} priced with no source"
            assert model["pricing_retrieved_at"], f"{model['id']} priced with no date"


def test_tokenize_returns_source_on_every_result(client):
    resp = client.post(
        "/v1/tokenize",
        json={"text": "Hello, world!", "models": ["gpt-4o", "claude-opus-5"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    for result in body["results"]:
        assert result["source"] in {
            "exact_local", "exact_api", "cached", "estimated", "unavailable",
        }

    by_model = {r["model"]: r for r in body["results"]}
    assert by_model["gpt-4o"]["source"] == "exact_local"
    assert by_model["gpt-4o"]["tokens"] > 0

    # With no ANTHROPIC_API_KEY configured, Claude must degrade to a clearly
    # marked estimate rather than failing the request or faking an exact count.
    claude = by_model["claude-opus-5"]
    assert claude["source"] in {"estimated", "unavailable"}
    if claude["source"] == "estimated":
        assert claude["calibrated"] is False, "uncalibrated ratio must say so"


def test_offsets_warning_names_the_models_that_cannot_provide_them(client):
    body = client.post(
        "/v1/tokenize",
        json={
            "text": "Hello there",
            "models": ["gpt-4o", "claude-opus-5"],
            "include_offsets": True,
        },
    ).json()
    by_model = {r["model"]: r for r in body["results"]}
    assert by_model["gpt-4o"]["offsets"]
    assert by_model["claude-opus-5"]["offsets"] is None
    assert any("claude-opus-5" in w for w in body["warnings"])


def test_optimize_applies_lossless_and_only_suggests_the_rest(client):
    body = client.post(
        "/v1/optimize",
        json={"text": "Please  clean   this  up.\r\n\r\n\r\nThank you!", "profile": "balanced"},
    ).json()

    assert body["tokens_after"] < body["tokens_before"]
    assert "Please" in body["optimized_text"], "politeness must not be auto-removed"

    applied_ids = {a["rule_id"] for a in body["applied"]}
    assert "collapse_spaces" in applied_ids

    suggested_ids = {s["rule_id"] for s in body["suggested"]}
    assert "flag_politeness" in suggested_ids
    for suggestion in body["suggested"]:
        assert suggestion["semantic_risk_note"]


def test_rules_endpoint_drives_the_frontend_toggles(client):
    body = client.get("/v1/rules").json()
    ids = {r["id"] for r in body["rules"]}
    assert {"collapse_spaces", "compact_json", "flag_politeness"} <= ids
    politeness = next(r for r in body["rules"] if r["id"] == "flag_politeness")
    assert politeness["suggestion_only"] is True
    assert politeness["default_in"] == []


def test_cost_uses_real_sourced_prices(client):
    body = client.post(
        "/v1/cost",
        json={
            "tokens_in_before": 10_000,
            "tokens_in_after": 8_000,
            "tokens_out": 500,
            "calls_per_month": 30_000,
            "models": ["claude-opus-5", "gpt-4o"],
        },
    ).json()
    by_model = {r["model"]: r for r in body["results"]}

    # 2,000 input tokens saved at $5/MTok = $0.01/call = $300/month.
    claude = by_model["claude-opus-5"]
    assert claude["available"] is True
    assert claude["saved_per_call"] == pytest.approx(0.01)
    assert claude["saved_per_month"] == pytest.approx(300.0)

    # Same tokens at $2.50/MTok = half of that.
    gpt = by_model["gpt-4o"]
    assert gpt["available"] is True
    assert gpt["saved_per_call"] == pytest.approx(0.005)

    assert body["assumptions"]


def test_cost_still_suppresses_a_model_with_no_price(client):
    """The suppression path must survive the catalog being populated."""
    body = client.post(
        "/v1/cost",
        json={
            "tokens_in_before": 1_000,
            "tokens_in_after": 500,
            "models": ["definitely-not-a-real-model"],
        },
    ).json()
    row = body["results"][0]
    assert row["available"] is False
    assert row["saved_per_call"] is None
    assert any("Excluded from cost totals" in w for w in body["warnings"])


def test_tiered_model_prices_each_side_at_its_own_band(client):
    """Gemini Pro doubles above 200k input tokens.

    Dropping under the threshold changes the RATE, not just the count, so the
    saving must exceed what the token delta alone would give.
    """
    body = client.post(
        "/v1/cost",
        json={
            "tokens_in_before": 250_000,
            "tokens_in_after": 190_000,
            "calls_per_month": 1,
            "models": ["gemini-2.5-pro"],
        },
    ).json()
    row = body["results"][0]
    assert row["available"] is True
    assert row["crossed_pricing_tier"] is True

    # before: 250k @ $2.50/MTok = $0.625 ; after: 190k @ $1.25/MTok = $0.2375
    assert row["cost_before_per_call"] == pytest.approx(0.625)
    assert row["cost_after_per_call"] == pytest.approx(0.2375)
    assert row["saved_per_call"] == pytest.approx(0.3875)

    # Naively pricing 60k saved tokens at the low band would give $0.075 —
    # under a fifth of the real saving. The assumption must explain why.
    assert any("cheaper pricing band" in a for a in body["assumptions"])


def test_analyze_prices_each_model_with_its_own_token_counts(client):
    body = client.post(
        "/v1/analyze",
        json={
            "text": 'Records:\n[{"id": 1, "n": "a"}, {"id": 2, "n": "b"}]\n\nPlease  summarise.',
            "models": ["gpt-4o", "claude-opus-5"],
            "profile": "balanced",
            "tokens_out": 300,
            "calls_per_month": 1000,
        },
    ).json()

    assert body["optimize"]["tokens_after"] < body["optimize"]["tokens_before"]
    assert len(body["tokenize"]["results"]) == 2
    assert len(body["tokenize_optimized"]["results"]) == 2
    assert {r["model"] for r in body["cost"]["results"]} == {"gpt-4o", "claude-opus-5"}


def test_oversized_text_is_rejected_with_the_error_envelope(client):
    resp = client.post(
        "/v1/tokenize",
        json={"text": "x" * 500_000, "models": ["gpt-4o"]},
    )
    assert resp.status_code == 413
    error = resp.json()["error"]
    assert error["code"] == "text_too_large"
    assert error["request_id"]


def test_unknown_model_degrades_instead_of_500ing(client):
    body = client.post(
        "/v1/tokenize", json={"text": "hi", "models": ["totally-made-up-model"]}
    ).json()
    assert body["results"][0]["source"] == "unavailable"
    assert body["results"][0]["tokens"] is None


def test_validation_error_uses_the_same_envelope(client):
    resp = client.post("/v1/tokenize", json={"text": "hi"})  # models missing
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


def test_cors_preflight_allows_the_configured_origin(client):
    resp = client.options(
        "/v1/tokenize",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
