"""Tier 1 — structural re-encoding, plus the advisory rules.

Where the large, defensible wins are. ``json_to_markdown_table`` is typically
the single biggest lever in the whole engine: an array of uniform objects
repeats every key on every row, and a table states each key once.

The advisory rules at the bottom emit no edits at all. They exist because the
honest answer to "how do I cut this bill" is sometimes "don't compress this —
cache it", and a tool that never says so is selling something.
"""

from __future__ import annotations

import json
import re

from app.schemas import RiskLevel, RuleCategory, SegmentKind
from app.services.optimizer.rules import (
    AGGRESSIVE_ONLY,
    ALL_PROFILES,
    BALANCED_UP,
    Edit,
    Rule,
    RuleHit,
    iter_allowed,
)
from app.services.optimizer.segmentation import Span

JSON_ONLY = frozenset({SegmentKind.JSON_BLOCK})
XML_ONLY = frozenset({SegmentKind.XML_HTML_BLOCK})
BASE64_ONLY = frozenset({SegmentKind.BASE64_BLOB})

MIN_TABLE_ROWS = 2
_SCALARS = (str, int, float, bool, type(None))

# Presentation markup only. Deliberately excludes arbitrary tag names, because
# XML-style tags (<instructions>, <context>, <example>) are a *recommended*
# prompting technique — stripping them would damage the prompt.
_HTML_TAGS = frozenset(
    "div span p br hr b i u em strong ul ol li table thead tbody tr td th "
    "h1 h2 h3 h4 h5 h6 a img section article header footer nav main "
    "font small big center blockquote pre".split()
)
_RE_ANY_TAG = re.compile(r"</?([A-Za-z][\w:-]*)\b[^>]*>")

# Rough lower bound on a cacheable prefix across providers. Below this there is
# nothing to advise about.
CACHE_ADVICE_MIN_CHARS = 4_000
REPEAT_BLOCK_MIN_CHARS = 200


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate keys")
    return dict(pairs)


def _parse_strict(raw: str) -> object:
    """Parse JSON, refusing input where a round trip would lose information."""
    return json.loads(raw, object_pairs_hook=_no_duplicate_keys)


def _compact_json(text: str, spans: list[Span]) -> RuleHit:
    edits: list[Edit] = []
    for span in iter_allowed(spans, JSON_ONLY):
        raw = text[span.start : span.end]
        try:
            value = _parse_strict(raw)
            compact = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            # Round-trip guard: the transform is only allowed if it is provably
            # information-preserving.
            if _parse_strict(compact) != value:
                continue
        except (ValueError, RecursionError):
            continue
        if len(compact) < len(raw):
            edits.append(Edit(span.start, span.end, compact))
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


def _cell(value: object) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _json_to_markdown_table(text: str, spans: list[Span]) -> RuleHit:
    edits: list[Edit] = []
    for span in iter_allowed(spans, JSON_ONLY):
        raw = text[span.start : span.end]
        try:
            value = _parse_strict(raw)
        except (ValueError, RecursionError):
            continue

        if not isinstance(value, list) or len(value) < MIN_TABLE_ROWS:
            continue
        if not all(isinstance(row, dict) for row in value):
            continue

        keys = list(value[0].keys())
        key_set = set(keys)
        if not keys:
            continue
        # Ragged or nested data must not be flattened into a table — that
        # would silently drop fields.
        if any(set(row.keys()) != key_set for row in value):
            continue
        if any(not isinstance(v, _SCALARS) for row in value for v in row.values()):
            continue

        lines = [
            "| " + " | ".join(keys) + " |",
            "| " + " | ".join("---" for _ in keys) + " |",
        ]
        lines.extend("| " + " | ".join(_cell(row[k]) for k in keys) + " |" for row in value)
        table = "\n".join(lines)

        if len(table) < len(raw):
            edits.append(Edit(span.start, span.end, table))

    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


def _strip_html_tags(text: str, spans: list[Span]) -> RuleHit:
    edits: list[Edit] = []
    for span in iter_allowed(spans, XML_ONLY):
        chunk = text[span.start : span.end]
        tags = {m.group(1).lower() for m in _RE_ANY_TAG.finditer(chunk)}
        # All-or-nothing: if the block contains any non-presentational tag it is
        # probably a deliberate prompt structure, so leave the whole thing alone.
        if not tags or not tags.issubset(_HTML_TAGS):
            continue
        for m in _RE_ANY_TAG.finditer(chunk):
            edits.append(Edit(span.start + m.start(), span.start + m.end(), ""))
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


# --------------------------------------------------------------------------
# Advisory rules — no edits, only recommendations
# --------------------------------------------------------------------------


def _flag_base64(text: str, spans: list[Span]) -> RuleHit:
    hits = tuple((s.start, s.end) for s in iter_allowed(spans, BASE64_ONLY))
    if not hits:
        return RuleHit()
    return RuleHit(
        spans=hits,
        advice=(
            "Base64 data tokenizes extremely badly — roughly one token per two "
            "or three characters, with no semantic value to the model. There is "
            "no compression that fixes this. Send the file through the "
            "provider's file/vision API, or reference it by URL, instead of "
            "pasting it into the prompt."
        ),
    )


def _detect_repeated_blocks(text: str, spans: list[Span]) -> RuleHit:
    """Find paragraph-sized blocks that appear more than once."""
    seen: dict[str, list[int]] = {}
    pos = 0
    for para in re.split(r"(\n\s*\n)", text):
        if para.strip() and len(para) >= REPEAT_BLOCK_MIN_CHARS:
            seen.setdefault(para.strip(), []).append(pos)
        pos += len(para)

    hits: list[tuple[int, int]] = []
    wasted = 0
    for body, positions in seen.items():
        if len(positions) > 1:
            hits.extend((p, p + len(body)) for p in positions[1:])
            wasted += len(body) * (len(positions) - 1)

    if not hits:
        return RuleHit()
    return RuleHit(
        spans=tuple(hits),
        advice=(
            f"{len(hits)} duplicated block(s) found, roughly {wasted:,} characters "
            "of repetition. Before deleting them, check whether they are a "
            "repeated system prompt: if so, prompt caching will save far more "
            "than removing them, and costs nothing in output quality."
        ),
    )


def _advise_prompt_caching(text: str, spans: list[Span]) -> RuleHit:
    if len(text) < CACHE_ADVICE_MIN_CHARS:
        return RuleHit()
    return RuleHit(
        spans=((0, min(len(text), CACHE_ADVICE_MIN_CHARS)),),
        advice=(
            "This prompt is large enough to be worth caching. If any of it is a "
            "stable prefix you resend on every call, caching it will almost "
            "certainly save more than compressing it — cached input is billed at "
            "a fraction of the base rate. Note the interaction: editing a cached "
            "prefix invalidates the cache, so compressing a stable system prompt "
            "can cost more on the next call than it saves. Compress the volatile "
            "tail; cache the stable head."
        ),
    )


TIER1_RULES: tuple[Rule, ...] = (
    Rule(
        id="json_to_markdown_table",
        name="Convert uniform JSON arrays to Markdown tables",
        category=RuleCategory.STRUCTURAL,
        risk=RiskLevel.MODERATE,
        applies_to=JSON_ONLY,
        default_in=BALANCED_UP,
        fn=_json_to_markdown_table,
        invalidates_segmentation=True,
        order=20,
        semantic_risk_note=(
            "Usually the largest single saving available. It does change the "
            "representation the model sees, and cell values lose their JSON "
            "types (3 and \"3\" both become 3). Review if your prompt depends "
            "on strict typing or on the input being valid JSON."
        ),
    ),
    Rule(
        id="compact_json",
        name="Remove formatting whitespace from JSON",
        category=RuleCategory.STRUCTURAL,
        risk=RiskLevel.SAFE,
        applies_to=JSON_ONLY,
        default_in=ALL_PROFILES,
        fn=_compact_json,
        invalidates_segmentation=True,
        order=21,
        semantic_risk_note=(
            "Byte-for-byte information preserving — verified by re-parsing and "
            "comparing before the edit is emitted."
        ),
    ),
    Rule(
        id="strip_html_tags",
        name="Strip presentational HTML markup",
        category=RuleCategory.STRUCTURAL,
        risk=RiskLevel.AGGRESSIVE,
        applies_to=XML_ONLY,
        default_in=AGGRESSIVE_ONLY,
        fn=_strip_html_tags,
        invalidates_segmentation=True,
        order=22,
        semantic_risk_note=(
            "Only fires on blocks made purely of presentational HTML tags. "
            "XML-style tags such as <instructions> or <context> are a "
            "deliberate prompting technique and are never touched."
        ),
    ),
    Rule(
        id="flag_base64",
        name="Flag base64 blobs",
        category=RuleCategory.ADVISORY,
        risk=RiskLevel.SAFE,
        applies_to=BASE64_ONLY,
        default_in=ALL_PROFILES,
        fn=_flag_base64,
        suggestion_only=True,
        order=30,
        semantic_risk_note="Advisory only — no change is made to your text.",
    ),
    Rule(
        id="detect_repeated_blocks",
        name="Detect duplicated blocks",
        category=RuleCategory.ADVISORY,
        risk=RiskLevel.SAFE,
        applies_to=frozenset(SegmentKind),
        default_in=ALL_PROFILES,
        fn=_detect_repeated_blocks,
        suggestion_only=True,
        order=31,
        semantic_risk_note="Advisory only — no change is made to your text.",
    ),
    Rule(
        id="advise_prompt_caching",
        name="Consider prompt caching",
        category=RuleCategory.ADVISORY,
        risk=RiskLevel.SAFE,
        applies_to=frozenset(SegmentKind),
        default_in=ALL_PROFILES,
        fn=_advise_prompt_caching,
        suggestion_only=True,
        order=32,
        semantic_risk_note="Advisory only — no change is made to your text.",
    ),
)
