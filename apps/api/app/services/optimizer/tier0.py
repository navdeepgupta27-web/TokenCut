"""Tier 0 — lossless normalization.

Individually small. Collectively meaningful on anything pasted out of Word,
Notion, Slack, or a Google Doc — which is most real prompts. All of it is
semantically identity-preserving on prose, which is why it is the only tier
applied without asking.

Every rule here is restricted to PROSE spans (a few also to markdown tables),
so code, JSON, URLs, and template variables are never touched.
"""

from __future__ import annotations

import re

from app.schemas import RiskLevel, RuleCategory, SegmentKind
from app.services.optimizer.rules import (
    ALL_PROFILES,
    PROSE_AND_TABLES,
    PROSE_ONLY,
    Edit,
    Rule,
    RuleFn,
    RuleHit,
    find_in_allowed,
)
from app.services.optimizer.segmentation import Span

# Runs of 2+ spaces/tabs that are NOT at the start of a line. Leading
# indentation carries meaning in markdown (nested lists, indented code) and is
# deliberately left alone.
_RE_INNER_RUNS = re.compile(r"(?<=\S)[ \t]{2,}")
_RE_TRAILING_WS = re.compile(r"[ \t]+(?=\r?\n)|[ \t]+\Z")
_RE_BLANK_RUN = re.compile(r"(?:\r?\n){3,}")
_RE_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
_RE_CRLF = re.compile(r"\r\n")

# Characters that cost more tokens than their ASCII equivalent while carrying
# no additional meaning in a prompt.
_UNICODE_MAP: dict[str, str] = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-",
    "…": "...",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "«": '"', "»": '"',
    "′": "'", "″": '"',
}
_RE_UNICODE = re.compile("|".join(re.escape(c) for c in _UNICODE_MAP))


def _regex_rule(
    pattern: re.Pattern[str], replacement: str, allowed: frozenset[SegmentKind]
) -> RuleFn:
    """Build a rule that replaces ``pattern`` inside allowed spans.

    Uses ``find_in_allowed``, which matches the whole document and filters by
    span, so anchors and lookarounds behave correctly at span boundaries. See
    that function's docstring for why per-span matching is wrong.
    """

    def fn(text: str, spans: list[Span]) -> RuleHit:
        edits = [
            Edit(m.start(), m.end(), replacement)
            for m in find_in_allowed(text, spans, allowed, pattern)
            if text[m.start() : m.end()] != replacement
        ]
        return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))

    return fn


def _collapse_blank_lines(text: str, spans: list[Span]) -> RuleHit:
    edits = [
        Edit(m.start(), m.end(), "\n\n")
        for m in find_in_allowed(text, spans, PROSE_ONLY, _RE_BLANK_RUN)
    ]
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


def _normalize_unicode(text: str, spans: list[Span]) -> RuleHit:
    edits = [
        Edit(m.start(), m.end(), _UNICODE_MAP[m.group(0)])
        for m in find_in_allowed(text, spans, PROSE_AND_TABLES, _RE_UNICODE)
    ]
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


def _normalize_line_endings(text: str, spans: list[Span]) -> RuleHit:
    # The only Tier 0 rule applied to the WHOLE document. CRLF -> LF is safe
    # everywhere including code, and the stray \r is frequently its own token.
    edits = [Edit(m.start(), m.end(), "\n") for m in _RE_CRLF.finditer(text)]
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


def _strip_zero_width(text: str, spans: list[Span]) -> RuleHit:
    edits = [Edit(m.start(), m.end(), "") for m in _RE_ZERO_WIDTH.finditer(text)]
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


TIER0_RULES: tuple[Rule, ...] = (
    Rule(
        id="normalize_line_endings",
        name="Normalise CRLF line endings",
        category=RuleCategory.LOSSLESS,
        risk=RiskLevel.SAFE,
        applies_to=frozenset(SegmentKind),  # whole document
        default_in=ALL_PROFILES,
        fn=_normalize_line_endings,
        order=10,
    ),
    Rule(
        id="strip_zero_width",
        name="Remove zero-width and BOM characters",
        category=RuleCategory.LOSSLESS,
        risk=RiskLevel.SAFE,
        applies_to=frozenset(SegmentKind),
        default_in=ALL_PROFILES,
        fn=_strip_zero_width,
        order=11,
    ),
    Rule(
        id="normalize_unicode",
        name="Convert smart quotes, dashes and non-breaking spaces to ASCII",
        category=RuleCategory.LOSSLESS,
        risk=RiskLevel.SAFE,
        applies_to=PROSE_AND_TABLES,
        default_in=ALL_PROFILES,
        fn=_normalize_unicode,
        order=12,
    ),
    Rule(
        id="trim_trailing_whitespace",
        name="Strip trailing whitespace",
        category=RuleCategory.LOSSLESS,
        risk=RiskLevel.SAFE,
        applies_to=PROSE_AND_TABLES,
        default_in=ALL_PROFILES,
        fn=_regex_rule(_RE_TRAILING_WS, "", PROSE_AND_TABLES),
        order=13,
    ),
    Rule(
        id="collapse_spaces",
        name="Collapse repeated spaces and tabs",
        category=RuleCategory.LOSSLESS,
        risk=RiskLevel.SAFE,
        applies_to=PROSE_ONLY,
        default_in=ALL_PROFILES,
        fn=_regex_rule(_RE_INNER_RUNS, " ", PROSE_ONLY),
        order=14,
    ),
    Rule(
        id="collapse_blank_lines",
        name="Collapse runs of blank lines",
        category=RuleCategory.LOSSLESS,
        risk=RiskLevel.SAFE,
        applies_to=PROSE_ONLY,
        default_in=ALL_PROFILES,
        fn=_collapse_blank_lines,
        order=15,
    ),
)
