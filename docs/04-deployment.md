# TokenCut — Deployment

Two services, two hosts.

```
apps/web  ──►  Vercel          (Next.js, native fit)
apps/api  ──►  Render / Fly    (long-running ASGI)
```

## Why the API is not on Vercel

Vercel *can* run Python, but this backend is a poor fit for serverless:

- **Startup cost repeats on every cold start.** The service pre-warms
  tiktoken's multi-megabyte BPE tables in its lifespan hook. Amortised once
  over a long-running process; paid per invocation on serverless.
- **The in-process cache stops working.** Token counts are cached to avoid
  re-hitting Anthropic's rate-limited endpoint. Across serverless instances
  each one keeps its own cache, multiplying upstream calls.
- **Bundle weight.** `tiktoken` plus the Anthropic and Google SDKs is a large
  dependency tree to ship into a function.

Render's free tier sleeps, which is its own problem — see
[The sleeping-backend problem](#the-sleeping-backend-problem). Fly.io and
Railway do not sleep and are the better choice once traffic justifies paying.

---

## Step 1 — Deploy the frontend to Vercel

**Do this first.** The frontend is designed to work standalone: OpenAI counts
run in the browser, and `getModels()` falls back to a built-in catalog when the
API is unreachable. You get a working deployment before the backend exists.

1. https://vercel.com/new → **Import Git Repository** → pick
   `navdeepgupta27-web/TokenCut`
2. **Set Root Directory to `apps/web`.** This is the one setting that matters
   and the one most often missed — without it Vercel builds the repo root,
   finds no `package.json`, and fails.
3. Framework preset should auto-detect **Next.js**. Leave build and output
   settings alone; the defaults are correct.
4. Add environment variables (Settings → Environment Variables):

   | Name | Value | Notes |
   |---|---|---|
   | `NEXT_PUBLIC_SITE_URL` | `https://<your-app>.vercel.app` | **Required.** Drives canonical URLs, OG tags, sitemap, robots. Wrong value = SEO metadata pointing at localhost. |
   | `API_BASE_URL` | *(add in step 2)* | Server-only. No `NEXT_PUBLIC_` prefix, so it never reaches the browser bundle. |
   | `API_INTERNAL_TOKEN` | *(add in step 2)* | Must match the backend exactly. |
   | `API_TIMEOUT_MS` | `60000` | Default is 15s — too short for a cold free-tier backend. |

5. **Deploy.**

Verify:

```bash
curl -s https://<your-app>.vercel.app/ -o /dev/null -w "%{http_code}\n"
curl -sI https://<your-app>.vercel.app/ | grep -i content-security-policy
curl -s https://<your-app>.vercel.app/robots.txt
```

The CSP header should contain `'nonce-…'` and `'strict-dynamic'`, and **must
not** contain `'unsafe-eval'` — that appears in development only. If you see
it in production, `NODE_ENV` is wrong.

At this point `/playground` gives exact GPT-4o counts with no backend at all.
Claude and Gemini show `≈` estimates, and the Savings tab shows no dollar
figures because the model catalog fallback carries no prices — by design.

### After the first deploy

Set `NEXT_PUBLIC_SITE_URL` to your **real** domain once you attach one, and
redeploy. It is baked in at build time, so changing it needs a rebuild, not
just a restart.

---

## Step 2 — Deploy the API to Render

[`render.yaml`](../render.yaml) is a blueprint, so this is mostly clicking.

1. https://dashboard.render.com → **New** → **Blueprint** → point at the repo.
   Render reads `render.yaml` and proposes a `tokencut-api` web service.
2. Fill the values marked `sync: false`:

   | Name | Value |
   |---|---|
   | `CORS_ORIGINS` | `https://<your-app>.vercel.app` |
   | `ANTHROPIC_API_KEY` | optional — enables exact Claude counts |
   | `GOOGLE_API_KEY` | optional — enables exact Gemini counts |
   | `REDIS_URL` | optional — see [Scaling](#scaling) |

   `API_INTERNAL_TOKEN` is generated automatically. **Copy it.**
3. Deploy, then verify:

   ```bash
   curl -s https://<your-api>.onrender.com/v1/health | python3 -m json.tool
   ```

   `providers.openai.available` should be `true`. Anthropic and Google report
   `false` with a reason unless you set their keys — that is not an error.

4. Confirm the gate is live. This must return **401**:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X POST \
     https://<your-api>.onrender.com/v1/tokenize \
     -H 'Content-Type: application/json' \
     -d '{"text":"hi","models":["gpt-4o"]}'
   ```

   If it returns 200, `API_INTERNAL_TOKEN` is not set and **your backend is an
   open proxy to your provider quota.** Fix before going further.

5. Back in Vercel, set `API_BASE_URL` to `https://<your-api>.onrender.com` and
   `API_INTERNAL_TOKEN` to the value from step 2, then **redeploy**.

Verify the full chain through the browser-facing proxy:

```bash
curl -s -X POST https://<your-app>.vercel.app/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"Please  summarise  this.","models":["gpt-4o","claude-opus-5"],
       "profile":"balanced","rules":{},"include_offsets":false,
       "include_segments":false,"tokens_out":400,"calls_per_month":30000,
       "cache_read_fraction":0,"cache_write_fraction":0,"batch_fraction":0}'
```

Note there is **no CORS configuration to get right on the browser side** — the
browser only ever calls `/api/*` on its own origin. That is the main reason the
BFF proxy exists.

---

## The sleeping-backend problem

Render's free tier spins down after ~15 minutes idle, and the cold start runs
into tens of seconds. For a tool judged in the first three seconds that is
fatal — so the design works around it:

1. **The critical path needs no backend.** OpenAI counts are computed in the
   browser. A visitor gets exact numbers and a token map instantly regardless.
2. **A warm-up ping fires on page mount.** `/api/health` is called as soon as
   the playground mounts, so the wake-up starts while the visitor is reading
   rather than on their first keystroke.
3. **`API_TIMEOUT_MS=60000`** so a cold start does not surface as an error.
4. **A failed analysis degrades**, showing a retry and stating that local
   counts are unaffected.

If that is still not good enough — and for a public launch it probably is not —
the options in order of cost:

- An external cron pinging `/v1/health` every 10 minutes. Cheap, slightly
  against the spirit of a free tier.
- **Fly.io or Railway**, which do not sleep. This is the real answer.
- Render's paid tier.

---

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push
and PR, plus weekly:

| Job | What it guards |
|---|---|
| `api` | ruff + 157 pytest tests |
| `web` | typecheck, eslint, vitest, and a **build with no API reachable** — proving the catalog fallback works so a sleeping backend cannot break a deploy |
| `pricing-freshness` | **fails the build** when any price is older than 30 days or lacks a `source_url`/`retrieved_at` |

The weekly schedule matters: prices rot while nobody is committing. Note the
gate is deliberately un-satisfiable by bumping the date — the point is to
re-read the provider's page and re-verify the figure.

---

## Scaling

**Add Redis before running more than one API instance.** Without `REDIS_URL`
the service uses an in-process cache, which is correct for one instance and
wrong the moment you scale out: each instance keeps its own cache and the
number of calls to Anthropic's rate-limited endpoint multiplies by your
instance count. Upstash's free tier is enough.

Rate limiting has the same property — it is a per-instance fixed window until
Redis is present.

---

## Deployment checklist

- [ ] Vercel **Root Directory** is `apps/web`
- [ ] `NEXT_PUBLIC_SITE_URL` is the real origin (rebuild after changing)
- [ ] `API_BASE_URL` set, with **no** `NEXT_PUBLIC_` prefix
- [ ] `API_INTERNAL_TOKEN` identical in both services
- [ ] Backend returns **401** without that token
- [ ] `API_TIMEOUT_MS` raised above the backend's cold-start time
- [ ] `CORS_ORIGINS` on the backend lists the real Vercel origin
- [ ] Production CSP contains a nonce and **no** `'unsafe-eval'`
- [ ] `/robots.txt` disallows `/api/` and `/playground`
- [ ] `/sitemap.xml` lists `/` and the four `/tools/*` pages
- [ ] Redis configured **if** more than one API instance
- [ ] Provider keys set, or accept that Claude/Gemini show `≈` estimates

## Not done yet

- **No custom domain.** `NEXT_PUBLIC_SITE_URL` must be updated and the app
  rebuilt when one is attached.
- **No error tracking.** `app/error.tsx` logs a digest to the console; wire it
  to a real reporter. Never include prompt text.
- **Claude/Gemini counts are uncalibrated estimates** until keys are set and
  `scripts/calibrate_estimator.py --write` has been run against a real key.
