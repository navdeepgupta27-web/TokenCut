# TokenCut — Phase 2: Core Logic & Algorithmic Design

Status: **design draft, not yet approved.** No code written.
Last updated: 2026-09-04

---

## 1. Accurate Token Counting Without Paid API Calls

### 1.1 The premise needs one correction

"Count tokens without making paid API calls" is achievable, but it is **not**
the same as "count tokens without making API calls". For two of the three
providers, an API call is the only accurate path — it just doesn't cost tokens.

| Provider | Method | Offline? | Exact? | Offsets? | Cost |
|---|---|---|---|---|---|
| OpenAI | `tiktoken` encodings | **Yes** | Yes | **Yes** | $0 |
| Anthropic | `POST /v1/messages/count_tokens` | No — keyed HTTPS call | Yes | **No** (total only) | No token charge; rate-limited |
| Google Gemini | `client.models.count_tokens()` | No — keyed HTTPS call | Yes | No | No token charge; rate-limited |

### 1.2 OpenAI — `tiktoken`, fully offline

Encoding is selected per model, not per provider. `o200k_base` covers the
GPT-4o / 4.1 / 5-family and o-series; `cl100k_base` covers GPT-4, GPT-3.5-turbo
and the older embedding models. The mapping must come from
`tiktoken.encoding_for_model()` (and the equivalent table in the WASM build) —
never a hand-maintained dict, which silently rots on every model launch.

Two things a naive implementation gets wrong:

1. **Chat framing overhead.** Raw text tokens ≠ what an API request bills. Chat
   completions add fixed per-message and per-conversation token overhead, and
   tool/function definitions are billed too. TokenCut must model
   `raw_text_tokens` and `billed_request_tokens` as **separate numbers** and
   show both. The exact overhead constants must be taken from OpenAI's own
   cookbook at implementation time, not from memory — they differ by API shape.
2. **Offsets.** `tiktoken` decodes each token id back to bytes, so accumulating
   byte lengths gives exact `[start, end)` character offsets. This is what
   powers the token map — and it only works here.

Runs in a **Web Worker** in the browser via the WASM build. The encoding table
is a multi-megabyte download: lazy-load it on first keystroke, not on page load,
and cache it in the service worker.

### 1.3 Anthropic — `count_tokens`, keyed and free of token charges

Verified facts to build on:

- There is **no public offline tokenizer** for current Claude models.
- `POST /v1/messages/count_tokens` returns `input_tokens` and nothing else — no
  segmentation, no offsets.
- Counts are **model-specific**. Pass the same model id you'd use for
  inference. The tokenizer changed within the Claude 4 line (the Opus 4.7+
  tokenizer produces roughly 1×–1.35× the token count of earlier models on the
  same text), so `claude-opus-5` and `claude-opus-4-6` are genuinely different
  numbers and must not share a cache key.
- **Do not approximate Claude with `tiktoken`.** It undercounts Claude by
  roughly 15–20% on typical prose and by considerably more on code and
  non-English text. A tool whose entire value proposition is accuracy cannot
  ship that.

Design consequences:

- The Anthropic API key lives on the backend only, in an env var.
- Redis cache keyed `sha256(text) + ":" + model_id`, 24h TTL. Value is an
  integer. This is what keeps the free tier alive under traffic.
- Per-IP rate limit in front of it, plus a global circuit breaker: if Anthropic
  returns 429s, degrade to the estimator with `source: "estimated"` rather than
  failing the request.
- **Standing risk to flag:** using a provider's free counting endpoint as
  backing infrastructure for a public free tool is exactly the pattern that
  gets rate-limited or restricted. Mitigate with caching + BYO-key for heavy
  users, and re-read each provider's terms before launch. Have the estimator
  fallback ready as a first-class path, not an error case.

### 1.4 Gemini

`count_tokens` on the `google-genai` client, same shape: keyed, no token
charge, no offsets. A **local** SentencePiece tokenizer may be available via the
Vertex AI tokenization extra — worth 30 minutes of verification in Phase 3,
because if it works it moves Gemini into the offline column and removes a whole
dependency. Design as keyed; treat local as an upside.

### 1.5 The two-tier counting model (this is the core UX mechanic)

```
keystroke
   │
   ├─► tier 1  local, synchronous, every keystroke
   │     · OpenAI  → tiktoken WASM  → EXACT  (source: exact_local)
   │     · Claude  → estimator      → ≈      (source: estimated)
   │     · Gemini  → estimator      → ≈      (source: estimated)
   │
   └─► tier 2  debounced 400ms, one /v1/analyze call
         · Claude  → count_tokens (or cache) → EXACT (source: exact_api)
         · Gemini  → count_tokens (or cache) → EXACT (source: exact_api)
         → estimates are replaced; the ≈ marker disappears
```

**The estimator must be calibrated, not invented.** Method:

1. Assemble a corpus of ~2,000 documents spanning the real input mix: English
   prose, code (several languages), pretty-printed JSON, markdown, CJK,
   Indic scripts, and mixed.
2. For each doc, record `tiktoken` count, character count, byte count, and the
   true `count_tokens` result per target model.
3. Fit a small model — a per-content-class ratio against the `tiktoken` count
   is usually enough — and record **measured error percentiles (p50/p90/p99)**
   per class.
4. Ship the coefficients as versioned data alongside the pricing catalog, and
   surface the p90 error in a tooltip: "estimate, typically within X%".

Two hard rules: never display an estimate without the `≈` marker, and never
let an estimate feed the cost calculator's headline number without the range
being shown. Publishing the calibration methodology is also a genuinely good
SEO/credibility asset.

---

## 2. The Optimization Engine

### 2.1 Design principles

1. **Measure by re-tokenizing.** A rule's saving is
   `tokens(before) − tokens(after)` under the user's selected tokenizer. Never
   character counts. Character savings and token savings diverge badly —
   Unicode normalization can save one character and four tokens.
2. **Lossless is applied; lossy is only suggested.** Anything that could change
   what the model does is an opt-in suggestion with a stated risk, defaulted
   off. This is the product's integrity and its differentiator.
3. **Every rule is a reversible diff.** Rules emit `{start, end, replacement}`
   edit ops against the original text, never a rewritten blob. That gives the
   UI a diff, per-rule toggling, and undo for free.
4. **Protected regions are computed first.** No rule touches a protected span.
5. **Order matters and is fixed.** Rules run in a declared sequence; savings are
   attributed to whichever rule actually made the cut, so the per-rule numbers
   sum to the total.

### 2.2 Pass 0 — segmentation into protected regions

Before any rule runs, classify the text into a typed span list:

`fenced_code` · `inline_code` · `json_block` · `xml_html_block` ·
`url` · `email` · `base64_blob` · `template_var` (`{{x}}`, `${x}`, `%s`) ·
`markdown_table` · `frontmatter` · `prose`

This pass is what separates a usable tool from one that corrupts prompts.
Collapsing whitespace inside a Python block or a JSON string literal is a
data-destroying bug, and it is the single most common failure in naive
"prompt compressor" tools. Each rule declares which span kinds it may operate
on; the pipeline enforces it.

### 2.3 Rule schema

```jsonc
{
  "id": "json_to_markdown_table",
  "name": "Convert JSON array to Markdown table",
  "category": "lossless" | "structural" | "prompt_audit" | "semantic",
  "risk": "safe" | "moderate" | "aggressive",
  "applies_to": ["json_block"],
  "default_in": ["balanced", "aggressive"],   // which profiles enable it
  "semantic_risk_note": "…shown in the UI when risk > safe",
  "reversible": true
}
```

### 2.4 Tier 0 — Lossless normalization (`risk: safe`, always on)

Operates on `prose` and `markdown_table` only.

| Rule | What it does | Why it saves tokens |
|---|---|---|
| `collapse_spaces` | runs of spaces/tabs → single space | leading-space variants are distinct tokens |
| `trim_trailing_ws` | strip end-of-line whitespace | pure waste |
| `collapse_blank_lines` | 3+ newlines → 2 | each newline can be its own token |
| `normalize_unicode` | smart quotes, en/em dashes, NBSP, ellipsis → ASCII | a curly quote often costs 1–3 tokens vs 1 for `'` |
| `strip_zero_width` | ZWSP, ZWNJ, BOM | invisible, non-free |
| `normalize_line_endings` | CRLF → LF | the `\r` is frequently a separate token |
| `dedent_overindent` | normalize runaway indentation | leading-whitespace tokens |

Individually small. On real pasted prompts — especially anything copied out of
a Word doc, a Notion page, or a Slack message — collectively meaningful, and
100% safe. This is the tier that builds trust.

### 2.5 Tier 1 — Structural re-encoding (`risk: safe`–`moderate`)

Where the large, defensible wins are.

- **`compact_json`** — strip formatting whitespace from JSON blocks. Byte-identical
  semantics. Pretty-printed payloads pasted into prompts are extremely common
  and the indentation is pure cost.
- **`json_to_markdown_table`** — an array of uniform objects repeats every key on
  every row. A table states each key once. This is typically the **single
  largest win in the entire engine** on data-heavy prompts, and it's the demo
  that sells the tool. Guardrails: only for arrays of flat, uniformly-keyed
  objects; abort on nesting or ragged keys.
- **`xml_to_markdown`** — closing tags are ~half the markup's tokens. Caveat worth
  stating in the UI: some prompting styles deliberately use XML tags as
  structural delimiters for the model. Mark this `moderate`, not `safe`.
- **`html_strip`** — pasted HTML → text/markdown.
- **`flag_base64`** — do not transform; **warn**. Base64 tokenizes catastrophically.
  The correct advice is "don't put this in a prompt", not "compress it".
- **`detect_repeated_blocks`** — if a large block recurs across the input, the
  right answer is usually **prompt caching, not deletion**. Surface that as
  advice with a link, and (for Anthropic) show the cache-adjusted cost in the
  Savings tab. Recommending a competitor's own feature over your compression is
  the kind of honesty that earns the audience this tool needs.
- **`reduce_numeric_precision`** — `moderate`. Offer, never auto-apply; the user
  knows whether 8 decimal places matter.

### 2.6 Tier 2 — Prompt audit (`risk: moderate`, suggestions only, default OFF)

Detected via curated phrase lists + light POS heuristics. Each hit is a
highlighted span with a one-click apply. **Never auto-applied.**

- Politeness scaffolding: "please", "thank you", "I would like you to…"
- Filler openers: "In this task, you will…", "As an AI language model…"
- Redundant role restatement: the persona repeated in three places
- Hedge stacking: "very carefully and thoroughly and precisely"
- Duplicate constraints: the same "do not X" expressed twice
- Verbose enumerations that a list would express in fewer tokens

**Required honesty guardrail.** Some of the folklore here — that removing
politeness or adding "take a deep breath" measurably changes output quality —
is weakly evidenced and model-dependent. The UI must present these as *token
savings with unquantified behavioural risk*, and must never claim "identical
output". Suggested UI copy: *"Removing this saves 23 tokens. It may change how
the model responds — review before applying."*

That single sentence is the difference between a credible tool and one that
gets torn apart in a Hacker News thread.

### 2.7 Tier 3 — Semantic compression (V2, paid, opt-in)

LLM-assisted rewrite to a target token budget, with a diff for review and a
quality check. Genuinely lossy. Has real per-request cost, so it cannot be
free — which makes it a natural Pro feature rather than a problem.

Ships only with: a mandatory side-by-side diff, an explicit "this changes your
prompt's meaning" acknowledgement, and never as a default.

### 2.8 Pipeline

```
input
  └─► pass 0  segment → protected span map
  └─► pass 1  tier 0 rules (enabled by profile)      → edit ops
  └─► pass 2  tier 1 rules (enabled by profile)      → edit ops
  └─► pass 3  tier 2 detectors                       → suggestions (not applied)
  └─► pass 4  resolve overlapping ops, apply in reverse offset order
  └─► pass 5  re-tokenize; attribute savings per rule; assemble response
```

Applying in **reverse offset order** keeps earlier offsets valid — the standard
approach, and the thing that breaks first if ignored. Overlapping ops resolve by
declared rule priority; conflicts are dropped, not merged.

### 2.9 Validation the engine must ship with

- **Round-trip tests**: for every `lossless` rule, assert the transform is a
  no-op on protected spans and semantically identity-preserving elsewhere.
- **JSON equivalence tests**: `json.loads(before) == json.loads(after)` for
  every structural JSON rule. Non-negotiable.
- **Corpus regression**: run the full pipeline over the calibration corpus and
  assert no rule ever *increases* token count. Normalization can backfire on
  some inputs; catch it in CI.

---

## 3. Cost Model

### 3.1 Notation

| Symbol | Meaning |
|---|---|
| `Tᵢᵣ`, `Tᵢₒ` | input tokens, raw / optimized |
| `Tₒ` | output tokens per call (estimated — see §3.3) |
| `Pᵢ`, `Pₒ` | price per **1M** input / output tokens, model-specific |
| `N` | calls per month |
| `f_r` | fraction of input served from prompt cache |
| `f_w` | fraction of input written to cache |
| `f_b` | fraction of calls sent via a batch endpoint |

### 3.2 Core equations

Cost of one call:

```
C = (Tᵢ / 1e6)·Pᵢ  +  (Tₒ / 1e6)·Pₒ
```

Savings per call from optimization:

```
ΔC = ((Tᵢᵣ − Tᵢₒ) / 1e6) · Pᵢ
```

**The output term cancels.** This is the most important line in the cost model
and the one every competitor calculator fudges: *compressing your prompt
reduces input cost only.* It does not shorten the response. A tool that shows
"total cost before vs after" with an unchanged output estimate is implicitly
taking credit for nothing. State it plainly in the UI.

Monthly: `ΔC_month = ΔC · N`.

### 3.3 Output tokens are an input, not an assumption

`Tₒ` is unknowable from the prompt. Three options, in order:

1. User enters it (default; pre-filled from a per-use-case preset).
2. A ratio `Tₒ = r · Tᵢ` with `r` visible and editable.
3. If neither, **show input-cost savings only** and say so.

Never silently assume a value. Every number the calculator renders carries its
assumptions in an `assumptions[]` list displayed beneath it.

### 3.4 Caching interaction (the sophisticated bit)

With prompt caching, the effective input price is a blend:

```
P_eff = f_r·(Pᵢ·k_read) + f_w·(Pᵢ·k_write) + (1 − f_r − f_w)·Pᵢ
```

where `k_read` and `k_write` are the provider's cache multipliers (for
Anthropic, cache reads are roughly a tenth of base input price and cache writes
roughly 1.25× — verify current multipliers and TTL tiers from the provider docs
at implementation time).

The non-obvious consequence, worth its own UI callout: **compression and
caching partly compete.** Tokens already being served from cache are cheap;
compressing them saves ten cents on the dollar. Worse, *editing* a cached prefix
invalidates the cache — so compressing a stable system prompt can cost more than
it saves by forcing a re-write on the next call. TokenCut should detect a
large stable prefix and say so:

> *"This 3,200-token block looks like a stable system prompt. Caching it will
> save more than compressing it — and compressing it will invalidate your
> existing cache."*

Nobody else does this. It is the most defensible thing in the product.

Batch endpoints: `P_batch = P · (1 − d_batch)` applied to the `f_b` fraction.

### 3.5 Pricing data — the no-fabricated-numbers rule

Pricing lives in **`data/pricing/catalog.json`**, never in application code.
Schema per model:

```jsonc
{
  "id": "claude-opus-5",
  "provider": "anthropic",
  "display_name": "Claude Opus 5",
  "input_per_mtok": 5.00,
  "output_per_mtok": 25.00,
  "cache_read_multiplier": null,      // null = unverified, UI must not use it
  "cache_write_multiplier": null,
  "batch_discount": null,
  "context_window": 1000000,
  "tokenizer": "anthropic_count_tokens_api",
  "source_url": "https://…official pricing page…",
  "retrieved_at": "2026-06-24",
  "verified_by": "…"
}
```

Rules enforced in CI:

- A `null` price renders as **"—  price not verified"** in the UI. It never
  falls back to a guess, and never participates in a total.
- Every entry needs `source_url` + `retrieved_at`.
- A CI job fails the build when any `retrieved_at` is older than 30 days.
- The UI footer shows "Prices as of `<oldest retrieved_at>`" with source links.

**What I can seed today, and what I cannot.** Anthropic first-party API rates
below are from the Claude API reference bundled with this session, cached
`2026-06-24` — they must still be re-verified against the live pricing page
before launch, and they do **not** apply to Bedrock or Vertex, which are
separately priced.

| Model | Input $/1M | Output $/1M |
|---|---|---|
| Claude Opus 5 | 5.00 | 25.00 |
| Claude Sonnet 5 | 2.00 | 10.00 |
| Claude Haiku 4.5 | 1.00 | 5.00 |
| Claude Opus 4.6 | 5.00 | 25.00 |
| Claude Sonnet 4.6 | 3.00 | 15.00 |

**OpenAI and Google pricing: I am not filling these in from memory.** Model
prices change often and a wrong figure in a cost calculator is the one bug that
destroys the product's credibility permanently. These rows get populated during
Phase 3 by reading the official pricing pages, with `source_url` and
`retrieved_at` recorded per row.

### 3.6 Presenting savings honestly

- Headline: **input-token savings**, in tokens and in dollars, at the user's
  stated volume.
- Show a **range**, not a point, whenever any component is an estimate.
- Never extrapolate to "per year" without the user setting the volume — annual
  figures from a made-up call count are the classic dishonest-calculator move.
- Show the counterfactual where it's true: *"caching would save more than
  compression here."*

---

## 4. What I need from you before Phase 3

Repeating the open decisions from `01-architecture.md` §5, plus:

6. Do we build the calibration corpus (§1.5) in V1? It is a day of work and it
   is what makes the instant estimates defensible. Skipping it means shipping
   with no `≈` numbers at all — Claude/Gemini counts only appear after the
   debounce. That is a legitimate, honest V1 choice.
7. Is Anthropic prompt-caching advice (§3.4) in V1 scope? I think it is the
   strongest differentiator, and it is mostly cost-model work rather than new
   infrastructure.
