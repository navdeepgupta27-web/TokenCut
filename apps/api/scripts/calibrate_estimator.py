"""Measure the tiktoken -> provider token ratio and write it back.

The shipped ratios in ``data/calibration/estimator.json`` are *derived* from
published statements, not measured. This script replaces them with real fitted
values and real error bands.

    export ANTHROPIC_API_KEY=...
    python -m scripts.calibrate_estimator --model claude-opus-5
    python -m scripts.calibrate_estimator --model claude-sonnet-4-6 --write

Without ``--write`` it prints the result and changes nothing.

Why this exists as a script rather than a test: it costs a network round trip
per corpus document against a rate-limited endpoint. It is a deliberate,
occasional act, not something CI should do on every push.

Note on cost: Anthropic's count_tokens endpoint does not charge for the tokens
it counts, so a calibration run is free of token charges. It is still
rate-limited, hence the concurrency cap and the retry pause.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python scripts/calibrate_estimator.py` as well as `-m`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.tokenizer.estimator import family_for
from app.services.tokenizer.openai_tiktoken import count_sync
from app.services.tokenizer.registry import get_registry, provider_for

CONCURRENCY = 4
BASE_MODEL = "gpt-4o"


@dataclass(slots=True)
class Sample:
    """One corpus document and its two counts."""

    label: str
    content_class: str
    text: str
    base_tokens: int = 0
    true_tokens: int = 0

    @property
    def ratio(self) -> float:
        return self.true_tokens / self.base_tokens if self.base_tokens else 0.0


def build_corpus() -> list[Sample]:
    """A deliberately mixed corpus.

    The ratio is NOT constant across content types — it is worst on code and
    non-Latin scripts — so a corpus of English prose alone would produce a
    confidently wrong number. Replace this with your own real traffic for a
    calibration that actually reflects your workload.
    """
    prose = (
        "The quarterly report noted that operational efficiency improved by "
        "fourteen percent year over year, driven primarily by automation of "
        "the reconciliation pipeline and a reduction in manual review. "
    )
    code = (
        "def reconcile(ledger: dict[str, Decimal], txns: list[Txn]) -> Report:\n"
        "    total = sum(t.amount for t in txns if not t.voided)\n"
        "    if total != ledger['expected']:\n"
        "        raise ReconciliationError(total, ledger['expected'])\n"
        "    return Report(total=total, count=len(txns))\n"
    )
    payload = json.dumps(
        [{"id": i, "name": f"user{i}", "plan": "enterprise", "mrr": 1200 + i} for i in range(12)],
        indent=2,
    )
    markdown = (
        "## Findings\n\n- **Revenue** grew 28%\n- Headcount flat\n\n"
        "| metric | q3 | q4 |\n| --- | --- | --- |\n| arr | 1.2 | 1.5 |\n"
    )
    cjk = "四半期報告書によると、業務効率は前年比で十四パーセント改善しました。" * 3
    indic = "तिमाही रिपोर्ट में कहा गया है कि परिचालन कà¥‍षमता में सुधार हुआ है।" * 3

    samples: list[Sample] = []
    for multiplier in (1, 4, 16):
        samples.extend(
            [
                Sample(f"prose x{multiplier}", "prose", prose * multiplier),
                Sample(f"code x{multiplier}", "code", code * multiplier),
                Sample(f"json x{multiplier}", "json", payload * multiplier),
                Sample(f"markdown x{multiplier}", "markdown", markdown * multiplier),
                Sample(f"cjk x{multiplier}", "cjk", cjk * multiplier),
                Sample(f"indic x{multiplier}", "indic", indic * multiplier),
            ]
        )
    return samples


async def measure(model: str, samples: list[Sample]) -> list[Sample]:
    registry = get_registry()
    tokenizer = registry.tokenizer_for(model)
    if tokenizer is None:
        raise SystemExit(f"no tokenizer for model '{model}'")

    available, reason = tokenizer.available()
    if not available:
        raise SystemExit(
            f"cannot calibrate '{model}': {reason}.\n"
            f"Calibration needs the provider's real counting endpoint — that is "
            f"the entire point. Set the API key and try again."
        )

    semaphore = asyncio.Semaphore(CONCURRENCY)
    measured: list[Sample] = []

    async def one(sample: Sample) -> None:
        async with semaphore:
            sample.base_tokens, _ = count_sync(sample.text, BASE_MODEL)
            result = await tokenizer.count(sample.text, model, want_offsets=False)
            if result.tokens is None:
                print(f"  ! skipped {sample.label}: {result.note}", file=sys.stderr)
                return
            sample.true_tokens = result.tokens
            measured.append(sample)

    await asyncio.gather(*(one(s) for s in samples))
    return measured


def summarise(measured: list[Sample]) -> dict[str, object]:
    ratios = [s.ratio for s in measured]
    fitted = statistics.median(ratios)

    # Error of the FITTED ratio against each sample — this is what the UI
    # shows as the error band, so it must be the residual after fitting, not
    # the spread of the raw ratios.
    errors = [abs(s.ratio - fitted) / s.ratio for s in measured]
    errors.sort()

    def percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, round(pct / 100 * (len(values) - 1)))
        return values[index]

    by_class: dict[str, float] = {}
    classes = {s.content_class for s in measured}
    for content_class in sorted(classes):
        subset = [s.ratio for s in measured if s.content_class == content_class]
        by_class[content_class] = round(statistics.median(subset) / fitted, 4)

    return {
        "ratio": round(fitted, 4),
        "error_p50": round(percentile(errors, 50), 4),
        "error_p90": round(percentile(errors, 90), 4),
        "samples": len(measured),
        "per_class_multiplier": by_class,
    }


def write_back(model: str, family: str, result: dict[str, object]) -> None:
    path = settings.calibration_path
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = (data.get("families") or {}).get(family)
    if entry is None:
        raise SystemExit(f"family '{family}' not present in {path}")

    entry["ratio"] = result["ratio"]
    entry["error_p50"] = result["error_p50"]
    entry["error_p90"] = result["error_p90"]
    entry["calibrated"] = True
    entry["source"] = (
        f"Measured against {model}'s count_tokens endpoint over "
        f"{result['samples']} mixed-content documents."
    )
    entry["notes"] = (
        "MEASURED. Per-content-class multipliers recorded under "
        "content_class_multipliers; the ratio above is the median across all "
        "classes."
    )

    per_class = result["per_class_multiplier"]
    assert isinstance(per_class, dict)
    multipliers = data.setdefault("content_class_multipliers", {})
    multipliers.update(per_class)

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote calibration for family '{family}' to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="e.g. claude-opus-5")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the measured values back to the calibration file",
    )
    args = parser.parse_args()

    provider = provider_for(args.model)
    if provider is None:
        raise SystemExit(f"cannot infer a provider for '{args.model}'")
    family = family_for(args.model, provider)
    if family is None:
        raise SystemExit(f"no calibration family for '{args.model}'")

    corpus = build_corpus()
    print(f"calibrating {args.model} (family '{family}') over {len(corpus)} documents…")

    measured = asyncio.run(measure(args.model, corpus))
    if not measured:
        raise SystemExit("no samples measured — nothing to fit")

    result = summarise(measured)

    print(f"\n  fitted ratio      {result['ratio']}   (tiktoken o200k -> {args.model})")
    print(f"  error p50         {result['error_p50']:.1%}")
    print(f"  error p90         {result['error_p90']:.1%}")
    print(f"  samples           {result['samples']}")
    print("\n  per-content-class multiplier (relative to the fitted ratio):")
    per_class = result["per_class_multiplier"]
    assert isinstance(per_class, dict)
    for content_class, multiplier in per_class.items():
        print(f"    {content_class:<10} {multiplier}")

    if args.write:
        write_back(args.model, family, result)
    else:
        print("\n(dry run — pass --write to update the calibration file)")


if __name__ == "__main__":
    main()
