# TokenCut — Validation Prompts

Use-case validation for the V1 build. Every number below was produced by
running the prompt through the live stack, not estimated.

Reproduce the whole suite:

```bash
# terminal 1
cd apps/api && .venv/bin/python -m uvicorn main:app --port 8000

# terminal 2
cd apps/api && .venv/bin/python scripts/validate_prompts.py
```

Measured `2026-09-04`, no provider API keys configured — which is why every
Claude figure below reads `estimated`. With `ANTHROPIC_API_KEY` set they become
`exact_api` and the numbers will shift; the *ratios* between models will change
most, because the shipped estimate ratio is derived rather than measured.

Volume assumption throughout: **30,000 calls/month, 400 output tokens**.
Prices per `data/pricing/catalog.json` (official pages, retrieved 2026-09-04).

---

## Short prompts

Short prompts are where the *honesty* behaviours are visible, because there is
almost nothing to save. A tool that reports big wins here is lying.

### S1 — Politeness that costs more to remove

```
Please summarize this document carefully.
```

| | |
|---|---|
| GPT-4o | 6 → 6 tokens (`exact_local`) |
| Claude Opus 5 | ≈9 → ≈9 tokens (`estimated`, uncalibrated) |
| Applied | nothing |

> ⚠ *'Politeness scaffolding' was skipped: applying it here would ADD 1 token(s)
> rather than save any. Shorter text does not always mean fewer tokens.*

**What it validates.** The measure-then-rollback guard. Removing `"Please "`
forces `" summarize"` (one token) to become `"Summarize"` (several). The engine
re-tokenizes, sees the count go up, refuses, and explains. This is the single
best demonstration that savings are measured rather than assumed.

### S2 — Smart quotes from a word processor

```
The report said “operational efficiency” improved — by 14% — year‑over‑year… driven by automation.
```

| | |
|---|---|
| GPT-4o | 25 → 25 tokens |
| Applied | `normalize_unicode` ×5, **0 tokens saved** |

**What it validates.** Rules fire and change the text without inventing a
saving. The normalisation is still correct and worth doing (ASCII is safer
downstream), but on this string o200k_base happens to cost the same either way,
so the report says 0. Compare with L3, where the same rule on a larger document
saves 3.

### S3 — Tiny JSON, table conversion correctly declined

```
Rank these: [{"id":1,"n":"Ada"},{"id":2,"n":"Grace"}]
```

| | |
|---|---|
| GPT-4o | 21 → 21 tokens |
| Applied | `trim_trailing_whitespace` ×1 (0 saved) |
| **Not** applied | `json_to_markdown_table` |

**What it validates.** The guardrail on the biggest rule. Two rows of two keys
produce a table that is *longer* than the JSON, so the rule declines. It only
fires when it actually wins — contrast L1.

### S4 — Duplicated constraint and hedge stacking

```
Answer very carefully and thoroughly and precisely.
Do not use markdown.
Do not use markdown.
```

| | |
|---|---|
| GPT-4o | 18 → 18 tokens |
| Applied | nothing |
| Suggested | `flag_hedge_stacking` −5 ×2, `flag_duplicate_constraints` −5 ×1 |

**What it validates.** A verbatim duplicated instruction and a triple adverb
chain are both detected and both left alone. 10 of 18 tokens are removable and
the tool will not touch them, because either could be deliberate reinforcement.

### S5 — Base64 blob

```
Describe this image: AAAA…(320 chars)
```

| | |
|---|---|
| GPT-4o | 46 → 44 tokens |
| Suggested | `flag_base64` — **advice, no transform** |

> *Base64 data tokenizes extremely badly … There is no compression that fixes
> this. Send the file through the provider's file/vision API, or reference it by
> URL, instead of pasting it into the prompt.*

**What it validates.** The tool recommends not using it, rather than pretending
to compress something incompressible.

### S6 — Already-tight prompt

```
Classify the sentiment of the review below as positive, negative or neutral.
```

| | |
|---|---|
| GPT-4o | 15 → 15 tokens |
| Applied | nothing — *"already tight"* |

**What it validates.** An honest zero. No manufactured percentage.

---

## Long prompts

### L1 — Bloated JSON payload ⭐ the flagship case

40 pretty-printed customer records with a short instruction. 6,326 characters.

| | Before | After | |
|---|---|---|---|
| GPT-4o | 2,453 | **964** | `exact_local` |
| Claude Opus 5 | ≈3,753 | ≈1,475 | `estimated` |
| **Reduction** | | **60.7%** | |
| Saved / month | | **$111.67** (GPT-4o) · **$341.70** (Opus 5) | |

Applied: `json_to_markdown_table` −1,489 tokens (×1).
Suggested: `advise_prompt_caching`.

**What it validates.** The core value proposition, and the one number worth
putting on the landing page. An array of uniform objects repeats every key on
every row; a Markdown table states each key once. One rule accounts for the
entire 60.7%.

This is also the honest counterweight to S3: the same rule, opposite verdict,
decided by measurement.

### L2 — Verbose system prompt with every audit smell

872 characters of politeness, filler, a repeated persona, a duplicated
constraint, and stacked adverbs.

| | |
|---|---|
| GPT-4o | 174 → 174 tokens |
| **Applied** | **nothing** |
| Suggested | `flag_politeness` −14 ×3 · `flag_filler_openers` −31 ×7 · `flag_hedge_stacking` −7 ×2 · `flag_redundant_role` −22 ×2 · `flag_duplicate_constraints` −9 ×1 |

**What it validates.** The safety split, at its most counter-intuitive. **83 of
174 tokens — 48% — are removable, and the tool removes none of them.** Every
finding is behaviour-affecting, so all five are offered with a risk note and
default to off.

Expect this to be the case reviewers argue about. It is the intended behaviour:
a competitor that silently strips all five reports a 48% win and may have
changed what the prompt does.

### L3 — RAG context with whitespace rot

840 characters of multi-space alignment, smart quotes, and a preamble repeated
across documents.

| | Before | After |
|---|---|---|
| GPT-4o | 202 | **145** |
| Claude Opus 5 | ≈309 | ≈222 |
| **Reduction** | | **28.2%** |
| Saved / month | | $4.27 (GPT-4o) · $13.05 (Opus 5) |

Applied: `collapse_spaces` −54 ×54 · `normalize_unicode` −3 ×8 ·
`collapse_blank_lines` ×3.

**What it validates.** Tier 0 alone, entirely lossless, on realistic pasted
content. 28% for zero semantic risk. This is the tier that earns trust before
anyone touches a suggestion.

### L4 — Mixed content, aggressive profile ⭐ the safety case

Prose + a Python fence with deliberate internal double-spaces and a
space-significant string literal + a JSON config + a URL + `{{user_name}}` +
`${greeting}` + an email address. Run at **aggressive**, the most destructive
profile.

| | Before | After |
|---|---|---|
| GPT-4o | 182 | **157** |
| **Reduction** | | **13.7%** |

Applied: `collapse_spaces` −13 ×13 · `compact_json` −12 ×1.

Verified assertions on the output:

```
PASS  code body byte-identical           PASS  url separated
PASS  string literal spaces kept         PASS  template var separated
PASS  json compacted and valid           PASS  email separated
PASS  no 'athttps' gluing                PASS  no 'greet{{' gluing
```

**What it validates.** Protected regions hold under the most aggressive
setting: `total  =  sum(...)` keeps its double spaces, `'  three   spaces  '`
is byte-identical, the URL and both template variables are untouched, and the
JSON compacts while still parsing to the same value.

> **This case found a real bug.** The first run produced
> `Call the endpoint athttps://api.example.com/...` — the space before every
> protected region was being deleted, because `trim_trailing_whitespace`
> matched `[ \t]+\Z` against each span's *substring*, so `\Z` meant "end of
> this chunk" rather than end of document. Protected bytes were safe; the
> boundary was not. Fixed by matching the whole document and filtering by span
> (`find_in_allowed`), with parametrised boundary regressions over all three
> profiles and five protected kinds. Reduction improved from 12.1% to 13.7% as
> a side effect.

### L5 — Large stable system prefix ⭐ the anti-sales case

11,413 characters of repeated playbook instructions — a realistic bloated
system prompt.

| | |
|---|---|
| GPT-4o | 2,115 → **2,114** tokens |
| **Reduction** | **0.0%** |
| Suggested | `advise_prompt_caching` |

> *This prompt is large enough to be worth caching. If any of it is a stable
> prefix you resend on every call, caching it will almost certainly save more
> than compressing it … editing a cached prefix invalidates the cache, so
> compressing a stable system prompt can cost more on the next call than it
> saves. Compress the volatile tail; cache the stable head.*

**What it validates.** The most defensible behaviour in the product. Handed the
single largest prompt in the suite, the tool saves one token and tells the user
to use a provider feature instead. At Opus 5's published 0.1× cache-read
multiplier, caching this prefix is worth roughly 90% of its input cost —
orders of magnitude more than compression could deliver.

---

## Cases still to add before launch

- **Length-tiered pricing.** `gemini-2.5-pro` doubles above 200k input tokens,
  and `crossed_pricing_tier` reports when optimization drops under it. Covered
  by unit tests (`test_tiered_model_prices_each_side_at_its_own_band`) but not
  yet by an end-to-end prompt, because a >200k-token prompt makes the suite
  slow. Worth one before launch.
- **Exact Claude counts.** Every Claude figure here is an uncalibrated
  estimate. Re-run the suite with `ANTHROPIC_API_KEY` set and record the real
  ratios; then run `scripts/calibrate_estimator.py --write`.
- **CJK / Indic content.** The estimate ratio is known to be worst on
  non-Latin scripts and none of these prompts exercise it.
