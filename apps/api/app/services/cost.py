"""Cost engine.

The equations from docs/02-core-logic.md section 3, and the honesty rules that
go with them.

The one that matters most:

    ΔC = ((T_in_raw − T_in_optimized) / 1e6) · P_input

**The output term cancels.** Compressing a prompt reduces input cost only — it
does not shorten the response. Every calculator that shows "total cost before
vs after" with an unchanged output estimate is taking credit for nothing. This
module reports the input-side saving as the headline and records the reason in
``assumptions``, which the UI renders verbatim.
"""

from __future__ import annotations

from app.schemas import CostRequest, CostResponse, ModelCost
from app.services.pricing import Catalog, ModelPricing, load_catalog

_PER_MTOK = 1_000_000.0


def _effective_input_price(
    pricing: ModelPricing, req: CostRequest, input_tokens: int
) -> tuple[float | None, list[str]]:
    """Blend the base input price with cache-read/write and batch rates.

    ``input_tokens`` selects the length band for models whose rate depends on
    prompt size (Gemini Pro doubles above 200k).
    """
    notes: list[str] = []
    base = pricing.input_price_for(input_tokens)
    if base is None:
        return None, notes

    f_read = req.cache_read_fraction
    f_write = req.cache_write_fraction
    if f_read + f_write > 1.0:
        notes.append(
            f"cache_read_fraction + cache_write_fraction exceeds 1.0 for "
            f"{pricing.id}; clamped."
        )
        scale = 1.0 / (f_read + f_write)
        f_read, f_write = f_read * scale, f_write * scale

    price = base
    if f_read or f_write:
        if pricing.cache_read_multiplier is None or pricing.cache_write_multiplier is None:
            notes.append(
                f"Cache multipliers for {pricing.id} are not verified in the "
                f"pricing catalog, so caching was ignored in this calculation. "
                f"The figure shown is the uncached cost."
            )
        else:
            price = (
                f_read * base * pricing.cache_read_multiplier
                + f_write * base * pricing.cache_write_multiplier
                + (1.0 - f_read - f_write) * base
            )

    if req.batch_fraction:
        if pricing.batch_discount is None:
            notes.append(
                f"A batch discount for {pricing.id} is not verified in the "
                f"pricing catalog, so batching was ignored."
            )
        else:
            price = price * (1.0 - req.batch_fraction * pricing.batch_discount)

    return price, notes


def compute_cost(req: CostRequest, catalog: Catalog | None = None) -> CostResponse:
    catalog = catalog or load_catalog()

    tokens_saved = max(0, req.tokens_in_before - req.tokens_in_after)
    input_only = req.tokens_out is None
    tokens_out = req.tokens_out or 0

    assumptions: list[str] = []
    warnings: list[str] = []

    if input_only:
        assumptions.append(
            "Output tokens were not supplied, so only input-side cost is shown. "
            "Output length cannot be derived from a prompt."
        )
    else:
        assumptions.append(f"Output assumed to be {tokens_out:,} tokens per call.")

    assumptions.append(
        "Optimization reduces input tokens only. The response length — and "
        "therefore the output cost — is unchanged, so the saving below is "
        "entirely input-side."
    )
    assumptions.append(f"Volume assumed to be {req.calls_per_month:,} calls per month.")

    if req.cache_read_fraction or req.cache_write_fraction:
        assumptions.append(
            f"Prompt caching assumed at {req.cache_read_fraction:.0%} reads / "
            f"{req.cache_write_fraction:.0%} writes of input."
        )
        assumptions.append(
            "Caching and compression compete: tokens served from cache are "
            "already cheap, and editing a cached prefix invalidates it. "
            "Compress the volatile tail, cache the stable head."
        )
    if req.batch_fraction:
        assumptions.append(f"{req.batch_fraction:.0%} of calls assumed to use a batch endpoint.")

    results: list[ModelCost] = []
    for model_id in req.models:
        pricing = catalog.get(model_id)

        if pricing is None:
            results.append(
                ModelCost(
                    model=model_id,
                    available=False,
                    unavailable_reason="not present in the pricing catalog",
                )
            )
            continue

        if not pricing.verified:
            results.append(
                ModelCost(
                    model=model_id,
                    available=False,
                    unavailable_reason=(
                        "price not verified — the catalog has no sourced figure "
                        "for this model"
                    ),
                    pricing_source_url=pricing.source_url,
                    pricing_retrieved_at=pricing.retrieved_at,
                )
            )
            continue

        # Length-tiered models are priced at their own band on each side of
        # the optimization. Using one rate for both would hide the entire
        # benefit of dropping under a threshold.
        eff_before, notes_before = _effective_input_price(
            pricing, req, req.tokens_in_before
        )
        eff_after, notes_after = _effective_input_price(
            pricing, req, req.tokens_in_after
        )
        warnings.extend(notes_before)
        for note in notes_after:
            if note not in warnings:
                warnings.append(note)

        assert eff_before is not None and eff_after is not None  # pricing.verified
        p_out_before = pricing.output_price_for(req.tokens_in_before) or 0.0
        p_out_after = pricing.output_price_for(req.tokens_in_after) or 0.0

        before = (req.tokens_in_before / _PER_MTOK) * eff_before + (
            (tokens_out / _PER_MTOK) * p_out_before if not input_only else 0.0
        )
        after = (req.tokens_in_after / _PER_MTOK) * eff_after + (
            (tokens_out / _PER_MTOK) * p_out_after if not input_only else 0.0
        )
        crossed = pricing.crosses_tier(req.tokens_in_before, req.tokens_in_after)

        if crossed:
            # The per-token rate changed, so the saving is genuinely the
            # difference of the two costs and cannot be expressed as
            # tokens x one rate.
            saved_per_call = max(0.0, before - after)
        else:
            # Flat rate: compute the saving directly from the token delta.
            # `before - after` would be algebraically identical but not
            # bit-identical — the output term cancels in exact arithmetic and
            # leaves ~1e-16 of float residue otherwise, which would make the
            # headline saving move when the user edits the output estimate.
            # It never should.
            saved_per_call = (tokens_saved / _PER_MTOK) * eff_after
        if crossed:
            assumptions.append(
                f"Optimization moved this prompt into a cheaper pricing band for "
                f"{pricing.display_name} (the rate itself dropped from "
                f"${eff_before:.2f} to ${eff_after:.2f} per million input tokens), "
                f"so the saving here is larger than the token reduction alone."
            )

        results.append(
            ModelCost(
                model=model_id,
                available=True,
                input_per_mtok=pricing.input_per_mtok,
                output_per_mtok=pricing.output_per_mtok,
                effective_input_per_mtok=eff_after,
                cost_before_per_call=before,
                cost_after_per_call=after,
                saved_per_call=saved_per_call,
                saved_per_month=saved_per_call * req.calls_per_month,
                input_only=input_only,
                pricing_retrieved_at=pricing.retrieved_at,
                pricing_source_url=pricing.source_url,
                pricing_note=pricing.pricing_note,
                crossed_pricing_tier=crossed,
            )
        )

    if stale := catalog.stale_models():
        warnings.append(
            f"{len(stale)} model price(s) are older than the freshness policy "
            f"and may be out of date: {', '.join(sorted(stale)[:5])}"
            + ("…" if len(stale) > 5 else "")
        )

    unverified = [r.model for r in results if not r.available]
    if unverified:
        warnings.append(
            "Excluded from cost totals because no verified price is on file: "
            + ", ".join(unverified)
        )

    return CostResponse(
        results=results,
        tokens_saved_per_call=tokens_saved,
        assumptions=assumptions,
        warnings=warnings,
        pricing_oldest_retrieved_at=catalog.oldest_retrieved_at,
    )
