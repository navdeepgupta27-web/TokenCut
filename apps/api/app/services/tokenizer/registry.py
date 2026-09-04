"""Model registry and counting orchestration.

Owns three things:

1. The price-free catalog of known models (id -> provider, tokenizer, context).
2. Provider resolution for unknown ids, so a model released after this file was
   written still counts instead of 404-ing.
3. The counting path itself: cache -> exact -> degrade to estimate.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.infra.cache import count_key, get_cache
from app.schemas import CountSource
from app.services.tokenizer.anthropic_api import AnthropicTokenizer
from app.services.tokenizer.base import CountResult, ModelSpec, Tokenizer
from app.services.tokenizer.estimator import Estimator
from app.services.tokenizer.gemini_api import GeminiTokenizer
from app.services.tokenizer.openai_tiktoken import OpenAITokenizer

log = logging.getLogger("tokencut.registry")


# ---------------------------------------------------------------------------
# Known models
#
# Curated, price-free, and deliberately conservative: an entry appears here only
# if the id is known-good. Unknown ids still work via _infer_provider below —
# they just don't get a display name or a context window.
#
# Adding a model is a one-line edit to this table plus a row in
# data/pricing/catalog.json. Nothing else in the codebase knows model names.
# ---------------------------------------------------------------------------

KNOWN_MODELS: tuple[ModelSpec, ...] = (
    # --- OpenAI: offline, exact, offsets ---------------------------------
    # Every id here was checked against the installed tiktoken (0.14.0) with
    # `encoding_for_model`; all resolve exactly, so counts are EXACT_LOCAL.
    # gpt-6-astra is deliberately absent: tiktoken does not know it, so it
    # would count via an inferred encoding and report as ESTIMATED. It is
    # still usable by typing the id — see _infer_provider.
    ModelSpec("gpt-5.6-sol", "openai", "GPT-5.6 Sol", "tiktoken/o200k_base"),
    ModelSpec("gpt-5.6-terra", "openai", "GPT-5.6 Terra", "tiktoken/o200k_base"),
    ModelSpec("gpt-5.6-luna", "openai", "GPT-5.6 Luna", "tiktoken/o200k_base"),
    ModelSpec("gpt-5.4", "openai", "GPT-5.4", "tiktoken/o200k_base", 272_000),
    ModelSpec("gpt-5", "openai", "GPT-5", "tiktoken/o200k_base"),
    ModelSpec("gpt-5-mini", "openai", "GPT-5 mini", "tiktoken/o200k_base"),
    ModelSpec("gpt-4o", "openai", "GPT-4o", "tiktoken/o200k_base"),
    ModelSpec("gpt-4o-mini", "openai", "GPT-4o mini", "tiktoken/o200k_base"),
    ModelSpec("gpt-3.5-turbo", "openai", "GPT-3.5 Turbo", "tiktoken/cl100k_base"),

    # --- Anthropic: keyed count_tokens, no offsets ------------------------
    # Context windows and tokenizer generations from the official pricing page
    # (retrieved 2026-09-04).
    ModelSpec("claude-opus-5", "anthropic", "Claude Opus 5",
              "anthropic_count_tokens_api", 1_000_000),
    ModelSpec("claude-sonnet-5", "anthropic", "Claude Sonnet 5",
              "anthropic_count_tokens_api", 1_000_000),
    ModelSpec("claude-fable-5", "anthropic", "Claude Fable 5",
              "anthropic_count_tokens_api", 1_000_000),
    ModelSpec("claude-haiku-4-5", "anthropic", "Claude Haiku 4.5",
              "anthropic_count_tokens_api", 200_000,
              note="Pre-4.7 tokenizer generation."),
    ModelSpec("claude-sonnet-4-6", "anthropic", "Claude Sonnet 4.6",
              "anthropic_count_tokens_api", 1_000_000,
              note="Pre-4.7 tokenizer generation. Anthropic states the 4.7+ "
                   "tokenizer produces ~30% more tokens for the same text, so "
                   "these counts are not comparable with Opus 5 / Sonnet 5."),
    ModelSpec("claude-opus-4-6", "anthropic", "Claude Opus 4.6",
              "anthropic_count_tokens_api", 1_000_000,
              note="Pre-4.7 tokenizer generation."),

    # --- Google: keyed count_tokens, no offsets ---------------------------
    # Ids taken from the official Gemini pricing page (retrieved 2026-09-04).
    # An id the API does not recognise surfaces as a clean "Google does not
    # recognise this model" rather than a wrong number.
    ModelSpec("gemini-2.5-pro", "google", "Gemini 2.5 Pro",
              "google_count_tokens_api",
              note="Input price doubles above 200k input tokens."),
    ModelSpec("gemini-3.1-pro-preview", "google", "Gemini 3.1 Pro Preview",
              "google_count_tokens_api",
              note="Preview pricing; doubles above 200k input tokens."),
    ModelSpec("gemini-3.5-flash", "google", "Gemini 3.5 Flash",
              "google_count_tokens_api"),
    ModelSpec("gemini-2.5-flash", "google", "Gemini 2.5 Flash",
              "google_count_tokens_api"),
    ModelSpec("gemini-2.5-flash-lite", "google", "Gemini 2.5 Flash-Lite",
              "google_count_tokens_api"),
)

_BY_ID: dict[str, ModelSpec] = {m.id: m for m in KNOWN_MODELS}
for _m in KNOWN_MODELS:
    for _alias in _m.aliases:
        _BY_ID[_alias] = _m

_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gemini", "google"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("text-embedding", "openai"),
)


def _infer_provider(model: str) -> str | None:
    lowered = model.lower()
    for prefix, provider in _PROVIDER_PREFIXES:
        if lowered.startswith(prefix):
            return provider
    return None


def get_spec(model: str) -> ModelSpec | None:
    return _BY_ID.get(model)


def provider_for(model: str) -> str | None:
    spec = _BY_ID.get(model)
    return spec.provider if spec else _infer_provider(model)


class TokenizerRegistry:
    def __init__(self) -> None:
        self._tokenizers: dict[str, Tokenizer] = {
            "openai": OpenAITokenizer(),
            "anthropic": AnthropicTokenizer(),
            "google": GeminiTokenizer(),
        }
        self._estimator = Estimator()

    # -- introspection ----------------------------------------------------

    def tokenizer_for(self, model: str) -> Tokenizer | None:
        provider = provider_for(model)
        return self._tokenizers.get(provider) if provider else None

    def provider_status(self) -> dict[str, dict[str, object]]:
        status: dict[str, dict[str, object]] = {}
        for provider, tk in self._tokenizers.items():
            ok, reason = tk.available()
            status[provider] = {
                "available": ok,
                "reason": reason,
                "local": tk.is_local,
                "offsets": tk.supports_offsets,
            }
        return status

    def supports_offsets(self, model: str) -> bool:
        tk = self.tokenizer_for(model)
        return bool(tk and tk.supports_offsets)

    # -- counting ---------------------------------------------------------

    async def count(
        self,
        text: str,
        model: str,
        *,
        want_offsets: bool = False,
        allow_estimate: bool = True,
        use_cache: bool = True,
    ) -> CountResult:
        """Count ``text`` for ``model``: cache, then exact, then estimate.

        Never raises for provider problems. A degraded answer that says it is
        degraded beats a 502 — the user still has their OpenAI numbers, their
        optimized text, and their input-side savings.
        """
        tokenizer = self.tokenizer_for(model)
        if tokenizer is None:
            return CountResult.unavailable(
                model, f"unknown model '{model}' — no provider could be inferred"
            )

        provider = tokenizer.provider

        # Cache only remote counts. Local tokenization is cheaper than a Redis
        # round trip, and caching it would also throw away the offsets.
        cacheable = use_cache and not tokenizer.is_local and not want_offsets
        key = count_key(text, model) if cacheable else None

        if key is not None:
            cached = await get_cache().get_int(key)
            if cached is not None:
                return CountResult(
                    model=model,
                    tokens=cached,
                    source=CountSource.CACHED,
                    encoding=tokenizer.__class__.__name__,
                    includes_message_overhead=True,
                )

        available, reason = tokenizer.available()
        if available:
            result = await tokenizer.count(text, model, want_offsets=want_offsets)
            if result.tokens is not None:
                if key is not None:
                    await get_cache().set_int(key, result.tokens, settings.cache_ttl_seconds)
                return result
            reason = result.note or "provider unavailable"

        if not allow_estimate:
            return CountResult.unavailable(model, reason or "unavailable")

        estimate = await self._estimator.estimate(text, model, provider)
        if estimate.tokens is None:
            # No exact count and no sourced ratio. Say so plainly.
            return CountResult.unavailable(
                model, f"{reason or 'unavailable'}; no calibrated estimate for this provider"
            )
        return estimate


_registry: TokenizerRegistry | None = None


def get_registry() -> TokenizerRegistry:
    global _registry
    if _registry is None:
        _registry = TokenizerRegistry()
    return _registry
