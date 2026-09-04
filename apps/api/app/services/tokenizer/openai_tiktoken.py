"""OpenAI tokenization via ``tiktoken``.

The only provider of the three that can be counted fully offline, exactly, and
with recoverable per-token character offsets. That last property is what makes
the visual token map possible — and it is why the token map is honest only for
this provider.

Deployment note: tiktoken downloads its BPE tables on first use. In a container
that means a cold, network-dependent first request. Pre-warm at build time by
running :func:`prewarm` (or set ``TIKTOKEN_CACHE_DIR`` and bake the files in).
"""

from __future__ import annotations

import logging
from bisect import bisect_left
from functools import lru_cache

import anyio

from app.schemas import CountSource
from app.services.tokenizer.base import CountResult

log = logging.getLogger("tokencut.tokenizer.openai")

DEFAULT_ENCODING = "o200k_base"

# Only used when tiktoken itself does not recognise the model id — which
# happens for every model released after the installed tiktoken version.
_PREFIX_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("gpt-3.5", "cl100k_base"),
    ("gpt-4-", "cl100k_base"),
    ("gpt-4o", "o200k_base"),
    ("gpt-", "o200k_base"),
    ("o1", "o200k_base"),
    ("o3", "o200k_base"),
    ("o4", "o200k_base"),
)

# Threshold above which encoding moves to a worker thread. tiktoken's Rust core
# is fast, but a 400KB paste on the event loop stalls every other request.
_THREAD_THRESHOLD_CHARS = 4_000


@lru_cache(maxsize=1)
def _tiktoken_version() -> str:
    try:
        from importlib.metadata import version

        return version("tiktoken")
    except Exception:  # pragma: no cover — metadata is optional
        return "unknown"


@lru_cache(maxsize=16)
def _get_encoding(name: str):  # noqa: ANN202 — tiktoken.Encoding
    import tiktoken

    return tiktoken.get_encoding(name)


@lru_cache(maxsize=256)
def resolve_encoding(model: str) -> tuple[str, bool]:
    """Return ``(encoding_name, was_exact_match)``.

    ``was_exact_match=False`` means tiktoken did not know this model id and we
    guessed from the name prefix. The guess is usually right, but the caller
    surfaces it as a note rather than presenting it silently.
    """
    import tiktoken

    try:
        return tiktoken.encoding_for_model(model).name, True
    except KeyError:
        pass

    lowered = model.lower()
    for prefix, encoding in _PREFIX_FALLBACKS:
        if lowered.startswith(prefix):
            return encoding, False
    return DEFAULT_ENCODING, False


def _char_start_bytes(text: str) -> list[int]:
    """UTF-8 byte offset at which each character starts (plus a final sentinel)."""
    starts = [0] * (len(text) + 1)
    pos = 0
    for i, ch in enumerate(text):
        starts[i] = pos
        pos += len(ch.encode("utf-8"))
    starts[len(text)] = pos
    return starts


def _byte_to_char(byte_off: int, starts: list[int], *, snap_up: bool) -> int:
    """Map a UTF-8 byte offset to a character index.

    A token boundary can fall *inside* a multi-byte character (an emoji split
    across two tokens, for instance). There is no character index for that, so
    snap outward: start offsets snap down, end offsets snap up. The result is
    that such a character is highlighted by both tokens rather than by neither.
    """
    idx = bisect_left(starts, byte_off)
    if idx < len(starts) and starts[idx] == byte_off:
        return idx
    return idx if snap_up else max(0, idx - 1)


def _encode_sync(
    text: str, encoding_name: str, want_offsets: bool
) -> tuple[int, list[tuple[int, int]] | None]:
    enc = _get_encoding(encoding_name)
    ids = enc.encode(text, disallowed_special=())

    if not want_offsets:
        return len(ids), None

    # ASCII fast path: byte offsets and character offsets coincide, so the
    # per-character encode below can be skipped entirely.
    ascii_only = text.isascii()
    starts = None if ascii_only else _char_start_bytes(text)

    offsets: list[tuple[int, int]] = []
    byte_pos = 0
    for tid in ids:
        length = len(enc.decode_single_token_bytes(tid))
        start_b, end_b = byte_pos, byte_pos + length
        byte_pos = end_b
        if ascii_only:
            offsets.append((start_b, end_b))
        else:
            offsets.append(
                (
                    _byte_to_char(start_b, starts, snap_up=False),
                    _byte_to_char(end_b, starts, snap_up=True),
                )
            )

    # Defensive: if the accumulated byte length disagrees with the source, the
    # offsets are untrustworthy. Return the count without them rather than
    # rendering a token map that is subtly misaligned.
    expected = len(text.encode("utf-8"))
    if byte_pos != expected:
        log.warning(
            "offset_reconstruction_mismatch",
            extra={"expected_bytes": expected, "got_bytes": byte_pos, "encoding": encoding_name},
        )
        return len(ids), None

    return len(ids), offsets


def count_sync(text: str, model: str) -> tuple[int, str]:
    """Synchronous token count. Returns ``(tokens, encoding_name)``.

    Used by the optimizer's attribution loop, which re-tokenizes once per rule
    and is itself already running in a worker thread. Going through the async
    tokenizer there would add an await per rule for no benefit.
    """
    encoding_name, _ = resolve_encoding(model)
    tokens, _ = _encode_sync(text, encoding_name, False)
    return tokens, encoding_name


class OpenAITokenizer:
    provider = "openai"

    @property
    def supports_offsets(self) -> bool:
        return True

    @property
    def is_local(self) -> bool:
        return True

    def available(self) -> tuple[bool, str | None]:
        try:
            import tiktoken  # noqa: F401
        except ImportError:
            return False, "tiktoken is not installed"
        return True, None

    async def count(
        self, text: str, model: str, *, want_offsets: bool = False
    ) -> CountResult:
        encoding_name, exact = resolve_encoding(model)

        if len(text) >= _THREAD_THRESHOLD_CHARS:
            tokens, offsets = await anyio.to_thread.run_sync(
                _encode_sync, text, encoding_name, want_offsets
            )
        else:
            tokens, offsets = _encode_sync(text, encoding_name, want_offsets)

        if not exact:
            # An inferred encoding is a guess, so the count must not claim to
            # be exact. tiktoken knows nothing about models released after the
            # installed version, and a new model can change encoding — GPT-4
            # (cl100k) to GPT-4o (o200k) did exactly that. Reporting an
            # inferred count as `exact_local` would be the product telling the
            # user a guess is a measurement.
            return CountResult(
                model=model,
                tokens=tokens,
                source=CountSource.ESTIMATED,
                encoding=f"{encoding_name} (inferred)",
                # Offsets from a guessed encoding would draw a token map that
                # is confidently wrong, which is worse than drawing none.
                offsets=None,
                includes_message_overhead=False,
                calibrated=False,
                note=(
                    f"tiktoken {_tiktoken_version()} does not recognise "
                    f"'{model}'. Counted with '{encoding_name}', inferred from "
                    f"the model name — treat as an estimate. Upgrading tiktoken "
                    f"usually resolves this."
                ),
            )

        return CountResult(
            model=model,
            tokens=tokens,
            source=CountSource.EXACT_LOCAL,
            encoding=encoding_name,
            offsets=offsets,
            # Raw text tokens. Chat framing overhead (per-message and
            # per-request constants, plus tool definitions) is NOT included —
            # billed request tokens are a larger, separate number.
            includes_message_overhead=False,
        )


def prewarm() -> None:
    """Load the common BPE tables so the first real request is not cold."""
    for name in ("o200k_base", "cl100k_base"):
        try:
            _get_encoding(name)
        except Exception as exc:  # pragma: no cover — best-effort warmup
            log.warning(
                "tiktoken_prewarm_failed",
                extra={"encoding": name, "exc_type": type(exc).__name__},
            )
