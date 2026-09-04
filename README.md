# TokenCut

**Track and optimize AI token usage.** Count tokens accurately across OpenAI,
Anthropic and Google models, see which parts of a prompt cost the most, and cut
the waste — with every number labelled by how it was measured.

> Not affiliated with OpenAI, Anthropic or Google. Model names are the
> trademarks of their respective owners.

---

## Why another token counter

Most free token counters run `tiktoken` — OpenAI's tokenizer — against every
model and call it a day. That undercounts Claude by roughly 15–20% on ordinary
prose and by considerably more on code and non-English text. A cost calculator
built on that is wrong in the direction that flatters it.

TokenCut counts each model with its own tokenizer, and when it can't, it says
so instead of guessing.

### The honesty contract

Two rules run through the entire codebase, enforced by types and tests rather
than by discipline:

**1. No bare numbers.** Every token count carries a `source`:

| `source` | Meaning | UI shows |
|---|---|---|
| `exact_local` | offline tokenizer (`tiktoken`), exact | `1,284` |
| `exact_api` | the provider's own counting endpoint, exact | `1,284` |
| `cached` | previously measured, identical text | `1,284` |
| `estimated` | heuristic ratio | `≈1,402` + hover caveat |
| `unavailable` | no count obtainable | `—` |

Exactly one component in the frontend renders a token count, and every caller
must hand it the `source` alongside the number.

**2. No unstated assumptions.** Every cost response carries an `assumptions[]`
list, rendered verbatim. A model with no verified published price returns
`available: false` and is excluded from totals — never defaulted to `$0`.

Prices live only in [`data/pricing/catalog.json`](data/pricing/catalog.json),
each row with a `source_url` and `retrieved_at`. No price is hardcoded anywhere
in application code.

---

## Quickstart

Two services. Start the API first, or don't — the frontend degrades rather than
breaking (see [Degradation](#degradation)).

```bash
# backend — http://localhost:8000
cd apps/api
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn main:app --reload
```

```bash
# frontend — http://localhost:3000
cd apps/web
npm install
npm run dev
```

No `.env` is needed for local development. Provider API keys are optional:
without them, OpenAI counts still work (they run in your browser) and Claude
counts fall back to a clearly-marked estimate.

| | |
|---|---|
| Playground | http://localhost:3000/playground |
| Interactive API docs | http://localhost:8000/docs |
| Health + provider status | http://localhost:8000/v1/health |

### Tests

```bash
cd apps/api && .venv/bin/python -m pytest        # 147 tests
cd apps/api && .venv/bin/python -m ruff check app main.py tests scripts
cd apps/web && npm test && npm run typecheck && npm run lint
```

---

## What it does

Paste a prompt and it:

- **counts** it against each selected model with that model's own tokenizer;
- **maps** it — alternating shading over each individual token (OpenAI family
  only; see below);
- **optimizes** it — lossless cleanups applied, behaviour-affecting changes
  offered but never applied;
- **prices** it — per-model input-side savings at your stated call volume.

### Verified example

The bundled *Bloated JSON payload* sample — 40 pretty-printed records:

| | Before | After | |
|---|---|---|---|
| GPT-4o | 2,453 | **964** | `exact_local` |
| Claude Opus 5 | ≈3,753 | ≈1,475 | `estimated` |
| **Reduction** | | **60.7%** | |
| Saved / month @ 30k calls | | **$111.67** (GPT-4o) · **$341.70** (Opus 5) | |

One rule accounts for all of it: an array of uniform objects repeats every key
on every row, and a Markdown table states each key once.

Eleven more validated cases — including the ones where it correctly saves
*nothing* — are in [`docs/03-validation-prompts.md`](docs/03-validation-prompts.md).
Reproduce them with `apps/api/scripts/validate_prompts.py`.

---

## Things that will surprise you

**Only OpenAI gets a token map.** Its tokenizer is published and reverses
cleanly to bytes, so exact per-token character boundaries are recoverable.
Anthropic's and Google's counting endpoints return a total and nothing else.
Relabelling OpenAI's boundaries as Claude's would be a guess dressed as data,
so the map is absent for those models and the UI says why.

**Shorter is not always fewer tokens.** Removing `"Please "` forces
`" summarize"` (one token) to become `"Summarize"` (several). Every rule's
saving is measured by re-tokenizing, and any rule that would *increase* the
count is rolled back with an explanation.

**Compressing a prompt does not reduce output cost.** Input and output are
billed separately; the response length is unchanged. The saving reported is
input-side only, and the assumptions list says so. Any calculator showing a
shrinking "total cost" while holding output constant is taking credit for
nothing.

**Sometimes the right answer is "don't compress this".** Handed a large stable
system prefix, TokenCut recommends prompt caching instead — cached input bills
at a fraction of base rate, and editing a cached prefix invalidates it, so
compressing a stable prompt can cost more on the next call than it saves.

**Your code is protected.** Fenced code, JSON string literals, URLs, template
variables and email addresses are classified before any rule runs, and no
cleanup may touch them — or the whitespace immediately around them.

---

## Architecture

```
apps/web/     Next.js 16 · React 19 · Tailwind 4 · TypeScript strict
apps/api/     FastAPI · Python 3.12 · tiktoken / anthropic / google-genai
data/         pricing catalog + estimator calibration (the only sources of truth)
docs/         design, algorithms, validation suite
```

The split is not stylistic. Two of the three providers require a **secret API
key** to count tokens at all, and a secret cannot live in a browser bundle.
OpenAI's tokenizer is published, so that path runs client-side in a Web Worker
— instant, free, and the text never leaves the device.

```
browser ──► Web Worker (js-tiktoken)   OpenAI counts, instant, exact
        └─► /api/analyze (BFF proxy) ──► FastAPI ──► provider count endpoints
```

**Why the BFF proxy** rather than calling Python from the browser: the CSP stays
at `connect-src 'self'`, there is no CORS in the browser at all, the backend
address never reaches the client bundle, and there is exactly one validation
boundary. It forwards the real client IP so per-IP rate limiting still works.

**Security:** nonce-based CSP with `strict-dynamic` and no `unsafe-inline` for
script, HSTS, `nosniff`, `Referrer-Policy`, `X-Frame-Options`,
`Permissions-Policy`, COOP/CORP, strict Zod validation at the proxy, and
`no-store` on every API response. Prompt text is never logged — logs carry a
truncated content hash, byte length, and token count.

Full detail in [`apps/web/README.md`](apps/web/README.md) and
[`apps/api/README.md`](apps/api/README.md).

### Degradation

Designed to stay useful when the backend is cold, throttled, or absent — which
a free-tier host will be:

- OpenAI counts need no server and no key, ever.
- The model catalog falls back to a built-in list, so `next build` succeeds and
  pages render with the API down. **Fallback entries carry no prices** —
  inventing prices to fill a fallback is exactly the failure this project
  exists to avoid.
- Anthropic rate-limited or unreachable → a labelled estimate, not a 502.
- Redis absent → in-process cache. A rule that throws → skipped, with a
  warning in the response.

### Privacy

**Local-only mode** makes "your prompt never leaves this browser" literally
true: no request is made at all, and any existing server results are dropped
from state immediately.

With it off, prompt text does transit the backend — Claude and Gemini have no
public offline tokenizer, so an exact count requires it. That is stated in the
UI next to the toggle, not buried in a policy page.

---

## Status

V1 complete: 147 backend tests, 10 frontend tests, typecheck / lint / build
clean.

Known gaps, all deliberate rather than forgotten:

- **Claude and Gemini counts are uncalibrated estimates** until an API key is
  configured. The shipped ratio for the Claude 4.7+ generation is *derived*
  from two published figures, not measured. Fix with
  `apps/api/scripts/calibrate_estimator.py --write` once a key exists.
- **Prices go stale in 30 days** by policy. The staleness check exists and
  warns in every response, but is not yet wired to a CI workflow.
- **Nonce CSP forces per-request rendering.** Harmless for SEO — crawlers get
  complete HTML — but it costs CDN HTML caching. The trade-off and the two-line
  flip are documented in `apps/web/README.md`.
- Batch CSV processing, user accounts, and the developer API tier are V2.

Not deployed yet.
