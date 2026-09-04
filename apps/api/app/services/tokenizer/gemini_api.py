"""Gemini tokenization via the google-genai ``count_tokens`` call.

Same shape as the Anthropic adapter: keyed, free of token charges, no offsets.

TWO THINGS TO VERIFY BEFORE LAUNCH (both flagged in docs/02-core-logic.md):

1. The exact async call surface and response field. This adapter reads
   ``total_tokens`` defensively via getattr and degrades rather than crashing
   if the SDK shape differs from what is assumed here.
2. Whether a **local** SentencePiece tokenizer is usable via the Vertex AI
   tokenization extra. If it is, Gemini moves into the offline column, this
   whole keyed dependency disappears, and offsets may become available. Worth
   half an hour before committing to the API path.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.schemas import CountSource
from app.services.tokenizer.base import CountResult

log = logging.getLogger("tokencut.tokenizer.gemini")

_client = None
_client_failed = False


def _get_client():  # noqa: ANN202 — google.genai.Client
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        from google import genai

        _client = genai.Client(api_key=settings.google_api_key)
    except Exception as exc:
        _client_failed = True
        log.warning("gemini_client_init_failed", extra={"exc_type": type(exc).__name__})
    return _client


class GeminiTokenizer:
    provider = "google"

    @property
    def supports_offsets(self) -> bool:
        return False

    @property
    def is_local(self) -> bool:
        return False

    def available(self) -> tuple[bool, str | None]:
        try:
            from google import genai  # noqa: F401
        except ImportError:
            return False, "the google-genai package is not installed"
        if not settings.google_api_key:
            return False, "GOOGLE_API_KEY is not configured"
        return True, None

    async def count(
        self, text: str, model: str, *, want_offsets: bool = False
    ) -> CountResult:
        ok, reason = self.available()
        if not ok:
            return CountResult.unavailable(model, reason or "unavailable")

        client = _get_client()
        if client is None:
            return CountResult.unavailable(model, "gemini client could not be created")

        try:
            resp = await client.aio.models.count_tokens(model=model, contents=text)
        except Exception as exc:
            # google-genai does not expose a stable typed exception hierarchy
            # comparable to the Anthropic SDK's, so this is a deliberate broad
            # catch that degrades to an estimate rather than failing the whole
            # request. Narrow it once the SDK surface is verified.
            log.warning(
                "gemini_count_failed",
                extra={"model": model, "exc_type": type(exc).__name__},
            )
            return CountResult.unavailable(model, f"Gemini count failed ({type(exc).__name__})")

        total = getattr(resp, "total_tokens", None)
        if total is None:
            log.warning("gemini_unexpected_response_shape", extra={"model": model})
            return CountResult.unavailable(model, "unexpected response shape from google-genai")

        return CountResult(
            model=model,
            tokens=int(total),
            source=CountSource.EXACT_API,
            encoding="google_count_tokens_api",
            offsets=None,
            includes_message_overhead=True,
        )
