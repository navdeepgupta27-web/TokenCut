/**
 * Mirror of the FastAPI contract in `apps/api/app/schemas.py`.
 *
 * Hand-maintained for now. Once the API stabilises, generate this from
 * `/openapi.json` at build time so the two cannot drift — a duplicated
 * contract is a contract that will eventually disagree with itself.
 *
 * The `CountSource` union is the important part of this file. It is what the
 * whole UI keys off to decide whether a number may be shown as fact.
 */

/** How a token count was obtained. Drives the `≈` / `—` markers. */
export type CountSource =
  | "exact_local" // offline tokenizer, exact
  | "exact_api" // provider count endpoint, exact
  | "cached" // previously exact
  | "estimated" // heuristic — MUST render with "≈"
  | "unavailable"; // no count possible — MUST render "—"

export type RiskLevel = "safe" | "moderate" | "aggressive";
export type RuleCategory = "lossless" | "structural" | "prompt_audit" | "advisory";
export type Profile = "safe" | "balanced" | "aggressive";

export type SegmentKind =
  | "prose"
  | "fenced_code"
  | "inline_code"
  | "json_block"
  | "xml_html_block"
  | "markdown_table"
  | "frontmatter"
  | "url"
  | "email"
  | "base64_blob"
  | "template_var";

export interface TokenResult {
  model: string;
  tokens: number | null;
  source: CountSource;
  encoding: string | null;
  /** Exact [start, end) char offsets. OpenAI family only — null elsewhere. */
  offsets: [number, number][] | null;
  includes_message_overhead: boolean;
  estimate_error_p90: number | null;
  /** For estimates: false means the ratio is a heuristic, not a measured fit. */
  calibrated: boolean | null;
  note: string | null;
}

export interface Segment {
  start: number;
  end: number;
  kind: SegmentKind;
  tokens: Record<string, number>;
}

export interface TokenizeResponse {
  results: TokenResult[];
  segments: Segment[] | null;
  chars: number;
  bytes: number;
  warnings: string[];
}

export interface EditOp {
  start: number;
  end: number;
  replacement: string;
}

export interface AppliedRule {
  rule_id: string;
  name: string;
  category: RuleCategory;
  risk: RiskLevel;
  occurrences: number;
  tokens_saved: number;
  edits: EditOp[];
}

export interface SuggestedRule {
  rule_id: string;
  name: string;
  category: RuleCategory;
  risk: RiskLevel;
  occurrences: number;
  tokens_saved_if_applied: number;
  semantic_risk_note: string;
  spans: [number, number][];
  advice: string | null;
}

export interface OptimizeResponse {
  optimized_text: string;
  applied: AppliedRule[];
  suggested: SuggestedRule[];
  tokens_before: number;
  tokens_after: number;
  measure_model: string;
  measure_source: CountSource;
  warnings: string[];
}

export interface ModelCost {
  model: string;
  available: boolean;
  unavailable_reason: string | null;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
  effective_input_per_mtok: number | null;
  cost_before_per_call: number | null;
  cost_after_per_call: number | null;
  saved_per_call: number | null;
  saved_per_month: number | null;
  input_only: boolean;
  pricing_retrieved_at: string | null;
  pricing_source_url: string | null;
  /** Model-specific pricing caveat from the catalog. Rendered verbatim. */
  pricing_note: string | null;
  /**
   * True when optimization moved the prompt into a cheaper length-based band
   * (Gemini Pro doubles above 200k input tokens), so the per-token *rate*
   * changed and not just the count.
   */
  crossed_pricing_tier: boolean;
}

export interface CostResponse {
  results: ModelCost[];
  tokens_saved_per_call: number;
  /** Rendered verbatim in the UI. Never summarised, never hidden. */
  assumptions: string[];
  warnings: string[];
  pricing_oldest_retrieved_at: string | null;
}

export interface AnalyzeResponse {
  tokenize: TokenizeResponse;
  optimize: OptimizeResponse;
  tokenize_optimized: TokenizeResponse;
  cost: CostResponse;
  warnings: string[];
}

export interface ModelInfo {
  id: string;
  provider: string;
  display_name: string;
  context_window: number | null;
  tokenizer: string;
  supports_offsets: boolean;
  counting: "offline" | "api" | "estimate_only" | "unavailable";
  available: boolean;
  unavailable_reason: string | null;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
  pricing_source_url: string | null;
  pricing_retrieved_at: string | null;
  pricing_verified: boolean;
}

export interface ModelsResponse {
  models: ModelInfo[];
  pricing_oldest_retrieved_at: string | null;
  pricing_stale: boolean;
  warnings: string[];
}

export interface ProviderStatus {
  available: boolean;
  reason: string | null;
  /** True when counting needs no network call and no credential. */
  local: boolean;
  /** True when the provider can supply per-token character offsets. */
  offsets: boolean;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  providers: Record<string, ProviderStatus>;
  cache: string;
}

export interface RuleInfo {
  id: string;
  name: string;
  category: RuleCategory;
  risk: RiskLevel;
  suggestion_only: boolean;
  default_in: Profile[];
  semantic_risk_note: string;
}

export interface RulesResponse {
  rules: RuleInfo[];
}

/** The API's single error envelope. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string;
  };
}

export interface AnalyzeRequest {
  text: string;
  models: string[];
  profile: Profile;
  rules: Record<string, boolean>;
  include_offsets: boolean;
  include_segments: boolean;
  tokens_out: number | null;
  calls_per_month: number;
  cache_read_fraction: number;
  cache_write_fraction: number;
  batch_fraction: number;
}

/** True when a count may be presented as fact rather than an approximation. */
export function isExact(source: CountSource): boolean {
  return source === "exact_local" || source === "exact_api" || source === "cached";
}
