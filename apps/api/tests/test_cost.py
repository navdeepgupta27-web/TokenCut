"""Cost engine — the honesty tests.

The behaviours asserted here are the ones that separate this calculator from
the ones that quietly inflate savings.
"""

from __future__ import annotations

from app.schemas import CostRequest
from app.services.cost import compute_cost
from app.services.pricing import Catalog, ModelPricing

PRICED = ModelPricing(
    id="test-model",
    provider="test",
    display_name="Test Model",
    input_per_mtok=5.0,
    output_per_mtok=25.0,
    cache_read_multiplier=0.1,
    cache_write_multiplier=1.25,
    batch_discount=0.5,
    context_window=200_000,
    source_url="https://example.com/pricing",
    retrieved_at="2026-09-01",
    notes=None,
)

UNVERIFIED = ModelPricing(
    id="unpriced-model",
    provider="test",
    display_name="Unpriced Model",
    input_per_mtok=None,
    output_per_mtok=None,
    cache_read_multiplier=None,
    cache_write_multiplier=None,
    batch_discount=None,
    context_window=None,
    source_url="https://example.com/pricing",
    retrieved_at=None,
    notes=None,
)

CATALOG = Catalog(models={"test-model": PRICED, "unpriced-model": UNVERIFIED})


def test_saving_is_input_side_only_and_output_cancels():
    """The core equation. Output length is unchanged by compression."""
    low_out = compute_cost(
        CostRequest(
            tokens_in_before=10_000, tokens_in_after=8_000,
            tokens_out=100, calls_per_month=1, models=["test-model"],
        ),
        CATALOG,
    )
    high_out = compute_cost(
        CostRequest(
            tokens_in_before=10_000, tokens_in_after=8_000,
            tokens_out=100_000, calls_per_month=1, models=["test-model"],
        ),
        CATALOG,
    )
    # A 1000x change in output tokens must not move the saving at all.
    assert low_out.results[0].saved_per_call == high_out.results[0].saved_per_call
    # 2,000 tokens saved at $5/1M
    assert low_out.results[0].saved_per_call == 2_000 / 1_000_000 * 5.0


def test_the_output_cancellation_is_stated_in_the_assumptions():
    resp = compute_cost(
        CostRequest(
            tokens_in_before=100, tokens_in_after=90,
            tokens_out=50, calls_per_month=1, models=["test-model"],
        ),
        CATALOG,
    )
    joined = " ".join(resp.assumptions).lower()
    assert "input tokens only" in joined
    assert "output cost is unchanged" in joined or "output cost" in joined


def test_unverified_price_is_excluded_never_guessed():
    resp = compute_cost(
        CostRequest(
            tokens_in_before=1000, tokens_in_after=500,
            models=["unpriced-model"], calls_per_month=1,
        ),
        CATALOG,
    )
    row = resp.results[0]
    assert row.available is False
    assert row.saved_per_call is None
    assert row.cost_before_per_call is None
    assert "not verified" in (row.unavailable_reason or "")
    assert any("Excluded from cost totals" in w for w in resp.warnings)


def test_model_missing_from_catalog_is_reported_not_zeroed():
    resp = compute_cost(
        CostRequest(
            tokens_in_before=10, tokens_in_after=5,
            models=["never-heard-of-it"], calls_per_month=1,
        ),
        CATALOG,
    )
    assert resp.results[0].available is False
    assert resp.results[0].saved_per_call is None


def test_missing_output_tokens_reports_input_only_and_says_so():
    resp = compute_cost(
        CostRequest(
            tokens_in_before=1000, tokens_in_after=800,
            tokens_out=None, calls_per_month=1, models=["test-model"],
        ),
        CATALOG,
    )
    assert resp.results[0].input_only is True
    assert any("only input-side cost" in a for a in resp.assumptions)


def test_cache_blend_lowers_the_effective_input_price():
    plain = compute_cost(
        CostRequest(
            tokens_in_before=1_000_000, tokens_in_after=1_000_000,
            models=["test-model"], calls_per_month=1,
        ),
        CATALOG,
    )
    cached = compute_cost(
        CostRequest(
            tokens_in_before=1_000_000, tokens_in_after=1_000_000,
            models=["test-model"], calls_per_month=1, cache_read_fraction=0.8,
        ),
        CATALOG,
    )
    assert cached.results[0].effective_input_per_mtok < plain.results[0].effective_input_per_mtok
    assert any("compete" in a for a in cached.assumptions)


def test_unverified_cache_multipliers_are_ignored_with_a_warning():
    catalog = Catalog(
        models={
            "m": ModelPricing(
                id="m", provider="t", display_name="M",
                input_per_mtok=1.0, output_per_mtok=2.0,
                cache_read_multiplier=None, cache_write_multiplier=None,
                batch_discount=None, context_window=None,
                source_url="https://example.com", retrieved_at="2026-09-01", notes=None,
            )
        }
    )
    resp = compute_cost(
        CostRequest(
            tokens_in_before=1_000_000, tokens_in_after=1_000_000,
            models=["m"], calls_per_month=1, cache_read_fraction=0.9,
        ),
        catalog,
    )
    assert resp.results[0].effective_input_per_mtok == 1.0  # uncached, not guessed
    assert any("not verified" in w for w in resp.warnings)


def test_monthly_saving_scales_with_volume():
    resp = compute_cost(
        CostRequest(
            tokens_in_before=10_000, tokens_in_after=9_000,
            models=["test-model"], calls_per_month=30_000,
        ),
        CATALOG,
    )
    row = resp.results[0]
    assert row.saved_per_month == row.saved_per_call * 30_000
    assert any("30,000 calls per month" in a for a in resp.assumptions)


def test_shipped_catalog_has_a_source_and_date_for_every_priced_model():
    """Guards the no-fabricated-numbers policy on the real data file."""
    from app.services.pricing import load_catalog

    catalog = load_catalog()
    assert catalog.models, "the shipped pricing catalog should not be empty"
    for model in catalog.models.values():
        if model.input_per_mtok is not None:
            assert model.source_url, f"{model.id} has a price but no source_url"
            assert model.retrieved_at, f"{model.id} has a price but no retrieved_at"
