"""Pricing catalog and tokenizer-honesty tests.

These guard the two properties that make the product trustworthy: prices are
sourced, and a guess is never labelled a measurement.
"""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.schemas import CountSource
from app.services.pricing import PriceTier, load_catalog
from app.services.tokenizer.estimator import family_for, load_calibration
from app.services.tokenizer.openai_tiktoken import OpenAITokenizer

# --------------------------------------------------------------------------
# Catalog integrity
# --------------------------------------------------------------------------


def test_every_priced_model_has_a_source_and_a_date():
    catalog = load_catalog()
    assert catalog.models, "catalog should not be empty"
    for model in catalog.models.values():
        if model.input_per_mtok is not None:
            assert model.source_url, f"{model.id}: priced with no source_url"
            assert model.retrieved_at, f"{model.id}: priced with no retrieved_at"
            assert model.output_per_mtok is not None, f"{model.id}: input but no output price"


def test_no_placeholder_rows_are_served():
    """Rows prefixed `__` are documentation, not data."""
    catalog = load_catalog()
    assert not [m for m in catalog.models if m.startswith("__")]


def test_catalog_prices_are_positive():
    for model in load_catalog().models.values():
        for value in (model.input_per_mtok, model.output_per_mtok):
            if value is not None:
                assert value > 0, f"{model.id}: non-positive price"


def test_known_sourced_prices_match_the_catalog():
    """Spot-check figures read from the official pricing pages on 2026-09-04.

    If a provider changes a price, this test fails and forces a re-read of the
    source rather than letting a stale number sit in the UI.
    """
    catalog = load_catalog()
    expected = {
        "claude-opus-5": (5.0, 25.0),
        "claude-sonnet-5": (2.0, 10.0),
        "claude-haiku-4-5": (1.0, 5.0),
        "gpt-4o": (2.5, 10.0),
        "gpt-5": (1.25, 10.0),
        "gemini-2.5-flash": (0.3, 2.5),
    }
    for model_id, (inp, out) in expected.items():
        pricing = catalog.get(model_id)
        assert pricing is not None, f"{model_id} missing from catalog"
        assert pricing.input_per_mtok == inp, f"{model_id} input price changed"
        assert pricing.output_per_mtok == out, f"{model_id} output price changed"


def test_cache_read_multipliers_match_the_published_ratio():
    """A cache multiplier must be consistent with the published cached price."""
    catalog = load_catalog()
    # Anthropic publishes cache hits at 0.1x base for these models.
    for model_id in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"):
        assert catalog.models[model_id].cache_read_multiplier == pytest.approx(0.1)
    # OpenAI's GPT-4o cached input is $1.25 against $2.50 base = 0.5x, which is
    # a materially weaker discount than the GPT-5 family's 0.1x. Getting these
    # the same way round would misprice a cached workload by 5x.
    assert catalog.models["gpt-4o"].cache_read_multiplier == pytest.approx(0.5)
    assert catalog.models["gpt-5"].cache_read_multiplier == pytest.approx(0.1)


def test_unverified_batch_discounts_stay_null():
    """Neither the OpenAI nor Gemini page gave a computable per-model figure."""
    catalog = load_catalog()
    for model in catalog.models.values():
        if model.provider in {"openai", "google"}:
            assert model.batch_discount is None, (
                f"{model.id}: batch discount must stay unverified until sourced"
            )
        if model.provider == "anthropic":
            assert model.batch_discount == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Length-tiered pricing
# --------------------------------------------------------------------------


def test_gemini_pro_tiers_parse_and_select_correctly():
    pricing = load_catalog().get("gemini-2.5-pro")
    assert pricing is not None
    assert pricing.is_tiered

    assert pricing.input_price_for(1_000) == pytest.approx(1.25)
    assert pricing.input_price_for(200_000) == pytest.approx(1.25)  # boundary inclusive
    assert pricing.input_price_for(200_001) == pytest.approx(2.5)
    assert pricing.output_price_for(200_001) == pytest.approx(15.0)


def test_flat_models_are_not_tiered():
    pricing = load_catalog().get("gpt-4o")
    assert pricing is not None
    assert not pricing.is_tiered
    # A flat model must return the same price at any length.
    assert pricing.input_price_for(10) == pricing.input_price_for(10_000_000)


def test_crosses_tier_detects_a_threshold_move():
    pricing = load_catalog().get("gemini-2.5-pro")
    assert pricing is not None
    assert pricing.crosses_tier(250_000, 190_000) is True
    assert pricing.crosses_tier(250_000, 240_000) is False
    assert pricing.crosses_tier(100_000, 90_000) is False


def test_tier_list_without_an_open_band_is_rejected(tmp_path, monkeypatch):
    """A truncated tier list would leave long prompts unpriced.

    Dropping to the flat price is the safe failure: it is at least a figure
    someone sourced.
    """
    from app.services import pricing as pricing_module

    bad = {
        "models": [
            {
                "id": "broken",
                "provider": "test",
                "display_name": "Broken",
                "input_per_mtok": 1.0,
                "output_per_mtok": 2.0,
                # No open-ended final band.
                "input_tiers": [{"max_input_tokens": 1000, "price": 1.0}],
                "source_url": "https://example.com",
                "retrieved_at": "2026-09-01",
            }
        ]
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(settings, "pricing_catalog_path", path)
    pricing_module.load_catalog.cache_clear()

    model = pricing_module.load_catalog().get("broken")
    assert model is not None
    assert model.input_tiers == ()  # rejected wholesale
    assert model.input_price_for(5_000) == pytest.approx(1.0)  # flat fallback


def test_price_tier_selection_is_inclusive_at_the_boundary():
    tiers = (PriceTier(100, 1.0), PriceTier(None, 2.0))
    from app.services.pricing import ModelPricing

    assert ModelPricing._select(tiers, 100, None) == 1.0
    assert ModelPricing._select(tiers, 101, None) == 2.0


# --------------------------------------------------------------------------
# Tokenizer honesty: an inferred encoding is not exact
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_known_model_is_exact_with_offsets():
    result = await OpenAITokenizer().count("hello world", "gpt-4o", want_offsets=True)
    assert result.source is CountSource.EXACT_LOCAL
    assert result.offsets is not None
    assert result.note is None


@pytest.mark.anyio
async def test_unknown_model_is_downgraded_to_an_estimate():
    """tiktoken knows nothing about models newer than its release.

    GPT-4 (cl100k) to GPT-4o (o200k) already changed encoding once, so an
    inferred encoding is a real guess — it must not be reported as exact, and
    it must not draw a token map.
    """
    result = await OpenAITokenizer().count(
        "hello world", "gpt-99-imaginary", want_offsets=True
    )
    assert result.source is CountSource.ESTIMATED
    assert result.calibrated is False
    assert result.offsets is None, "a guessed encoding must not produce a token map"
    assert result.note and "does not recognise" in result.note
    assert result.tokens and result.tokens > 0  # still useful, just labelled


@pytest.mark.anyio
async def test_current_openai_registry_models_all_resolve_exactly():
    """Every OpenAI id in the registry must be known to the installed tiktoken.

    If this fails, someone added a model tiktoken cannot count exactly — either
    remove it or accept that it reports as an estimate.
    """
    from app.services.tokenizer.registry import KNOWN_MODELS

    tokenizer = OpenAITokenizer()
    for spec in KNOWN_MODELS:
        if spec.provider != "openai":
            continue
        result = await tokenizer.count("probe", spec.id)
        assert result.source is CountSource.EXACT_LOCAL, (
            f"{spec.id} is in the registry but tiktoken infers its encoding"
        )


# --------------------------------------------------------------------------
# Estimator families
# --------------------------------------------------------------------------


def test_tokenizer_generations_get_different_ratios():
    """Anthropic states the 4.7+ tokenizer yields ~30% more tokens.

    A single "Anthropic" ratio would therefore be wrong by roughly 30% for
    half the lineup.
    """
    families = load_calibration()["families"]
    older = families["anthropic_pre_4_7"]["ratio"]
    newer = families["anthropic_4_7_plus"]["ratio"]
    assert newer > older
    assert newer / older == pytest.approx(1.3, abs=0.02)


def test_models_map_to_the_right_family():
    assert family_for("claude-opus-5", "anthropic") == "anthropic_4_7_plus"
    assert family_for("claude-sonnet-4-6", "anthropic") == "anthropic_pre_4_7"
    assert family_for("gemini-2.5-pro", "google") == "google"


def test_unknown_anthropic_model_assumes_the_current_generation():
    """Under-counting a new model is the worse error — it understates cost."""
    assert family_for("claude-opus-9", "anthropic") == "anthropic_4_7_plus"


def test_google_has_no_ratio_so_produces_no_estimate():
    """No sourced ratio means '—', not a plausible-looking number."""
    assert load_calibration()["families"]["google"]["ratio"] is None


def test_shipped_ratios_are_marked_uncalibrated():
    """They are derived from published prose, not measured. Say so."""
    for entry in load_calibration()["families"].values():
        assert entry["calibrated"] is False
        assert entry["error_p90"] is None
