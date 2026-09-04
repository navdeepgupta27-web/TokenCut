"""The optimizer pipeline.

Fully synchronous and CPU-bound — the router runs it in a worker thread.

Ordering:

    pass 0   segment into protected regions
    pass A   apply enabled rules one at a time, re-segmenting after each,
             re-tokenizing after each to attribute the saving to that rule
    pass B   run suggestion-only detectors against the ORIGINAL text, so the
             spans line up with what the user is looking at in the left pane
    pass C   final count, assemble response

Savings are always measured by **re-tokenizing**, never by counting characters.
The two diverge badly: normalising a curly quote saves one character and can
save three tokens.
"""

from __future__ import annotations

import logging

from app.schemas import CountSource, Profile, RuleCategory
from app.services.optimizer.rules import Edit, Rule, apply_edits, resolve_overlaps
from app.services.optimizer.segmentation import segment
from app.services.optimizer.tier0 import TIER0_RULES
from app.services.optimizer.tier1 import TIER1_RULES
from app.services.optimizer.tier2 import TIER2_RULES
from app.services.tokenizer.openai_tiktoken import count_sync
from app.services.tokenizer.registry import provider_for

log = logging.getLogger("tokencut.optimizer")

ALL_RULES: tuple[Rule, ...] = tuple(
    sorted(TIER0_RULES + TIER1_RULES + TIER2_RULES, key=lambda r: r.order)
)
RULES_BY_ID: dict[str, Rule] = {r.id: r for r in ALL_RULES}

# Above this size, per-rule re-tokenization and re-segmentation become the
# dominant cost. We degrade to a single measured before/after with savings
# attributed proportionally, and say so in a warning.
LARGE_TEXT_CHARS = 100_000

DEFAULT_MEASURE_MODEL = "gpt-4o"


class AppliedResult:
    __slots__ = ("rule", "occurrences", "tokens_saved", "edits")

    def __init__(
        self, rule: Rule, occurrences: int, tokens_saved: int, edits: list[Edit]
    ) -> None:
        self.rule = rule
        self.occurrences = occurrences
        self.tokens_saved = tokens_saved
        self.edits = edits


class SuggestedResult:
    __slots__ = ("rule", "occurrences", "tokens_saved", "spans", "advice")

    def __init__(
        self,
        rule: Rule,
        occurrences: int,
        tokens_saved: int,
        spans: tuple[tuple[int, int], ...],
        advice: str | None,
    ) -> None:
        self.rule = rule
        self.occurrences = occurrences
        self.tokens_saved = tokens_saved
        self.spans = spans
        self.advice = advice


class PipelineOutput:
    __slots__ = (
        "optimized_text", "applied", "suggested", "tokens_before",
        "tokens_after", "measure_model", "warnings",
    )

    def __init__(self, **kw: object) -> None:
        for key in self.__slots__:
            setattr(self, key, kw[key])


def resolve_measure_model(requested: str) -> tuple[str, list[str]]:
    """Force the measurement tokenizer to a local one.

    Attribution re-tokenizes once per rule. That is free offline and
    unaffordable against a keyed endpoint — a dozen upstream calls per
    keystroke would exhaust the shared quota in minutes.
    """
    warnings: list[str] = []
    if provider_for(requested) == "openai":
        return requested, warnings
    warnings.append(
        f"Savings were measured with '{DEFAULT_MEASURE_MODEL}' rather than "
        f"'{requested}': attribution requires a local tokenizer, and "
        f"{provider_for(requested) or 'that provider'} only counts via a keyed "
        f"API call. Exact before/after totals for '{requested}' are reported "
        f"separately by the tokenize step."
    )
    return DEFAULT_MEASURE_MODEL, warnings


def _should_apply(rule: Rule, profile: Profile, overrides: dict[str, bool]) -> bool:
    if rule.category is RuleCategory.ADVISORY:
        return False
    if overrides.get(rule.id) is True:
        return True   # explicit opt-in beats suggestion_only — this is the
                      # one-click-apply path from the UI
    if rule.suggestion_only:
        return False
    return rule.enabled(profile, overrides)


def run_pipeline(
    text: str,
    *,
    profile: Profile = Profile.BALANCED,
    overrides: dict[str, bool] | None = None,
    measure_with: str = DEFAULT_MEASURE_MODEL,
) -> PipelineOutput:
    overrides = overrides or {}
    measure_model, warnings = resolve_measure_model(measure_with)

    tokens_before, _ = count_sync(text, measure_model)
    if not text.strip():
        return PipelineOutput(
            optimized_text=text, applied=[], suggested=[],
            tokens_before=tokens_before, tokens_after=tokens_before,
            measure_model=measure_model, warnings=warnings,
        )

    large = len(text) > LARGE_TEXT_CHARS
    if large:
        warnings.append(
            f"Input is {len(text):,} characters. Per-rule savings are "
            f"apportioned by size rather than measured individually; the "
            f"before/after totals remain exact."
        )

    # ---- pass A: apply ---------------------------------------------------
    current = text
    running_tokens = tokens_before
    applied: list[AppliedResult] = []
    spans = segment(current)

    for rule in ALL_RULES:
        if not _should_apply(rule, profile, overrides):
            continue

        try:
            hit = rule.fn(current, spans)
        except Exception as exc:
            # A broken rule must not take down the request. Skip it, say so.
            log.warning(
                "rule_failed",
                extra={"rule_id": rule.id, "exc_type": type(exc).__name__},
            )
            warnings.append(f"Rule '{rule.id}' failed and was skipped.")
            continue

        if not hit.edits:
            continue

        edits = resolve_overlaps(list(hit.edits))
        if not edits:
            continue

        candidate = apply_edits(current, edits)
        if candidate == current:
            continue

        if large:
            saved = 0  # apportioned after the loop
        else:
            after, _ = count_sync(candidate, measure_model)
            saved = running_tokens - after
            # A rule can occasionally COST tokens. Removing "Please " and
            # re-capitalising is the classic case: " summarize" is one token
            # but "Summarize" splits into several. Roll back, and say so —
            # silently dropping a rule the user explicitly clicked is worse
            # than explaining why it did not help.
            if saved < 0:
                log.info(
                    "rule_increased_tokens_rolled_back",
                    extra={"rule_id": rule.id},
                )
                warnings.append(
                    f"'{rule.name}' was skipped: applying it here would ADD "
                    f"{-saved} token(s) rather than save any. Shorter text does "
                    f"not always mean fewer tokens."
                )
                continue
            running_tokens = after

        current = candidate
        spans = segment(current)
        applied.append(AppliedResult(rule, len(edits), saved, edits))

    tokens_after, _ = count_sync(current, measure_model)

    if large and applied:
        # Apportion the measured total by each rule's character reduction.
        # Approximate by construction — the warning above says so.
        total_saved = max(0, tokens_before - tokens_after)
        weights = [
            max(1, sum((e.end - e.start) - len(e.replacement) for e in a.edits))
            for a in applied
        ]
        weight_sum = sum(weights) or 1
        for result, weight in zip(applied, weights, strict=True):
            result.tokens_saved = round(total_saved * weight / weight_sum)

    # ---- pass B: suggest -------------------------------------------------
    # Detectors run against the ORIGINAL text so returned spans line up with
    # the editor contents the user is looking at.
    original_spans = segment(text)
    suggested: list[SuggestedResult] = []

    for rule in ALL_RULES:
        if _should_apply(rule, profile, overrides):
            continue
        if not (rule.suggestion_only or rule.category is RuleCategory.ADVISORY):
            continue

        try:
            hit = rule.fn(text, original_spans)
        except Exception as exc:
            log.warning(
                "detector_failed",
                extra={"rule_id": rule.id, "exc_type": type(exc).__name__},
            )
            continue

        if not hit.edits and not hit.spans:
            continue


        would_save = 0
        if hit.edits and not large:
            preview = apply_edits(text, resolve_overlaps(list(hit.edits)))
            preview_tokens, _ = count_sync(preview, measure_model)
            would_save = max(0, tokens_before - preview_tokens)

        spans_out = hit.spans or tuple((e.start, e.end) for e in hit.edits)
        suggested.append(
            SuggestedResult(rule, hit.occurrences, would_save, spans_out, hit.advice)
        )

    return PipelineOutput(
        optimized_text=current,
        applied=applied,
        suggested=suggested,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        measure_model=measure_model,
        warnings=warnings,
    )


MEASURE_SOURCE = CountSource.EXACT_LOCAL
