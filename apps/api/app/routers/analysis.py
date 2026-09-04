"""Analysis endpoints: tokenize, optimize, cost, and the composite analyze."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.infra.ratelimit import enforce
from app.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CostRequest,
    CostResponse,
    OptimizeRequest,
    OptimizeResponse,
    TokenizeRequest,
    TokenizeResponse,
)
from app.services.analysis import (
    MEASURE_SOURCE,
    optimizer_to_schema,
    run_optimizer,
    tokenize_text,
)
from app.services.cost import compute_cost
from app.services.optimizer.pipeline import ALL_RULES

router = APIRouter(tags=["analysis"])


@router.post("/tokenize", response_model=TokenizeResponse)
async def tokenize(req: TokenizeRequest, request: Request) -> TokenizeResponse:
    # Segment attribution fans out into one upstream call per block per model,
    # so it costs more than a plain count against the shared quota.
    await enforce(request, cost=3 if req.include_segments else 1)
    return await tokenize_text(
        req.text,
        req.models,
        include_offsets=req.include_offsets,
        include_segments=req.include_segments,
    )


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest, request: Request) -> OptimizeResponse:
    # Purely local work — no provider quota is consumed.
    await enforce(request, cost=1)
    output = await run_optimizer(
        req.text, profile=req.profile, overrides=req.rules, measure_with=req.measure_with
    )
    applied, suggested = optimizer_to_schema(output)
    return OptimizeResponse(
        optimized_text=output.optimized_text,
        applied=applied,
        suggested=suggested,
        tokens_before=output.tokens_before,
        tokens_after=output.tokens_after,
        measure_model=output.measure_model,
        measure_source=MEASURE_SOURCE,
        warnings=output.warnings,
    )


@router.post("/cost", response_model=CostResponse)
async def cost(req: CostRequest, request: Request) -> CostResponse:
    await enforce(request, cost=1)
    return compute_cost(req)


@router.get("/rules")
async def rules() -> dict:
    """The rule catalog, so the frontend can render toggles without hardcoding.

    Adding a rule to the backend makes it appear in the UI with no frontend
    change.
    """
    return {
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "category": r.category.value,
                "risk": r.risk.value,
                "suggestion_only": r.suggestion_only,
                "default_in": sorted(p.value for p in r.default_in),
                "semantic_risk_note": r.semantic_risk_note,
            }
            for r in ALL_RULES
        ]
    }


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Tokenize + optimize + re-tokenize + cost, in one round trip.

    This is what the web app calls on every debounced edit. The three
    primitives stay public and separate because they are the developer API
    product; this composite exists so the UI makes one request, not four.
    """
    await enforce(request, cost=4 if req.include_segments else 2)

    before = await tokenize_text(
        req.text,
        req.models,
        include_offsets=req.include_offsets,
        include_segments=req.include_segments,
    )

    optimized = await run_optimizer(
        req.text, profile=req.profile, overrides=req.rules, measure_with=req.models[0]
    )
    applied, suggested = optimizer_to_schema(optimized)
    optimize_response = OptimizeResponse(
        optimized_text=optimized.optimized_text,
        applied=applied,
        suggested=suggested,
        tokens_before=optimized.tokens_before,
        tokens_after=optimized.tokens_after,
        measure_model=optimized.measure_model,
        measure_source=MEASURE_SOURCE,
        warnings=optimized.warnings,
    )

    # Re-tokenize the optimized text against the real models. The optimizer's
    # own before/after pair is measured with a local tokenizer for speed; these
    # are the exact per-model numbers the cost step must use.
    after = await tokenize_text(optimized.optimized_text, req.models)

    # Cost is computed per model with THAT model's own counts. Claude and
    # GPT-4o produce materially different token counts for the same text, so
    # pricing them all off one model's number would be wrong for every model
    # but one.
    before_by_model = {r.model: r.tokens for r in before.results}
    after_by_model = {r.model: r.tokens for r in after.results}

    cost_results = []
    cost_assumptions: list[str] = []
    cost_warnings: list[str] = []
    saved_by_model: dict[str, int] = {}

    for model in req.models:
        t_before = before_by_model.get(model)
        t_after = after_by_model.get(model)
        if t_before is None or t_after is None:
            continue
        partial = compute_cost(
            CostRequest(
                tokens_in_before=t_before,
                tokens_in_after=t_after,
                tokens_out=req.tokens_out,
                calls_per_month=req.calls_per_month,
                models=[model],
                cache_read_fraction=req.cache_read_fraction,
                cache_write_fraction=req.cache_write_fraction,
                batch_fraction=req.batch_fraction,
            )
        )
        cost_results.extend(partial.results)
        cost_assumptions.extend(partial.assumptions)
        cost_warnings.extend(partial.warnings)
        saved_by_model[model] = partial.tokens_saved_per_call

    from app.services.pricing import load_catalog

    # The scalar headline is the first requested model — the one the UI treats
    # as primary. Per-model savings are in `results`, which is what the
    # comparison table renders.
    headline = saved_by_model.get(req.models[0], next(iter(saved_by_model.values()), 0))

    cost_response = CostResponse(
        results=cost_results,
        tokens_saved_per_call=headline,
        assumptions=list(dict.fromkeys(cost_assumptions)),
        warnings=list(dict.fromkeys(cost_warnings)),
        pricing_oldest_retrieved_at=load_catalog().oldest_retrieved_at,
    )

    warnings = [*before.warnings, *optimize_response.warnings, *cost_response.warnings]
    return AnalyzeResponse(
        tokenize=before,
        optimize=optimize_response,
        tokenize_optimized=after,
        cost=cost_response,
        warnings=list(dict.fromkeys(warnings)),
    )
