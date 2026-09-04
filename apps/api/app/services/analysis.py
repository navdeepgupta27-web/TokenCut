"""Orchestration shared by /v1/tokenize and /v1/analyze."""

from __future__ import annotations

import asyncio
import logging
import re

import anyio

from app.config import settings
from app.errors import TextTooLarge
from app.schemas import (
    AppliedRule,
    CountSource,
    Profile,
    Segment,
    SegmentKind,
    SuggestedRule,
    TokenizeResponse,
    TokenResult,
)
from app.services.optimizer.pipeline import PipelineOutput
from app.services.optimizer.segmentation import segment as classify
from app.services.tokenizer.base import CountResult
from app.services.tokenizer.registry import get_registry

log = logging.getLogger("tokencut.analysis")

# Concurrency ceiling for segment attribution. Each unit is an upstream call
# against a shared, rate-limited provider quota.
_ATTRIBUTION_CONCURRENCY = 6

_RE_PARAGRAPH = re.compile(r"\n\s*\n")


def guard_size(text: str) -> None:
    size = len(text.encode("utf-8"))
    if size > settings.max_text_bytes:
        raise TextTooLarge(
            f"Text is {size:,} bytes; the limit is {settings.max_text_bytes:,}.",
            details={"bytes": size, "limit_bytes": settings.max_text_bytes},
        )


def _to_schema(result: CountResult) -> TokenResult:
    return TokenResult(
        model=result.model,
        tokens=result.tokens,
        source=result.source,
        encoding=result.encoding,
        offsets=result.offsets,
        includes_message_overhead=result.includes_message_overhead,
        estimate_error_p90=result.estimate_error_p90,
        calibrated=result.calibrated,
        note=result.note,
    )


def build_blocks(text: str) -> list[tuple[int, int, SegmentKind]]:
    """Split into paragraph-sized blocks for segment attribution.

    Capped at ``settings.max_segments_for_attribution`` by merging neighbours:
    each block costs one upstream call per API-backed model, so an uncapped
    split turns one paste into hundreds of calls.
    """
    if not text.strip():
        return []

    bounds: list[tuple[int, int]] = []
    cursor = 0
    for m in _RE_PARAGRAPH.finditer(text):
        if m.start() > cursor:
            bounds.append((cursor, m.start()))
        cursor = m.end()
    if cursor < len(text):
        bounds.append((cursor, len(text)))
    if not bounds:
        bounds = [(0, len(text))]

    cap = max(1, settings.max_segments_for_attribution)
    while len(bounds) > cap:
        merged: list[tuple[int, int]] = []
        for i in range(0, len(bounds), 2):
            pair = bounds[i : i + 2]
            merged.append((pair[0][0], pair[-1][1]))
        bounds = merged

    spans = classify(text)
    out: list[tuple[int, int, SegmentKind]] = []
    for start, end in bounds:
        best_kind, best_overlap = SegmentKind.PROSE, 0
        for span in spans:
            overlap = min(end, span.end) - max(start, span.start)
            if overlap > best_overlap:
                best_kind, best_overlap = span.kind, overlap
        out.append((start, end, best_kind))
    return out


async def _count_blocks(
    text: str, model: str, blocks: list[tuple[int, int, SegmentKind]]
) -> list[int | None]:
    registry = get_registry()
    sem = asyncio.Semaphore(_ATTRIBUTION_CONCURRENCY)

    async def one(start: int, end: int) -> int | None:
        async with sem:
            result = await registry.count(
                text[start:end], model, want_offsets=False, allow_estimate=True
            )
            return result.tokens

    return list(await asyncio.gather(*(one(s, e) for s, e, _ in blocks)))


async def tokenize_text(
    text: str,
    models: list[str],
    *,
    include_offsets: bool = False,
    include_segments: bool = False,
) -> TokenizeResponse:
    guard_size(text)
    registry = get_registry()

    results = await asyncio.gather(
        *(
            registry.count(
                text,
                model,
                want_offsets=include_offsets and registry.supports_offsets(model),
                allow_estimate=True,
            )
            for model in models
        )
    )

    warnings: list[str] = []
    if include_offsets:
        no_offsets = [m for m in models if not registry.supports_offsets(m)]
        if no_offsets:
            warnings.append(
                "Exact token boundaries are available for the OpenAI family "
                "only; "
                + ", ".join(no_offsets)
                + " return a total with no segmentation. Use the segment heat "
                "map for those models rather than a token-level map."
            )

    segments: list[Segment] | None = None
    if include_segments:
        blocks = build_blocks(text)
        segments = [Segment(start=s, end=e, kind=k) for s, e, k in blocks]

        for model, whole in zip(models, results, strict=True):
            if whole.tokens is None:
                continue
            try:
                counts = await _count_blocks(text, model, blocks)
            except Exception as exc:
                log.warning(
                    "segment_attribution_failed",
                    extra={"model": model, "exc_type": type(exc).__name__},
                )
                continue

            usable = [c for c in counts if c is not None]
            if not usable:
                continue

            # Per-segment counts do not sum to the whole-text count: message
            # framing overhead is charged once, and boundary tokens differ.
            # Normalise the shares to the exact total so the heat map adds up
            # to the number displayed in the metrics bar.
            raw_total = sum(usable)
            scale = (whole.tokens / raw_total) if raw_total else 0.0
            for seg, count in zip(segments, counts, strict=True):
                if count is not None:
                    seg.tokens[model] = round(count * scale)

        if segments:
            warnings.append(
                "Segment counts are normalised so they sum to the exact "
                "whole-text total; individual blocks are therefore approximate "
                "by a token or two."
            )

    return TokenizeResponse(
        results=[_to_schema(r) for r in results],
        segments=segments,
        chars=len(text),
        bytes=len(text.encode("utf-8")),
        warnings=warnings,
    )


async def run_optimizer(
    text: str,
    *,
    profile: Profile,
    overrides: dict[str, bool],
    measure_with: str,
) -> PipelineOutput:
    """Run the CPU-bound optimizer off the event loop."""
    from app.services.optimizer.pipeline import run_pipeline

    guard_size(text)
    return await anyio.to_thread.run_sync(
        lambda: run_pipeline(
            text, profile=profile, overrides=overrides, measure_with=measure_with
        )
    )


def optimizer_to_schema(
    output: PipelineOutput,
) -> tuple[list[AppliedRule], list[SuggestedRule]]:
    """Map pipeline dataclasses onto the public schema types."""
    from app.schemas import AppliedRule, EditOp, SuggestedRule

    applied = [
        AppliedRule(
            rule_id=a.rule.id,
            name=a.rule.name,
            category=a.rule.category,
            risk=a.rule.risk,
            occurrences=a.occurrences,
            tokens_saved=a.tokens_saved,
            edits=[EditOp(start=e.start, end=e.end, replacement=e.replacement) for e in a.edits],
        )
        for a in output.applied
    ]
    suggested = [
        SuggestedRule(
            rule_id=s.rule.id,
            name=s.rule.name,
            category=s.rule.category,
            risk=s.rule.risk,
            occurrences=s.occurrences,
            tokens_saved_if_applied=s.tokens_saved,
            semantic_risk_note=s.rule.semantic_risk_note,
            spans=list(s.spans),
            advice=s.advice,
        )
        for s in output.suggested
    ]
    return applied, suggested


MEASURE_SOURCE = CountSource.EXACT_LOCAL
