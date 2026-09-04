"""Public API contract.

The single most important rule in this file: **no bare integers**. Every count
carries a ``source``, and every cost carries its ``assumptions``. A number
without provenance is a number the product can be wrong about silently.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CountSource(str, Enum):
    """Where a token count came from. Drives the `≈` marker in the UI."""

    EXACT_LOCAL = "exact_local"   # offline tokenizer (tiktoken). Exact, free.
    EXACT_API = "exact_api"       # provider count endpoint. Exact, keyed.
    CACHED = "cached"             # previously exact, served from cache.
    ESTIMATED = "estimated"       # heuristic. UI MUST render "≈".
    UNAVAILABLE = "unavailable"   # no key / no calibration. UI MUST render "—".


class RiskLevel(str, Enum):
    SAFE = "safe"              # semantics preserved; applied automatically
    MODERATE = "moderate"      # representation changes; may alter behaviour
    AGGRESSIVE = "aggressive"  # meaning may change; never auto-applied


class RuleCategory(str, Enum):
    LOSSLESS = "lossless"
    STRUCTURAL = "structural"
    PROMPT_AUDIT = "prompt_audit"
    ADVISORY = "advisory"      # emits no edit; surfaces a recommendation


class Profile(str, Enum):
    SAFE = "safe"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class SegmentKind(str, Enum):
    PROSE = "prose"
    FENCED_CODE = "fenced_code"
    INLINE_CODE = "inline_code"
    JSON_BLOCK = "json_block"
    XML_HTML_BLOCK = "xml_html_block"
    MARKDOWN_TABLE = "markdown_table"
    FRONTMATTER = "frontmatter"
    URL = "url"
    EMAIL = "email"
    BASE64_BLOB = "base64_blob"
    TEMPLATE_VAR = "template_var"


# --------------------------------------------------------------------------
# Shared
# --------------------------------------------------------------------------

TextField = Annotated[str, Field(max_length=2_000_000, description="Prompt text to analyse.")]


class TokenResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    model: str
    tokens: int | None = Field(default=None, description="None when source is 'unavailable'.")
    source: CountSource
    encoding: str | None = Field(
        default=None, description="Tokenizer/encoding identifier, when knowable."
    )
    offsets: list[tuple[int, int]] | None = Field(
        default=None,
        description=(
            "Exact [start, end) character offsets per token. Available for the "
            "OpenAI family only — Anthropic and Google return a total with no "
            "segmentation. Never synthesise these for other providers."
        ),
    )
    includes_message_overhead: bool = Field(
        default=False,
        description=(
            "True when the count includes the provider's chat-request framing "
            "(Anthropic's count_tokens does). Raw text tokens and billed "
            "request tokens are different numbers; the UI must not conflate them."
        ),
    )
    estimate_error_p90: float | None = Field(
        default=None,
        description="For source='estimated': measured p90 relative error, if calibrated.",
    )
    calibrated: bool | None = Field(
        default=None,
        description="For source='estimated': False means the ratio is a heuristic, not measured.",
    )
    note: str | None = None


class Segment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    start: int
    end: int
    kind: SegmentKind
    tokens: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Per-model token share for this segment. Per-segment counts do not "
            "sum exactly to the whole-text count (framing overhead, boundary "
            "effects); the UI normalises to the exact total."
        ),
    )


# --------------------------------------------------------------------------
# /v1/tokenize
# --------------------------------------------------------------------------


class TokenizeRequest(BaseModel):
    text: TextField
    models: list[str] = Field(min_length=1, max_length=12)
    include_offsets: bool = False
    include_segments: bool = False


class TokenizeResponse(BaseModel):
    results: list[TokenResult]
    segments: list[Segment] | None = None
    chars: int
    bytes: int
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# /v1/optimize
# --------------------------------------------------------------------------


class EditOp(BaseModel):
    start: int
    end: int
    replacement: str


class AppliedRule(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    rule_id: str
    name: str
    category: RuleCategory
    risk: RiskLevel
    occurrences: int
    tokens_saved: int
    edits: list[EditOp] = Field(default_factory=list)


class SuggestedRule(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    rule_id: str
    name: str
    category: RuleCategory
    risk: RiskLevel
    occurrences: int
    tokens_saved_if_applied: int
    semantic_risk_note: str
    spans: list[tuple[int, int]] = Field(default_factory=list)
    advice: str | None = Field(
        default=None,
        description="For advisory rules: what to do instead of compressing.",
    )


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    text: TextField
    profile: Profile = Profile.BALANCED
    rules: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-rule override of the profile default. rule_id -> enabled.",
    )
    measure_with: str = Field(
        default="gpt-4o",
        description=(
            "Model whose tokenizer measures savings. Must resolve to a LOCAL "
            "tokenizer: attribution re-tokenizes once per rule, which is free "
            "offline and unaffordable against a keyed endpoint."
        ),
    )


class OptimizeResponse(BaseModel):
    optimized_text: str
    applied: list[AppliedRule]
    suggested: list[SuggestedRule]
    tokens_before: int
    tokens_after: int
    measure_model: str
    measure_source: CountSource
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# /v1/cost
# --------------------------------------------------------------------------


class CostRequest(BaseModel):
    tokens_in_before: int = Field(ge=0)
    tokens_in_after: int = Field(ge=0)
    tokens_out: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Output tokens per call. Unknowable from the prompt — supplied by "
            "the user. When None, only input-side cost is reported and an "
            "assumption is recorded saying so."
        ),
    )
    calls_per_month: int = Field(default=1, ge=0)
    models: list[str] = Field(min_length=1, max_length=24)
    cache_read_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    cache_write_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    batch_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class ModelCost(BaseModel):
    model: str
    available: bool = Field(
        description="False when the catalog has no verified price. Excluded from totals."
    )
    unavailable_reason: str | None = None

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    effective_input_per_mtok: float | None = None

    cost_before_per_call: float | None = None
    cost_after_per_call: float | None = None
    saved_per_call: float | None = None
    saved_per_month: float | None = None

    input_only: bool = Field(
        default=False,
        description="True when tokens_out was not supplied; costs cover input alone.",
    )
    pricing_retrieved_at: str | None = None
    pricing_source_url: str | None = None
    pricing_note: str | None = Field(
        default=None,
        description="Model-specific pricing caveat from the catalog, rendered as-is.",
    )
    crossed_pricing_tier: bool = Field(
        default=False,
        description=(
            "True when optimization moved the prompt into a cheaper length-based "
            "pricing band, so the per-token rate changed as well as the count."
        ),
    )


class CostResponse(BaseModel):
    results: list[ModelCost]
    tokens_saved_per_call: int
    assumptions: list[str] = Field(
        description="Rendered verbatim in the UI. Every default is stated here, never implied."
    )
    warnings: list[str] = Field(default_factory=list)
    pricing_oldest_retrieved_at: str | None = None


# --------------------------------------------------------------------------
# /v1/analyze  — composite; what the web app calls
# --------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    text: TextField
    models: list[str] = Field(min_length=1, max_length=12)
    profile: Profile = Profile.BALANCED
    rules: dict[str, bool] = Field(default_factory=dict)
    include_offsets: bool = False
    include_segments: bool = False

    tokens_out: int | None = Field(default=None, ge=0)
    calls_per_month: int = Field(default=1, ge=0)
    cache_read_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    cache_write_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    batch_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class AnalyzeResponse(BaseModel):
    tokenize: TokenizeResponse
    optimize: OptimizeResponse
    tokenize_optimized: TokenizeResponse
    cost: CostResponse
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# /v1/models
# --------------------------------------------------------------------------


class ModelInfo(BaseModel):
    id: str
    provider: str
    display_name: str
    context_window: int | None = None
    tokenizer: str
    supports_offsets: bool
    counting: Literal["offline", "api", "estimate_only", "unavailable"]
    available: bool
    unavailable_reason: str | None = None

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    pricing_source_url: str | None = None
    pricing_retrieved_at: str | None = None
    pricing_verified: bool


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    pricing_oldest_retrieved_at: str | None = None
    pricing_stale: bool
    warnings: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    providers: dict[str, Any]
    cache: str
