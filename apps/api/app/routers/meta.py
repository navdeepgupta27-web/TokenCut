"""Health and model catalog."""

from __future__ import annotations

from fastapi import APIRouter

from app.infra.cache import get_cache
from app.schemas import HealthResponse, ModelInfo, ModelsResponse
from app.services.pricing import load_catalog
from app.services.tokenizer.registry import KNOWN_MODELS, get_registry

router = APIRouter(tags=["meta"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness plus provider status.

    Also serves as the frontend's warm-up ping: the web app fires this on page
    load so a sleeping free-tier instance is already awake by the time the user
    stops typing.
    """
    registry = get_registry()
    providers = registry.provider_status()
    degraded = not any(p["available"] for p in providers.values())
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=VERSION,
        providers=providers,
        cache=get_cache().name,
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """The catalog the frontend builds its model picker and cost math from.

    Counting availability and pricing availability are reported separately: a
    model can be perfectly countable while its price is unverified, and the UI
    needs to show the token count and suppress the dollar figure.
    """
    registry = get_registry()
    catalog = load_catalog()
    provider_status = registry.provider_status()

    models: list[ModelInfo] = []
    for spec in KNOWN_MODELS:
        tokenizer = registry.tokenizer_for(spec.id)
        status = provider_status.get(spec.provider, {})
        provider_ok = bool(status.get("available"))
        is_local = bool(tokenizer and tokenizer.is_local)

        if provider_ok:
            counting = "offline" if is_local else "api"
        elif is_local:
            counting = "unavailable"
        else:
            counting = "estimate_only"

        pricing = catalog.get(spec.id)
        models.append(
            ModelInfo(
                id=spec.id,
                provider=spec.provider,
                display_name=spec.display_name,
                context_window=spec.context_window,
                tokenizer=spec.tokenizer,
                supports_offsets=bool(tokenizer and tokenizer.supports_offsets),
                counting=counting,
                available=provider_ok or counting == "estimate_only",
                unavailable_reason=None if provider_ok else status.get("reason"),
                input_per_mtok=pricing.input_per_mtok if pricing else None,
                output_per_mtok=pricing.output_per_mtok if pricing else None,
                pricing_source_url=pricing.source_url if pricing else None,
                pricing_retrieved_at=pricing.retrieved_at if pricing else None,
                pricing_verified=bool(pricing and pricing.verified),
            )
        )

    warnings: list[str] = []
    if stale := catalog.stale_models():
        warnings.append(
            f"{len(stale)} model price(s) exceed the freshness policy: "
            + ", ".join(sorted(stale))
        )
    if unverified := [m.id for m in models if not m.pricing_verified]:
        warnings.append(
            "No verified price on file (token counts still work; cost is "
            "suppressed): " + ", ".join(unverified)
        )

    return ModelsResponse(
        models=models,
        pricing_oldest_retrieved_at=catalog.oldest_retrieved_at,
        pricing_stale=catalog.is_stale,
        warnings=warnings,
    )
