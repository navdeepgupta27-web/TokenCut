"""Tier 2 — prompt audit.

Suggestions only. ``default_in`` is empty for every rule here, so nothing in
this module is ever applied by a profile; a rule fires only when the user
explicitly opts into it, one click at a time, having seen the diff.

That is deliberate. Much of the folklore in this area — that removing
politeness, or adding an incantation, measurably changes output quality — is
weakly evidenced and model-dependent. What TokenCut can state truthfully is
"this costs you N tokens". What it must not state is "removing it is free".
Hence ``semantic_risk_note`` on every rule, rendered in the UI next to the
saving.

Note what is deliberately absent: "let's think step by step" and similar
chain-of-thought triggers are NOT flagged. There is real evidence they affect
output on some models, and telling users to delete them to save four tokens
would be bad advice dressed as optimization.
"""

from __future__ import annotations

import re

from app.schemas import RiskLevel, RuleCategory
from app.services.optimizer.rules import (
    PROSE_ONLY,
    Edit,
    Rule,
    RuleFn,
    RuleHit,
    iter_allowed,
)
from app.services.optimizer.segmentation import Span

NEVER_BY_DEFAULT: frozenset = frozenset()

_RE_POLITENESS = re.compile(
    r"\b(?:please\s+|kindly\s+"
    r"|thank you(?:\s+very much)?\s*[.,!]?\s*"
    r"|thanks(?:\s+in advance)?\s*[.,!]?\s*"
    r"|I(?:'d|\s+would)\s+like\s+you\s+to\s+"
    r"|I\s+want\s+you\s+to\s+(?!act\b)"
    r"|could\s+you\s+(?:please\s+)?"
    r"|would\s+you\s+(?:please\s+)?"
    r"|if\s+you\s+(?:could|would|don't\s+mind)\s*,?\s*)",
    re.IGNORECASE,
)

_RE_FILLER = re.compile(
    r"(?:\bAs\s+an?\s+AI(?:\s+language\s+model)?\s*,?\s*"
    r"|\bIn\s+this\s+task\s*,?\s*you\s+will\s+"
    r"|\bTake\s+a\s+deep\s+breath\s*[.,]?\s*"
    r"|\bYou\s+are\s+a\s+world[- ]class\s+"
    r"|\bIt\s+is\s+(?:very\s+)?important\s+that\s+you\s+"
    r"|\bRemember\s+(?:that|to)\s+)",
    re.IGNORECASE,
)

_RE_HEDGE = re.compile(
    r"\b(?:very|really|extremely|super|highly|incredibly)\s+"
    r"(?=\w+(?:ly|ful|ive|ous|ate)\b|carefully|thoroughly|precisely|accurately)",
    re.IGNORECASE,
)

_RE_ADVERB_CHAIN = re.compile(
    r"\b(\w+ly)(?:\s*,\s*|\s+and\s+)(\w+ly)(?:(?:\s*,\s*|\s+and\s+)(\w+ly))+",
    re.IGNORECASE,
)

_RE_ROLE = re.compile(r"\byou\s+are\s+an?\s+[^.\n]{3,80}[.\n]", re.IGNORECASE)

_RE_CONSTRAINT_LINE = re.compile(
    r"^\s*[-*\d.)\s]*((?:do\s+not|don't|never|avoid|must\s+not)\b[^\n]{3,200})$",
    re.IGNORECASE | re.MULTILINE,
)


def _phrase_rule(pattern: re.Pattern[str]) -> RuleFn:
    """Delete a matched phrase, repairing sentence capitalisation."""

    def fn(text: str, spans: list[Span]) -> RuleHit:
        edits: list[Edit] = []
        for span in iter_allowed(spans, PROSE_ONLY):
            chunk = text[span.start : span.end]
            for m in pattern.finditer(chunk):
                start = span.start + m.start()
                end = span.start + m.end()
                replacement = ""
                # If the phrase opened a sentence, re-capitalise what follows so
                # the applied diff reads as written English rather than a stub.
                before = text[:start].rstrip()
                at_sentence_start = not before or before[-1] in ".!?\n:"
                if at_sentence_start and end < len(text) and text[end].islower():
                    replacement = text[end].upper()
                    end += 1
                edits.append(Edit(start, end, replacement))
        return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))

    return fn


def _hedge_stacking(text: str, spans: list[Span]) -> RuleHit:
    edits: list[Edit] = []
    for span in iter_allowed(spans, PROSE_ONLY):
        chunk = text[span.start : span.end]
        for m in _RE_HEDGE.finditer(chunk):
            edits.append(Edit(span.start + m.start(), span.start + m.end(), ""))
        for m in _RE_ADVERB_CHAIN.finditer(chunk):
            # Keep the first adverb, drop the rest of the chain.
            edits.append(Edit(span.start + m.start(), span.start + m.end(), m.group(1)))
    return RuleHit(edits=tuple(edits), spans=tuple((e.start, e.end) for e in edits))


def _redundant_role(text: str, spans: list[Span]) -> RuleHit:
    matches = [
        (span.start + m.start(), span.start + m.end())
        for span in iter_allowed(spans, PROSE_ONLY)
        for m in _RE_ROLE.finditer(text[span.start : span.end])
    ]
    if len(matches) < 2:
        return RuleHit()
    # Keep the first declaration; every later one is the redundancy.
    later = matches[1:]
    return RuleHit(
        edits=tuple(Edit(s, e, "") for s, e in later),
        spans=tuple(later),
    )


def _duplicate_constraints(text: str, spans: list[Span]) -> RuleHit:
    seen: dict[str, tuple[int, int]] = {}
    dupes: list[tuple[int, int]] = []
    for m in _RE_CONSTRAINT_LINE.finditer(text):
        key = re.sub(r"\s+", " ", m.group(1).strip().lower()).rstrip(".")
        if key in seen:
            dupes.append((m.start(), m.end()))
        else:
            seen[key] = (m.start(), m.end())
    if not dupes:
        return RuleHit()
    return RuleHit(
        edits=tuple(Edit(s, e, "") for s, e in dupes),
        spans=tuple(dupes),
    )


TIER2_RULES: tuple[Rule, ...] = (
    Rule(
        id="flag_politeness",
        name="Politeness scaffolding",
        category=RuleCategory.PROMPT_AUDIT,
        risk=RiskLevel.MODERATE,
        applies_to=PROSE_ONLY,
        default_in=NEVER_BY_DEFAULT,
        fn=_phrase_rule(_RE_POLITENESS),
        suggestion_only=True,
        order=40,
        semantic_risk_note=(
            "Costs tokens and carries no instruction. It may still change how "
            "the model responds — tone and instruction-following are not fully "
            "separable. Review the diff before applying."
        ),
    ),
    Rule(
        id="flag_filler_openers",
        name="Filler openers and empty emphasis",
        category=RuleCategory.PROMPT_AUDIT,
        risk=RiskLevel.MODERATE,
        applies_to=PROSE_ONLY,
        default_in=NEVER_BY_DEFAULT,
        fn=_phrase_rule(_RE_FILLER),
        suggestion_only=True,
        order=41,
        semantic_risk_note=(
            "Phrases such as 'As an AI language model' or 'It is very important "
            "that you' add tokens without adding a constraint. Evidence that "
            "removing them changes output is weak but not zero — review first."
        ),
    ),
    Rule(
        id="flag_hedge_stacking",
        name="Stacked intensifiers and adverb chains",
        category=RuleCategory.PROMPT_AUDIT,
        risk=RiskLevel.MODERATE,
        applies_to=PROSE_ONLY,
        default_in=NEVER_BY_DEFAULT,
        fn=_hedge_stacking,
        suggestion_only=True,
        order=42,
        semantic_risk_note=(
            "'very carefully and thoroughly and precisely' costs several times "
            "what 'carefully' costs. Whether it buys anything is unmeasured."
        ),
    ),
    Rule(
        id="flag_redundant_role",
        name="Repeated role declarations",
        category=RuleCategory.PROMPT_AUDIT,
        risk=RiskLevel.MODERATE,
        applies_to=PROSE_ONLY,
        default_in=NEVER_BY_DEFAULT,
        fn=_redundant_role,
        suggestion_only=True,
        order=43,
        semantic_risk_note=(
            "The persona is declared more than once. Some prompt authors repeat "
            "it deliberately to reinforce it late in a long context — check "
            "whether yours is one of those before removing it."
        ),
    ),
    Rule(
        id="flag_duplicate_constraints",
        name="Duplicated constraints",
        category=RuleCategory.PROMPT_AUDIT,
        risk=RiskLevel.MODERATE,
        applies_to=PROSE_ONLY,
        default_in=NEVER_BY_DEFAULT,
        fn=_duplicate_constraints,
        suggestion_only=True,
        order=44,
        semantic_risk_note=(
            "The same instruction appears more than once verbatim. Repetition "
            "late in a long prompt is sometimes intentional reinforcement."
        ),
    ),
)
