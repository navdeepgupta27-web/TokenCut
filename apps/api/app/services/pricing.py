"""Pricing catalog loader.

Prices live in ``data/pricing/catalog.json`` and nowhere else. No module in
this codebase may contain a hardcoded price.

Two invariants this module enforces:

* A ``null`` price is **unavailable**, not zero and not a guess. It never
  participates in a total; the UI renders "price not verified".
* Every entry carries ``source_url`` and ``retrieved_at``. Entries older than
  ``settings.pricing_max_age_days`` are still served but flagged stale, and CI
  fails the build on them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache

from app.config import settings

log = logging.getLogger("tokencut.pricing")

# Rows whose id starts with this are documentation placeholders for prices that
# have not been verified yet. They are never served.
PLACEHOLDER_PREFIX = "__"


@dataclass(frozen=True, slots=True)
class PriceTier:
    """One band of length-dependent pricing.

    ``max_input_tokens is None`` marks the open-ended top band.
    """

    max_input_tokens: int | None
    price: float


@dataclass(frozen=True, slots=True)
class ModelPricing:
    id: str
    provider: str
    display_name: str
    input_per_mtok: float | None
    output_per_mtok: float | None
    cache_read_multiplier: float | None
    cache_write_multiplier: float | None
    batch_discount: float | None
    context_window: int | None
    source_url: str | None
    retrieved_at: str | None
    notes: str | None
    pricing_note: str | None = None
    # Length-dependent pricing (Gemini Pro doubles above 200k input tokens).
    # Empty means flat pricing.
    input_tiers: tuple[PriceTier, ...] = ()
    output_tiers: tuple[PriceTier, ...] = ()

    @property
    def verified(self) -> bool:
        return (
            self.input_per_mtok is not None
            and self.output_per_mtok is not None
            and self.retrieved_at is not None
        )

    @property
    def is_tiered(self) -> bool:
        return bool(self.input_tiers or self.output_tiers)

    @staticmethod
    def _select(
        tiers: tuple[PriceTier, ...], input_tokens: int, fallback: float | None
    ) -> float | None:
        """Pick the band for ``input_tokens``.

        Both input and output prices are selected by the *input* token count —
        that is how the providers state it, and it is the whole reason this
        exists: quoting the low band for a 300k-token prompt would understate
        the cost by 2x.
        """
        if not tiers:
            return fallback
        for tier in tiers:
            if tier.max_input_tokens is None or input_tokens <= tier.max_input_tokens:
                return tier.price
        # Only reachable if the catalog omits the open-ended top band.
        return tiers[-1].price

    def input_price_for(self, input_tokens: int) -> float | None:
        return self._select(self.input_tiers, input_tokens, self.input_per_mtok)

    def output_price_for(self, input_tokens: int) -> float | None:
        return self._select(self.output_tiers, input_tokens, self.output_per_mtok)

    def crosses_tier(self, before_tokens: int, after_tokens: int) -> bool:
        """True when optimization moved the prompt into a cheaper band.

        Worth surfacing: dropping under a threshold is worth far more than the
        token saving alone, and it is the one case where compression changes
        the *rate* rather than just the quantity.
        """
        if not self.input_tiers:
            return False
        return self.input_price_for(after_tokens) != self.input_price_for(before_tokens)

    @property
    def retrieved_date(self) -> date | None:
        if not self.retrieved_at:
            return None
        try:
            return datetime.strptime(self.retrieved_at, "%Y-%m-%d").date()
        except ValueError:
            log.warning("pricing_bad_date", extra={"model": self.id, "value": self.retrieved_at})
            return None

    def age_days(self, today: date | None = None) -> int | None:
        retrieved = self.retrieved_date
        if retrieved is None:
            return None
        return ((today or date.today()) - retrieved).days


@dataclass(frozen=True, slots=True)
class Catalog:
    models: dict[str, ModelPricing]

    def get(self, model_id: str) -> ModelPricing | None:
        return self.models.get(model_id)

    @property
    def oldest_retrieved_at(self) -> str | None:
        dates = [m.retrieved_at for m in self.models.values() if m.retrieved_at]
        return min(dates) if dates else None

    def stale_models(self, today: date | None = None) -> list[str]:
        today = today or date.today()
        out = []
        for model in self.models.values():
            retrieved = model.retrieved_date
            if retrieved is None:
                continue
            if (today - retrieved).days > settings.pricing_max_age_days:
                out.append(model.id)
        return out

    @property
    def is_stale(self) -> bool:
        return bool(self.stale_models())


def _coerce_tiers(value: object, model_id: str, field: str) -> tuple[PriceTier, ...]:
    """Parse a tier list, refusing anything malformed.

    A half-parsed tier list is worse than none: it would silently price part of
    the range wrong. On any problem we drop the tiers entirely and fall back to
    the flat price, which is at least a number someone sourced.
    """
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        log.error("pricing_bad_tiers", extra={"model": model_id, "field": field})
        return ()

    tiers: list[PriceTier] = []
    for raw_tier in value:
        if not isinstance(raw_tier, dict):
            log.error("pricing_bad_tier_entry", extra={"model": model_id, "field": field})
            return ()
        price = _coerce_float(raw_tier.get("price"), model_id, field)
        if price is None:
            return ()
        cap = raw_tier.get("max_input_tokens")
        if cap is not None and not isinstance(cap, int):
            log.error("pricing_bad_tier_cap", extra={"model": model_id, "field": field})
            return ()
        tiers.append(PriceTier(max_input_tokens=cap, price=price))

    # The last band must be open-ended, or prompts above the highest cap have
    # no defined price.
    if tiers[-1].max_input_tokens is not None:
        log.error(
            "pricing_tiers_missing_open_band",
            extra={"model": model_id, "field": field},
        )
        return ()
    return tuple(tiers)


def _coerce_float(value: object, model_id: str, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.error("pricing_bad_number", extra={"model": model_id, "field": field})
        return None


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    path = settings.pricing_catalog_path
    try:
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        log.error("pricing_catalog_missing", extra={"path": str(path)})
        return Catalog(models={})
    except json.JSONDecodeError as exc:
        log.error("pricing_catalog_invalid", extra={"path": str(path), "error": str(exc)})
        return Catalog(models={})

    models: dict[str, ModelPricing] = {}
    for entry in raw.get("models", []):
        model_id = entry.get("id", "")
        if not model_id or model_id.startswith(PLACEHOLDER_PREFIX):
            continue
        models[model_id] = ModelPricing(
            input_tiers=_coerce_tiers(entry.get("input_tiers"), model_id, "input_tiers"),
            output_tiers=_coerce_tiers(entry.get("output_tiers"), model_id, "output_tiers"),
            pricing_note=entry.get("pricing_note"),
            id=model_id,
            provider=entry.get("provider", "unknown"),
            display_name=entry.get("display_name", model_id),
            input_per_mtok=_coerce_float(entry.get("input_per_mtok"), model_id, "input"),
            output_per_mtok=_coerce_float(entry.get("output_per_mtok"), model_id, "output"),
            cache_read_multiplier=_coerce_float(
                entry.get("cache_read_multiplier"), model_id, "cache_read"
            ),
            cache_write_multiplier=_coerce_float(
                entry.get("cache_write_multiplier"), model_id, "cache_write"
            ),
            batch_discount=_coerce_float(entry.get("batch_discount"), model_id, "batch"),
            context_window=entry.get("context_window"),
            source_url=entry.get("source_url"),
            retrieved_at=entry.get("retrieved_at"),
            notes=entry.get("notes"),
        )

    stale = Catalog(models=models).stale_models()
    if stale:
        log.warning("pricing_stale", extra={"models": stale, "count": len(stale)})

    return Catalog(models=models)
