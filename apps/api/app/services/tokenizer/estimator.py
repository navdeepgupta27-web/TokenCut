"""Heuristic token estimator.

Purpose: fill the ~400ms gap between a keystroke and the exact, debounced
count from a provider's endpoint — and cover the case where that endpoint is
rate-limited or unreachable.

It is a fallback, never a headline. Three rules it enforces structurally:

* A family with no sourced ratio produces **no estimate**. It returns
  ``UNAVAILABLE`` and the UI renders ``—``. Inventing a plausible-looking
  number is the failure mode this whole design exists to prevent.
* Ratios are **per tokenizer family, not per provider**. Anthropic's own
  pricing page states the 4.7+ tokenizer produces ~30% more tokens for the
  same text than earlier models, so a single "Anthropic" ratio would be wrong
  by roughly 30% for half the lineup.
* Every estimate carries ``calibrated`` and, when known, ``estimate_error_p90``,
  so the UI can widen the band and soften the wording.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from app.config import settings
from app.schemas import CountSource
from app.services.tokenizer.base import CountResult
from app.services.tokenizer.openai_tiktoken import OpenAITokenizer

log = logging.getLogger("tokencut.tokenizer.estimator")

_BASE_MODEL = "gpt-4o"  # resolves to o200k_base, the calibration base encoding


@lru_cache(maxsize=1)
def load_calibration() -> dict[str, Any]:
    path = settings.calibration_path
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        log.warning("calibration_file_missing", extra={"path": str(path)})
        return {"families": {}}
    except json.JSONDecodeError as exc:
        log.error("calibration_file_invalid", extra={"path": str(path), "error": str(exc)})
        return {"families": {}}


@lru_cache(maxsize=1)
def _model_to_family() -> dict[str, str]:
    """Invert the calibration file's `applies_to` lists into a lookup."""
    index: dict[str, str] = {}
    for family, entry in (load_calibration().get("families") or {}).items():
        for model_id in entry.get("applies_to") or ():
            index[model_id] = family
    return index


def family_for(model: str, provider: str) -> str | None:
    """Resolve a model id to a calibration family.

    Exact membership first, then a conservative provider-level guess. An
    unrecognised Anthropic model is assumed to be current-generation, because
    under-counting a new model is the worse error — it would understate cost.
    """
    exact = _model_to_family().get(model)
    if exact:
        return exact

    if provider == "anthropic":
        return "anthropic_4_7_plus"
    if provider == "google":
        return "google"
    return None


class Estimator:
    """Not a Tokenizer implementation — it needs the provider, not just the id."""

    def __init__(self) -> None:
        self._base = OpenAITokenizer()

    async def estimate(self, text: str, model: str, provider: str) -> CountResult:
        family_key = family_for(model, provider)
        families = load_calibration().get("families") or {}
        entry = families.get(family_key) if family_key else None

        if not entry or entry.get("ratio") is None:
            return CountResult.unavailable(
                model,
                f"no calibrated estimate available for '{model}'",
            )

        base = await self._base.count(text, _BASE_MODEL, want_offsets=False)
        if base.tokens is None:
            return CountResult.unavailable(model, "base tokenizer unavailable")

        ratio = float(entry["ratio"])
        calibrated = bool(entry.get("calibrated", False))
        error_p90 = entry.get("error_p90")

        # An inferred family is a second layer of guessing on top of an
        # uncalibrated ratio. Say so rather than blur the two.
        inferred_family = model not in _model_to_family()

        if calibrated:
            note = "Estimate. Exact count is loading."
        elif inferred_family:
            note = (
                f"Rough estimate: '{model}' is not in the calibration table, so "
                f"the '{family_key}' ratio was assumed. Indicative only until "
                f"the exact count arrives."
            )
        else:
            note = (
                "Rough estimate from an uncalibrated ratio derived from published "
                "figures, not measured. Indicative only until the exact count "
                "arrives."
            )

        return CountResult(
            model=model,
            tokens=round(base.tokens * ratio),
            source=CountSource.ESTIMATED,
            encoding=f"estimated_from_{base.encoding}_x{ratio}",
            offsets=None,
            includes_message_overhead=False,
            estimate_error_p90=float(error_p90) if error_p90 is not None else None,
            calibrated=calibrated,
            note=note,
        )
