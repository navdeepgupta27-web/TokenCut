# TokenCut API

FastAPI backend for token counting, prompt optimization, and cost analysis.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m uvicorn main:app --reload
```

`http://localhost:8000/docs` for the interactive schema.
No API keys are required to start — see *Degradation* below.

```bash
.venv/bin/python -m pytest        # 106 tests
.venv/bin/python -m ruff check app main.py tests
```

## The contract

Two rules run through every endpoint, and most of the code exists to keep them:

**1. No bare numbers.** Every token count carries a `source`:

| `source` | Meaning | UI must show |
|---|---|---|
| `exact_local` | tiktoken, offline, exact | the number |
| `exact_api` | provider `count_tokens`, exact | the number |
| `cached` | previously exact | the number |
| `estimated` | heuristic ratio | `≈` prefix |
| `unavailable` | no key **and** no sourced ratio | `—` |

`estimated` also carries `calibrated` and `estimate_error_p90`. `calibrated: false`
means the ratio is a documented heuristic, not a measured fit.

**2. No unstated assumptions.** Every cost response carries `assumptions[]`,
meant to be rendered verbatim. A model with no verified price comes back
`available: false` and is excluded from totals — never defaulted to zero.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/health` | Per-provider status. Also the frontend's warm-up ping. |
| `GET` | `/v1/models` | Counting availability and pricing availability, reported **separately**. |
| `GET` | `/v1/rules` | Rule catalog — the frontend renders toggles from this, so adding a rule needs no frontend change. |
| `POST` | `/v1/tokenize` | Counts, optional offsets, optional segment attribution. |
| `POST` | `/v1/optimize` | `applied` (lossless, done) vs `suggested` (risky, offered). |
| `POST` | `/v1/cost` | Per-model cost matrix + assumptions. |
| `POST` | `/v1/analyze` | All of the above in one round trip. What the web app calls. |

## Degradation

The service boots with **no credentials** and stays useful:

- OpenAI counting is offline (`tiktoken`) — needs no key, ever.
- Claude/Gemini without a key → `estimated` (Claude) or `unavailable` (Gemini,
  which has no sourced ratio).
- Anthropic rate-limited or unreachable → falls back to `estimated`, not a 502.
- Redis absent → in-process TTL cache.
- A rule that throws → skipped, with a warning in the response.

This is deliberate: the frontend must survive a cold, throttled, or missing
backend, because a free-tier host will produce all three.

## Things that will surprise you

**Only OpenAI has token offsets.** Anthropic's `count_tokens` returns a total
and nothing else, so `supports_offsets` is `False` for Claude and must stay
that way. Use segment attribution (`include_segments`) for those models.

**Shorter is not always fewer tokens.** Removing `"Please "` forces
`" summarize"` (one token) to become `"Summarize"` (several). The pipeline
measures every rule by re-tokenizing and rolls back any rule that would *add*
tokens, with a warning explaining why.

**Savings are measured with a local tokenizer.** Per-rule attribution
re-tokenizes once per rule. Free offline; unaffordable against a keyed
endpoint. `measure_with` is forced to an OpenAI model and a warning says so.
Exact per-model totals still come from `/v1/tokenize`.

**`count_tokens` counts a whole request.** Anthropic's figure includes message
framing; tiktoken's does not. `includes_message_overhead` marks the difference
— do not compare the two numbers like-for-like.

**No prompt text is ever logged.** Logs carry `sha256(text)[:16]`, byte length,
and token count. If you add logging, use
`app.infra.logging.text_fingerprint()`.

## Pricing

`data/pricing/catalog.json` is the only source of prices; no module contains a
hardcoded one. Every entry needs `source_url` and `retrieved_at`; entries older
than 30 days are flagged stale in responses.

Anthropic rows are seeded from the Anthropic API reference (cached 2026-06-24)
and **still need re-verification**. **OpenAI and Google rows are deliberately
`null`** — they get populated by reading the official pricing pages, not from
memory. A wrong number in a cost calculator is unrecoverable for credibility.

## Layout

```
main.py                    app wiring, CORS, request-id middleware
app/config.py              all settings (nothing reads os.environ directly)
app/schemas.py             the public contract
app/errors.py              one error envelope for every failure
app/routers/               meta (health, models), analysis (the four endpoints)
app/services/tokenizer/    per-provider adapters + registry + estimator
app/services/optimizer/    segmentation, rule tiers 0-2, pipeline
app/services/cost.py       the cost equations
app/services/pricing.py    catalog loader + staleness
app/infra/                 cache, rate limit, structured logging
```

## Still to do

- Populate OpenAI/Google prices from source (blocks cost for those models).
- Calibrate the estimator (`docs/02-core-logic.md` §1.5) — the Claude ratio is
  currently an uncalibrated heuristic.
- Verify Gemini's SDK call shape, and whether a local tokenizer is available.
- `POST /v1/batch` (CSV) and `GET /v1/usage` — V2, with auth.
