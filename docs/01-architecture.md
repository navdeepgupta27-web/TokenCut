# TokenCut — Phase 1: Product Spec & Architecture

Status: **design draft, not yet approved.** No code written.
Last updated: 2026-09-04

---

## 0. Naming

Working directory is `TokenCut`; the brief said "TokenShrink or similar".
Docs use **TokenCut** throughout. Change once, here, before Phase 3 — the name
leaks into package names, the API host, and every SEO page slug.

Domain check needed before committing: `tokencut.dev` / `tokencut.app` /
`tokencut.io`. Avoid anything an LLM provider could read as trademark-adjacent.

---

## 1. System Architecture

### 1.1 The honest version of "why split the stack"

The brief's premise was that a Python backend is *necessary* for native
tokenization. That is **half true**, and the half that's false is the more
important half — it changes the architecture.

| Provider | Offline tokenizer available? | Consequence |
|---|---|---|
| **OpenAI** | **Yes.** `tiktoken` (Python, Rust core) *and* WASM/JS ports (`js-tiktoken`, `gpt-tokenizer`) | Can run **in the browser**. No server needed. |
| **Anthropic** | **No.** There is no public offline tokenizer for Claude 3+/4/5 models. Counts come from `POST /v1/messages/count_tokens` | **Requires a server** holding an API key |
| **Google Gemini** | Only via `client.models.count_tokens()` (keyed API call). A local SentencePiece path may exist via the Vertex AI tokenization extra — **must be verified in Phase 3**, do not design around it as a certainty | **Requires a server** |

So the split is necessary — but not for the reason stated. It is necessary
because **two of the three providers require a secret API key to count tokens
at all**, and a secret key cannot live in a browser bundle.

Three further reasons the backend is non-optional:

1. **The Optimization Engine** needs the tokenizer in-process. Every rule's
   saving must be measured by *re-tokenizing*, not by counting characters.
   That measurement loop is the product.
2. **The API product** (Phase 5 monetization) is the backend. If the tool is
   pure client-side, there is nothing to sell to developers.
3. **Caching and rate limiting.** `count_tokens` is free of token charges but
   is a rate-limited, keyed network call. A public tool hammering it per
   keystroke will get throttled. Redis-backed caching is mandatory, and it has
   to live server-side.

### 1.2 Recommended shape: hybrid, not pure split

```
┌─────────────────────────────── BROWSER ───────────────────────────────┐
│  Next.js 15 (App Router) · TypeScript · Tailwind · shadcn/ui          │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  WASM tiktoken (Web Worker)                                    │   │
│  │  → OpenAI counts + exact token OFFSETS, on every keystroke     │   │
│  │  → 0ms server latency · $0 cost · text never leaves the device │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  Local heuristic estimator (calibrated)                        │   │
│  │  → instant "≈" numbers for Claude/Gemini while the             │   │
│  │    debounced server call is in flight                          │   │
│  └────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │  HTTPS · debounced 400ms · JSON
                                ▼
┌─────────────────────────────── BACKEND ───────────────────────────────┐
│  FastAPI (Python 3.12, async, uvicorn) — Render / Railway / Fly       │
│                                                                        │
│  routers/    tokenize · optimize · cost · analyze · models · batch     │
│  services/   tokenizer_registry · optimizer pipeline · cost_engine     │
│  adapters/   openai_tiktoken · anthropic_count · gemini_count          │
│  infra/      redis cache · rate limiter · structured logging           │
└──────────┬────────────────────────────────┬───────────────────────────┘
           │                                │
           ▼                                ▼
   ┌───────────────┐              ┌─────────────────────────┐
   │ Redis (Upstash│              │ Provider count APIs     │
   │ free tier)    │              │ Anthropic count_tokens  │
   │ · count cache │              │ Google count_tokens     │
   │ · rate limits │              │ (free of token charges, │
   │ · quotas      │              │  but keyed + throttled) │
   └───────────────┘              └─────────────────────────┘

   ┌──────────────────────────────────────────────┐
   │ Postgres (Neon/Supabase) — V2 ONLY           │
   │ users · api_keys · usage_events · history    │
   │ Deliberately absent from V1.                 │
   └──────────────────────────────────────────────┘
```

**Why this beats a pure split:** the first-paint experience needs zero backend.
A visitor types, and OpenAI counts appear instantly with real token
highlighting — even if the backend is cold-starting, throttled, or down. The
backend is then an *enhancement layer* (Claude, Gemini, optimization), not a
single point of failure on the landing path.

### 1.3 Deployment-tier realities to design around

- **Render free tier sleeps after ~15 min idle**, with a cold start on the
  order of tens of seconds. For a tool judged in the first three seconds, a
  cold backend on the critical path is fatal. Mitigations, in order of
  preference: (a) client-side path stays useful with zero backend — already in
  the design above; (b) fire a `/health` warm-up ping on page load, before the
  user finishes typing; (c) an external cron pinging every 10 min; (d) pay for
  a non-sleeping tier (Fly.io / Railway) once traffic justifies it.
- **Verify current free-tier terms before committing** — sleep thresholds,
  cold-start times, and free-tier existence all change. Do not treat the
  numbers above as current fact without checking.

### 1.4 Privacy as an architectural constraint (and a marketing asset)

The target user pastes production system prompts. That is confidential
material. This has to be a design constraint, not a policy page:

- OpenAI path: text **never leaves the browser**. Say so on the landing page.
- Server paths: prompt bodies are **never** written to logs, metrics, or the
  database. Log `sha256(text)[:16]`, byte length, and token count only.
- Cache keys are hashes; cache values are integers. No plaintext at rest.
- Optional "Local-only mode" toggle that disables all non-OpenAI models.
- If a Claude/Gemini count is requested, the text transits Anthropic's or
  Google's counting endpoint. **Disclose this in the UI**, next to those model
  chips. Do not bury it.

---

## 2. API Surface

Base: `https://api.tokencut.dev/v1`. Versioned from day one — the public API is
a product in V2 and cannot be broken casually.

### 2.1 Conventions

- All bodies JSON. All responses carry `X-Request-Id`.
- Errors use one envelope:
  ```json
  { "error": { "code": "rate_limited", "message": "…",
               "details": {}, "request_id": "req_…" } }
  ```
- Codes: `invalid_request`, `unsupported_model`, `text_too_large`,
  `rate_limited` (+ `Retry-After`), `upstream_unavailable`, `internal_error`.
- Every count carries a **provenance field**, never a bare integer:
  `"source": "exact_local" | "exact_api" | "estimated" | "cached"`.
  The UI renders `≈` for `estimated`. This is the single most important
  contract in the whole API — it is what stops the product from lying.

### 2.2 Endpoints

#### `GET /v1/models`
Static-ish catalog: model ids, families, tokenizer metadata, context windows,
pricing, and `pricing_retrieved_at`. Cached hard at the edge. The frontend
builds its model picker and its cost math from this and nothing else.

#### `POST /v1/tokenize`
```jsonc
// request
{
  "text": "…",
  "models": ["gpt-4o", "claude-opus-5", "gemini-2.5-pro"],
  "include_segments": true,      // per-segment attribution for the heat map
  "include_offsets": false       // exact token offsets; OpenAI-family only
}
// response
{
  "results": [
    { "model": "gpt-4o", "tokens": 1284, "source": "exact_local",
      "offsets": [[0,3],[3,9], …] },
    { "model": "claude-opus-5", "tokens": 1402, "source": "exact_api" },
    { "model": "gemini-2.5-pro", "tokens": 1331, "source": "exact_api" }
  ],
  "segments": [ { "start": 0, "end": 412, "kind": "prose",
                  "share": { "gpt-4o": 96, "claude-opus-5": 104 } } ],
  "chars": 5120, "bytes": 5124
}
```

#### `POST /v1/optimize`
```jsonc
// request
{
  "text": "…",
  "profile": "safe" | "balanced" | "aggressive",
  "rules": { "collapse_whitespace": true, "json_to_markdown_table": true,
             "flag_politeness": false },          // explicit per-rule override
  "protect": ["code", "urls", "json_values"],     // protected region kinds
  "measure_with": "gpt-4o"                        // tokenizer used for savings
}
// response
{
  "optimized_text": "…",
  "applied": [
    { "rule_id": "collapse_whitespace", "category": "lossless",
      "risk": "safe", "occurrences": 42, "tokens_saved": 61,
      "edits": [ { "start": 88, "end": 94, "replacement": " " } ] }
  ],
  "suggested": [
    { "rule_id": "flag_politeness", "category": "prompt_audit",
      "risk": "moderate", "occurrences": 7, "tokens_saved_if_applied": 23,
      "semantic_risk": "May alter tone; unlikely to change task output.",
      "spans": [[210,224], …] }
  ],
  "tokens_before": 1284, "tokens_after": 1109, "measure_source": "exact_local"
}
```
`applied` vs `suggested` is the core safety split: lossless transforms are
applied; anything that could change model behaviour is only *offered*, with a
stated risk, defaulted off.

#### `POST /v1/cost`
```jsonc
{
  "tokens_in_before": 1284, "tokens_in_after": 1109,
  "tokens_out": 500,                 // user estimate; see Phase 2 §3
  "calls_per_month": 30000,
  "models": ["gpt-4o", "claude-opus-5"],
  "cache_read_fraction": 0.0,        // 0..1, optional
  "batch_fraction": 0.0              // 0..1, optional
}
```
Returns a per-model matrix of `cost_before`, `cost_after`, `saved_per_call`,
`saved_per_month`, plus `assumptions[]` and `pricing_retrieved_at`. The
`assumptions` array is rendered verbatim in the UI — no silent defaults.

#### `POST /v1/analyze` — the one the UI actually calls
Composite of tokenize + optimize + cost in a single round trip. Keeping the
three primitives public and separate is what makes the developer API sellable;
keeping this composite is what keeps the web app to one request per edit.

#### `POST /v1/batch` (V2) · `GET /v1/usage` (V2) · `GET /health`

### 2.3 Limits

`text` capped at 400 KB (return `text_too_large` above it). Anonymous: N
requests/min per IP, enforced in Redis. Keyed: per-plan quota. Cache TTL 24h on
`sha256(text)+model`; the cache is what makes the free tier survivable.

---

## 3. UI / UX

### 3.1 Layout

```
┌───────────────────────────────────────────────────────────────────────┐
│ TokenCut          Playground   Pricing   API Docs   Blog     [GitHub] │
├───────────────────────────────────────────────────────────────────────┤
│  ▸ STICKY METRICS BAR  (always visible, both panes scroll under it)   │
│   1,284 → 1,109 tokens    −13.6%    $42.18 saved / mo @ 30k calls     │
├──────────────────────────────┬────────────────────────────────────────┤
│ LEFT  (input, ~46%)          │ RIGHT  (analysis, ~54%)                │
│                              │                                        │
│ ┌──────────────────────────┐ │ ┌─[ Token Map | Optimized | Savings ]┐ │
│ │ Paste your prompt…       │ │ │                                    │ │
│ │                          │ │ │  TOKEN MAP                         │ │
│ │ CodeMirror 6             │ │ │  alternating-shade token spans,    │ │
│ │ mono, line numbers off   │ │ │  hover → token id + index          │ │
│ │                          │ │ │  gutter heat bar per paragraph     │ │
│ └──────────────────────────┘ │ │                                    │ │
│                              │ │  OPTIMIZED                         │ │
│ Models:                      │ │  side-by-side diff, additions and  │ │
│  [✓ GPT-4o] [✓ Claude Opus 5]│ │  deletions; per-rule toggle list   │ │
│  [✓ Gemini 2.5 Pro] [+ more] │ │  with each rule's token saving     │ │
│                              │ │           [ Copy optimized ]  ←★   │ │
│ Optimization profile:        │ │                                    │ │
│  ( ) Safe  (•) Balanced      │ │  SAVINGS                           │ │
│  ( ) Aggressive              │ │  calls/month  [ 30,000 ]           │ │
│                              │ │  output est.  [ 500 ] tokens       │ │
│ Your volume:                 │ │  ┌──────────────────────────────┐  │ │
│  calls/month [ 30,000 ]      │ │  │ model  before  after  saved  │  │ │
│                              │ │  └──────────────────────────────┘  │ │
│ ⓘ OpenAI counts run locally. │ │  "Prices as of <date> · sources"   │ │
│   Claude/Gemini counts are   │ │                                    │ │
│   sent to their count APIs.  │ └────────────────────────────────────┘ │
├──────────────────────────────┴────────────────────────────────────────┤
│  ── ad slot: below the fold, full width, clearly separated ──         │
└───────────────────────────────────────────────────────────────────────┘
```

Mobile: panes stack, right pane becomes a bottom sheet, metrics bar pins to the
top. The metrics bar is the thing people screenshot — it must survive at 375px.

### 3.2 Interaction rules

- **No signup, no modal, no cookie wall on the playground.** Every gate on the
  first interaction costs a large fraction of the funnel.
- Typing → local OpenAI count updates on every keystroke (Web Worker, no jank).
- Typing → 400 ms debounce → single `/v1/analyze` call for the rest.
- While server counts are pending: show the calibrated estimate greyed with
  `≈`, then swap to the exact number. **Never** animate a number that is a
  guess as though it were measured.
- `Copy optimized` is the primary conversion event. Instrument it.
- Empty state ships with 3 one-click sample prompts (a bloated JSON payload,
  a verbose system prompt, a RAG context blob) — each chosen to produce a
  visibly large saving.

### 3.3 The token-highlight rendering problem

Naive `<span>`-per-token dies at scale: a 10k-token prompt is 10k DOM nodes,
re-created on every keystroke.

- Use **CodeMirror 6 decorations** rather than a hand-rolled
  transparent-textarea overlay. CM6 virtualizes the viewport and only decorates
  visible ranges.
- Cycle **4 low-saturation background shades** so adjacent tokens are
  distinguishable. Not a rainbow — a rainbow is unreadable and fails contrast.
  Verify contrast in both themes.
- Hard-cap decoration at the first ~5,000 tokens; beyond that, fall back to the
  paragraph heat bar with an explicit "highlighting first 5,000 tokens" note.

### 3.4 The honesty problem in the Token Map (important)

Exact per-token *offsets* exist only for the OpenAI family — `tiktoken` decodes
to byte strings, so boundaries are recoverable. Anthropic's `count_tokens`
returns **a total and nothing else**. There is no way to draw a true Claude
token map.

Two of the three obvious options are dishonest:

- ❌ Show OpenAI boundaries and label them "Claude". Wrong, and the sort of
  wrong a technical audience will catch and post about.
- ❌ Silently show an approximation with no marker.
- ✅ **Segment-level attribution.** Split the text into paragraphs/blocks,
  count each block against the real Claude endpoint (batched, cached), and
  render a per-block heat bar with exact per-block counts. Token-level
  boundaries stay OpenAI-only and are labelled as such.

Caveat to surface in the UI: per-segment counts will not sum exactly to the
whole-text count (boundary effects, message framing overhead). Normalize the
displayed shares to the exact total and note it.

### 3.5 Visual system

Dark-first (developer audience defaults to dark), light theme fully supported.
Inter for UI, JetBrains Mono for all text/code surfaces. One accent colour.
Numbers in the metrics bar in tabular-lining figures so they don't jitter as
they change. Motion limited to number transitions; respect
`prefers-reduced-motion`.

---

## 4. Repository layout (proposed, for Phase 3)

```
tokencut/
├─ apps/web/                 Next.js 15 · App Router
│  ├─ app/(marketing)/       landing, /tools/*, /blog/* — static, SEO
│  ├─ app/playground/        the tool
│  ├─ components/            editor, token-map, diff, metrics, savings
│  ├─ lib/tokenizer/         WASM tiktoken worker + estimator
│  └─ lib/api/               typed client generated from the OpenAPI schema
├─ apps/api/                 FastAPI
│  ├─ main.py  routers/  services/  adapters/  infra/  models/
│  └─ tests/
├─ data/pricing/catalog.json versioned pricing (see Phase 2 §3)
└─ docs/
```

Monorepo, but deployed as two independent units (Vercel / Render). The typed
API client is generated from FastAPI's OpenAPI schema — no hand-written
duplicate types.

---

## 5. Open decisions blocking Phase 3

1. Final name + domain.
2. Backend host: Render free (sleeps) vs Fly/Railway (doesn't) — affects §1.3.
3. Does V1 ship Gemini, or OpenAI + Anthropic only? Gemini adds a second keyed
   dependency for a smaller share of the target audience.
4. BYO-key mode in V1? It removes the rate-limit ceiling and is a strong
   privacy story, but adds a key-handling surface.
5. Whether to run any LLM-assisted (Tier 3) compression in V1 — it has real
   per-request cost and cannot be free.
