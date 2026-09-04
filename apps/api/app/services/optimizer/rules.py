"""Rule types.

Every rule is a pure function from (text, spans) to a set of edits or a set of
highlighted spans. Rules never rewrite the whole document — they emit
``Edit(start, end, replacement)`` ops against the text they were given, which
is what gives the UI a diff, per-rule toggling, and undo for free.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.schemas import Profile, RiskLevel, RuleCategory, SegmentKind
from app.services.optimizer.segmentation import Span


@dataclass(frozen=True, slots=True)
class Edit:
    start: int
    end: int
    replacement: str

    @property
    def delta(self) -> int:
        return len(self.replacement) - (self.end - self.start)


@dataclass(frozen=True, slots=True)
class RuleHit:
    """What a rule found.

    ``edits`` is empty for suggestion-only rules; ``spans`` drives highlighting
    for both kinds.
    """

    edits: tuple[Edit, ...] = ()
    spans: tuple[tuple[int, int], ...] = ()
    advice: str | None = None

    @property
    def occurrences(self) -> int:
        return max(len(self.edits), len(self.spans))


RuleFn = Callable[[str, list[Span]], RuleHit]

ALL_PROFILES = frozenset({Profile.SAFE, Profile.BALANCED, Profile.AGGRESSIVE})
BALANCED_UP = frozenset({Profile.BALANCED, Profile.AGGRESSIVE})
AGGRESSIVE_ONLY = frozenset({Profile.AGGRESSIVE})


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    name: str
    category: RuleCategory
    risk: RiskLevel
    applies_to: frozenset[SegmentKind]
    default_in: frozenset[Profile]
    fn: RuleFn
    semantic_risk_note: str = ""
    suggestion_only: bool = False
    invalidates_segmentation: bool = False
    order: int = 100
    advice: str | None = None

    def enabled(self, profile: Profile, overrides: dict[str, bool]) -> bool:
        if self.id in overrides:
            return overrides[self.id]
        return profile in self.default_in


def apply_edits(text: str, edits: list[Edit]) -> str:
    """Apply non-overlapping edits.

    Applied in **reverse offset order** so that each edit's coordinates remain
    valid against the not-yet-modified prefix. Doing this forwards, and
    tracking a running delta, is the classic way this breaks.
    """
    ordered = sorted(edits, key=lambda e: e.start, reverse=True)
    out = text
    prev_start = len(text) + 1
    for edit in ordered:
        if edit.end > prev_start:  # overlap slipped through; drop it rather than corrupt
            continue
        out = out[: edit.start] + edit.replacement + out[edit.end :]
        prev_start = edit.start
    return out


def resolve_overlaps(edits: list[Edit]) -> list[Edit]:
    """Keep the earliest edit in any overlapping group; drop the rest.

    Conflicts are dropped, never merged. A merged edit is one no rule authored
    and no test covers.
    """
    kept: list[Edit] = []
    for edit in sorted(edits, key=lambda e: (e.start, -e.end)):
        if kept and edit.start < kept[-1].end:
            continue
        kept.append(edit)
    return kept


PROSE_ONLY = frozenset({SegmentKind.PROSE})
PROSE_AND_TABLES = frozenset({SegmentKind.PROSE, SegmentKind.MARKDOWN_TABLE})


def iter_allowed(
    spans: list[Span], allowed: frozenset[SegmentKind]
) -> Iterator[Span]:
    """Yield the spans a rule is permitted to operate on."""
    for span in spans:
        if span.kind in allowed:
            yield span


def find_in_allowed(
    text: str,
    spans: list[Span],
    allowed: frozenset[SegmentKind],
    pattern: re.Pattern[str],
) -> Iterator[re.Match[str]]:
    """Match ``pattern`` over the WHOLE document, keeping only hits that lie
    entirely inside a permitted span.

    Matching against each span's substring in isolation looks equivalent and is
    not: regex anchors and lookarounds resolve against whatever string they are
    given. ``[ \\t]+\\Z`` in a trailing-whitespace rule matches the end of every
    *chunk*, so run per-span it deletes the space before every protected
    region — turning "endpoint at  https://..." into "endpoint athttps://...".
    Lookbehinds fail the same way: ``(?<=\\S)`` cannot see the character before
    a chunk's first byte.

    Matching the full document keeps ``^``, ``$``, ``\\A``, ``\\Z`` and every
    lookaround meaning what the rule author intended, and the span filter still
    guarantees no protected byte is touched.
    """
    permitted = [(span.start, span.end) for span in spans if span.kind in allowed]
    if not permitted:
        return

    for match in pattern.finditer(text):
        start, end = match.start(), match.end()
        for span_start, span_end in permitted:
            if start >= span_start and end <= span_end:
                yield match
                break
