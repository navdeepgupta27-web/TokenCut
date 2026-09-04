"""Pass 0 — classify the text into typed, non-overlapping spans.

This runs before any rule and is the single most important safety mechanism in
the optimizer. Collapsing whitespace inside a Python block, or normalising a
quote inside a JSON string literal, is a data-destroying bug — and it is the
most common failure in naive "prompt compressor" tools.

Every rule declares which span kinds it may touch. The pipeline enforces it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.schemas import SegmentKind

# Bounds the cost of JSON discovery on adversarial input (a 400KB file of "{").
MAX_JSON_SCAN_ATTEMPTS = 400
MIN_JSON_BLOCK_CHARS = 24


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    kind: SegmentKind

    @property
    def length(self) -> int:
        return self.end - self.start


# Lower number wins when candidates overlap.
_PRIORITY: dict[SegmentKind, int] = {
    SegmentKind.FRONTMATTER: 1,
    SegmentKind.FENCED_CODE: 2,
    SegmentKind.JSON_BLOCK: 3,
    SegmentKind.XML_HTML_BLOCK: 4,
    SegmentKind.MARKDOWN_TABLE: 5,
    SegmentKind.INLINE_CODE: 6,
    SegmentKind.BASE64_BLOB: 7,
    SegmentKind.URL: 8,
    SegmentKind.EMAIL: 9,
    SegmentKind.TEMPLATE_VAR: 10,
    SegmentKind.PROSE: 99,
}

_RE_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_RE_FENCED = re.compile(r"(?:^|\n)(```|~~~)[^\n]*\n.*?(?:\n\1|\Z)", re.DOTALL)
_RE_INLINE_CODE = re.compile(r"`[^`\n]+`")
_RE_XML_BLOCK = re.compile(r"<([A-Za-z][\w:-]*)\b[^>]*>.*?</\1\s*>", re.DOTALL)
_RE_URL = re.compile(r"https?://[^\s<>\"'`)\]]+")
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_RE_TEMPLATE = re.compile(r"\{\{[^{}\n]{1,200}\}\}|\$\{[^{}\n]{1,200}\}|%\((\w+)\)[sdif]|%[sdif]\b")
_RE_BASE64 = re.compile(r"\b(?:data:[\w/+.-]+;base64,)?[A-Za-z0-9+/]{200,}={0,2}\b")
_RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RE_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _find_json_blocks(text: str) -> list[Span]:
    """Locate substrings that genuinely parse as JSON objects or arrays.

    Uses the real parser rather than a regex: brace matching cannot tell a JSON
    payload from a code block from a set-literal, and getting this wrong means
    reformatting something that is not JSON.
    """
    decoder = json.JSONDecoder()
    spans: list[Span] = []
    attempts = 0
    idx = 0
    length = len(text)

    while idx < length and attempts < MAX_JSON_SCAN_ATTEMPTS:
        ch = text[idx]
        if ch not in "{[":
            idx += 1
            continue

        attempts += 1
        try:
            value, end = decoder.raw_decode(text, idx)
        except ValueError:
            idx += 1
            continue

        if isinstance(value, (dict, list)) and (end - idx) >= MIN_JSON_BLOCK_CHARS:
            spans.append(Span(idx, end, SegmentKind.JSON_BLOCK))
            idx = end
        else:
            idx += 1

    return spans


def _find_markdown_tables(text: str) -> list[Span]:
    spans: list[Span] = []
    pos = 0
    lines = text.splitlines(keepends=True)
    run_start: int | None = None
    run_has_sep = False

    for line in lines:
        stripped = line.rstrip("\r\n")
        if _RE_TABLE_ROW.match(stripped):
            if run_start is None:
                run_start = pos
            if _RE_TABLE_SEP.match(stripped):
                run_has_sep = True
        else:
            if run_start is not None and run_has_sep:
                spans.append(Span(run_start, pos, SegmentKind.MARKDOWN_TABLE))
            run_start, run_has_sep = None, False
        pos += len(line)

    if run_start is not None and run_has_sep:
        spans.append(Span(run_start, pos, SegmentKind.MARKDOWN_TABLE))
    return spans


def _candidates(text: str) -> list[Span]:
    out: list[Span] = []

    if m := _RE_FRONTMATTER.match(text):
        out.append(Span(m.start(), m.end(), SegmentKind.FRONTMATTER))

    for m in _RE_FENCED.finditer(text):
        # Group 0 may include the leading newline; keep the fence itself only.
        start = m.start(1)
        out.append(Span(start, m.end(), SegmentKind.FENCED_CODE))

    out.extend(_find_json_blocks(text))

    for m in _RE_XML_BLOCK.finditer(text):
        out.append(Span(m.start(), m.end(), SegmentKind.XML_HTML_BLOCK))

    out.extend(_find_markdown_tables(text))

    for regex, kind in (
        (_RE_INLINE_CODE, SegmentKind.INLINE_CODE),
        (_RE_BASE64, SegmentKind.BASE64_BLOB),
        (_RE_URL, SegmentKind.URL),
        (_RE_EMAIL, SegmentKind.EMAIL),
        (_RE_TEMPLATE, SegmentKind.TEMPLATE_VAR),
    ):
        for m in regex.finditer(text):
            out.append(Span(m.start(), m.end(), kind))

    return out


def segment(text: str) -> list[Span]:
    """Return non-overlapping, sorted spans covering the whole of ``text``.

    Gaps between typed spans become ``PROSE``, which is the only kind most
    rules are allowed to modify.
    """
    if not text:
        return []

    candidates = _candidates(text)
    # Highest priority first, then longest, then leftmost — so an outer JSON
    # block beats an inline-code match that happens to sit inside it.
    candidates.sort(key=lambda s: (_PRIORITY[s.kind], -s.length, s.start))

    claimed: list[Span] = []
    for cand in candidates:
        if any(cand.start < c.end and c.start < cand.end for c in claimed):
            continue
        claimed.append(cand)

    claimed.sort(key=lambda s: s.start)

    result: list[Span] = []
    cursor = 0
    for span in claimed:
        if span.start > cursor:
            result.append(Span(cursor, span.start, SegmentKind.PROSE))
        result.append(span)
        cursor = span.end
    if cursor < len(text):
        result.append(Span(cursor, len(text), SegmentKind.PROSE))

    return result


def spans_of(spans: list[Span], kinds: frozenset[SegmentKind]) -> list[Span]:
    return [s for s in spans if s.kind in kinds]


def is_protected(spans: list[Span], start: int, end: int, allowed: frozenset[SegmentKind]) -> bool:
    """True when [start, end) touches any span whose kind is not in ``allowed``."""
    for s in spans:
        if s.start < end and start < s.end and s.kind not in allowed:
            return True
    return False
