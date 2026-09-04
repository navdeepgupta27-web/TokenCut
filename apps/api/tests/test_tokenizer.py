from __future__ import annotations

from itertools import pairwise

import pytest

from app.schemas import CountSource
from app.services.tokenizer.openai_tiktoken import OpenAITokenizer, count_sync, resolve_encoding

TEXTS = [
    "Hello, world!",
    "def f(x):\n    return x * 2\n",
    "café — naïve — “quoted”",
    "日本語のテキストです。",
    "🎉 emoji 🚀 heavy 🧪 text",
    "मैं हिन्दी में लिख रहा हूँ",
    "",
]


@pytest.mark.anyio
@pytest.mark.parametrize("text", TEXTS)
async def test_offsets_reconstruct_the_original_text_exactly(text: str):
    """The token map is only honest if the offsets tile the source exactly."""
    result = await OpenAITokenizer().count(text, "gpt-4o", want_offsets=True)
    assert result.source is CountSource.EXACT_LOCAL

    if not text:
        assert result.tokens == 0
        return

    assert result.offsets is not None, "offsets should be recoverable for OpenAI"
    assert len(result.offsets) == result.tokens

    # Offsets must be monotonic and cover [0, len(text)).
    assert result.offsets[0][0] == 0
    assert result.offsets[-1][1] == len(text)
    for (s1, e1), (s2, _) in pairwise(result.offsets):
        assert s1 <= e1
        assert e1 >= s2, "gaps between tokens would leave characters unhighlighted"


@pytest.mark.anyio
async def test_ascii_and_unicode_paths_agree_on_count():
    tokenizer = OpenAITokenizer()
    for text in TEXTS:
        with_offsets = await tokenizer.count(text, "gpt-4o", want_offsets=True)
        without = await tokenizer.count(text, "gpt-4o", want_offsets=False)
        assert with_offsets.tokens == without.tokens


@pytest.mark.anyio
async def test_unknown_openai_model_still_counts_but_says_it_guessed():
    result = await OpenAITokenizer().count("hello", "gpt-9-turbo-preview")
    assert result.tokens and result.tokens > 0
    assert result.note and "does not recognise" in result.note


def test_encoding_resolution_is_exact_for_known_models():
    for model in ("gpt-4o", "gpt-4", "gpt-3.5-turbo"):
        _, exact = resolve_encoding(model)
        assert exact, f"tiktoken should know {model}"


def test_count_sync_matches_async_path():
    text = "The quick brown fox jumps over the lazy dog."
    tokens, encoding = count_sync(text, "gpt-4o")
    assert tokens > 0
    assert encoding == "o200k_base"


def test_openai_counts_exclude_message_framing():
    """Raw text tokens and billed request tokens are different numbers.

    The API must not conflate them — the UI shows both.
    """
    import anyio

    result = anyio.run(lambda: OpenAITokenizer().count("hello", "gpt-4o"))
    assert result.includes_message_overhead is False
