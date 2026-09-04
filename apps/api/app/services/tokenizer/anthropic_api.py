"""Anthropic tokenization via ``POST /v1/messages/count_tokens``.

Three facts drive this adapter:

1. **There is no public offline tokenizer for current Claude models.** The
   counting endpoint is the only accurate source.
2. **It is free of token charges but is a keyed, rate-limited network call.**
   Hence the cache in front of it and the estimator behind it.
3. **Counts are model-specific.** The tokenizer changed within the Claude 4
   line — Opus 4.7+ produces roughly 1x-1.35x the tokens of earlier models on
   the same text — so model ids must never share a cache key.

And one anti-pattern worth stating explicitly, because it is the obvious
shortcut: do **not** approximate Claude with tiktoken. It undercounts Claude by
roughly 15-20% on typical prose and by considerably more on code and
non-English text.

The endpoint returns a total and nothing else — no segmentation, no offsets.
``supports_offsets`` is therefore False and must stay False.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.schemas import CountSource
from app.services.tokenizer.base import CountResult

log = logging.getLogger("tokencut.tokenizer.anthropic")

_client = None
_client_failed = False


def _get_client():  # noqa: ANN202 — anthropic.AsyncAnthropic
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        import anthropic

        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.upstream_timeout_seconds,
            max_retries=1,  # the caller degrades to an estimate; don't stall the request
        )
    except Exception as exc:
        _client_failed = True
        log.warning("anthropic_client_init_failed", extra={"exc_type": type(exc).__name__})
    return _client


class AnthropicTokenizer:
    provider = "anthropic"

    @property
    def supports_offsets(self) -> bool:
        # count_tokens returns input_tokens only. Synthesising boundaries from
        # another provider's tokenizer and labelling them "Claude" would be a
        # lie the audience for this tool would catch.
        return False

    @property
    def is_local(self) -> bool:
        return False

    def available(self) -> tuple[bool, str | None]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "the anthropic package is not installed"
        if not settings.anthropic_api_key:
            return False, "ANTHROPIC_API_KEY is not configured"
        return True, None

    async def count(
        self, text: str, model: str, *, want_offsets: bool = False
    ) -> CountResult:
        ok, reason = self.available()
        if not ok:
            return CountResult.unavailable(model, reason or "unavailable")

        client = _get_client()
        if client is None:
            return CountResult.unavailable(model, "anthropic client could not be created")

        import anthropic

        try:
            resp = await client.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.NotFoundError:
            return CountResult.unavailable(model, f"Anthropic does not recognise model '{model}'")
        except anthropic.AuthenticationError:
            return CountResult.unavailable(model, "Anthropic rejected the configured API key")
        except anthropic.RateLimitError:
            log.warning("anthropic_rate_limited", extra={"model": model})
            return CountResult.unavailable(
                model, "Anthropic rate limit reached; showing an estimate"
            )
        except anthropic.APIStatusError as exc:
            log.warning(
                "anthropic_status_error",
                extra={"model": model, "status": exc.status_code},
            )
            return CountResult.unavailable(model, f"Anthropic returned {exc.status_code}")
        except anthropic.APIConnectionError:
            log.warning("anthropic_connection_error", extra={"model": model})
            return CountResult.unavailable(model, "could not reach Anthropic")

        return CountResult(
            model=model,
            tokens=resp.input_tokens,
            source=CountSource.EXACT_API,
            encoding="anthropic_count_tokens_api",
            offsets=None,
            # The endpoint counts a full request, so the figure includes the
            # message framing Anthropic will actually bill for. This is the
            # number a user wants for cost — but it is NOT comparable
            # like-for-like with tiktoken's raw-text count.
            includes_message_overhead=True,
        )
