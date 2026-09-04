# TokenCut Web

Next.js 16 (App Router) + React 19 + Tailwind 4 frontend.

## Run it

```bash
npm install
npm run dev          # http://localhost:3000
```

No `.env.local` is needed for local development — `API_BASE_URL` defaults to
`http://127.0.0.1:8000` and `NEXT_PUBLIC_SITE_URL` to `http://localhost:3000`.
Start the API first (`apps/api`), or don't: the page degrades rather than
breaking. See *Degradation* below.

```bash
npm run typecheck    # tsc --noEmit
npm test             # vitest — 10 reducer tests
npm run build
```

## Architecture

### The SSR/SEO split

The playground is a live editor. It cannot be usefully server-rendered, and
trying to rank it would produce a thin page. So the two concerns are split:

| Route | Rendering | Indexed | Client JS |
|---|---|---|---|
| `/` | Server Component | yes | none of its own |
| `/tools/[slug]` | Server Component, `generateStaticParams` | yes | none of its own |
| `/playground` | Server shell + client island | **no** (`noindex`) | CodeMirror + worker |
| `/api/analyze` | Route handler (BFF) | no | — |

The marketing and guide routes carry the SEO weight and ship no interactive
JavaScript. `/playground` is explicitly `noindex` and `Disallow`ed in
`robots.txt` — listing a noindex URL in a sitemap is a contradiction crawlers
flag, so it is absent from `sitemap.ts` too.

Content is in the server-rendered HTML before any JS runs — `<title>`,
`<meta description>`, canonical, `<h1>`, body copy, `FAQPage` and
`BreadcrumbList` JSON-LD. Verify with `curl -s localhost:3000/tools/claude-token-counter`.

### Layers

```
src/app/                routes; Server Components by default
src/app/api/analyze/    BFF proxy — the only browser-reachable API surface
src/components/ui/      stateless primitives
src/components/playground/  the client island
src/lib/api/            typed contract (types.ts) + server client (server.ts)
src/lib/playground/     pure reducer (state.ts) + effects (usePlayground.ts)
src/lib/tokenizer/      Web Worker + adapter
src/lib/seo/            JSON-LD builders
src/content/tools.ts    programmatic SEO page content
src/proxy.ts            nonce CSP (Next 16 renamed `middleware` -> `proxy`)
```

**Container/presentational.** `Playground.tsx` owns all state and renders no
data of its own; every pane is a pure function of props.

**Pure reducer + effectful hook.** `state.ts` has no side effects, which is why
its 10 tests run with no DOM, no network and no React. All fetching and worker
talk lives in `usePlayground.ts`.

**Adapter pattern for tokenizers**, mirroring the backend: the local worker and
the remote API sit behind one shape, so the two-tier counting below is a
strategy swap rather than branching logic scattered through components.

### Two-tier counting

```
keystroke ──► local worker (js-tiktoken)  OpenAI models only   -> instant, exact
          └─► 400ms debounce ──► POST /api/analyze             -> exact for all
```

The worker does **counts only, never offsets**. Reconstructing offsets needs
per-token *byte* decoding; `js-tiktoken` decodes to a JS string, so a token
ending mid-character returns a replacement char — decoding
`"Hello, world! Café 🎉"` one token at a time yields `" �" "�"`. Offsets built
from that would be silently misaligned on any emoji, CJK or Indic text. The
Python backend does it correctly in byte space, so the token map's offsets come
from the API. See the comment block in `count.worker.ts`.

### Why a BFF proxy instead of calling the API from the browser

- **CSP stays at `connect-src 'self'`** — no backend host to allowlist, and
  rotating the backend URL is not a CSP change.
- **No CORS in the browser at all** — the classic "works locally, fails
  deployed" failure cannot occur.
- **The backend address never reaches the client bundle** (`server-only` +
  no `NEXT_PUBLIC_` prefix), so it can sit on a private network.
- **One validation boundary** — a strict Zod schema; unknown fields are
  rejected, not forwarded.

It forwards the real client IP as `X-Forwarded-For`. Without that the backend
would see the serverless function's address and rate-limit every visitor as if
they were one client, silently destroying the shared provider quota protection.

## Security

| Control | Where |
|---|---|
| Nonce CSP, `strict-dynamic`, no `unsafe-inline` for script | `src/proxy.ts` |
| HSTS, nosniff, Referrer-Policy, X-Frame-Options, Permissions-Policy, COOP/CORP | `next.config.ts` |
| `no-store` + `Vary: *` on `/api/*` | `next.config.ts` |
| Strict input validation | `src/app/api/analyze/route.ts` |
| Env validation, server/public split | `src/lib/config.ts` |
| Escaped JSON-LD (only `dangerouslySetInnerHTML` in the app) | `src/lib/seo/jsonld.tsx` |

`style-src` keeps `'unsafe-inline'`. CodeMirror injects its theme as inline
`<style>` at runtime and Next inlines critical CSS; neither can currently be
nonced. This is a bounded trade — inline *style* cannot execute code — and it
is called out in `proxy.ts` rather than left as an unexplained hole.
`'unsafe-eval'` appears in development only, for React Fast Refresh.

### Known trade-off: nonce CSP forces dynamic rendering

A nonce must be unique per response, so any route carrying one must be rendered
per request. `headers()` in the root layout therefore makes `/` and
`/tools/[slug]` `ƒ (Dynamic)` in the build output rather than `○ (Static)`.

**This does not hurt SEO** — crawlers receive complete HTML either way, and the
expensive part (the model-catalog fetch) is still cached for an hour via
`revalidate`. What it costs is CDN HTML caching and some serverless compute.

To trade the other way — fully static HTML, weaker CSP — remove the `headers()`
call and the nonce from `src/app/layout.tsx` and change `script-src` in
`proxy.ts` to `'self' 'unsafe-inline'`. You cannot have both: static HTML is
generated once, a nonce changes every request, and `'strict-dynamic'` makes
`'unsafe-inline'` inert. Recommendation is to keep the nonce.

## Degradation

The page is designed to stay useful when the backend is cold, throttled, or
absent — which a free-tier host will be:

- OpenAI counts run in the browser and never need the server.
- `getModels()` falls back to a built-in catalog, so `next build` succeeds and
  the page renders with the API down. **Fallback entries carry no prices** —
  inventing prices to fill a fallback is exactly the failure this product
  exists to avoid.
- A failed analysis shows the error and a retry, and says local counts are
  unaffected.
- A dead Web Worker resolves to `null` and the debounced server count covers it.

## Privacy

`Local-only mode` makes "your prompt never leaves this browser" literally true:
no server request is made at all, and any existing server results are dropped
from state immediately rather than left on screen.

With it off, prompt text does transit the BFF — Claude and Gemini have no
public offline tokenizer, so an exact count requires it. That is stated in the
UI next to the toggle, not buried in a policy page. Nothing logs prompt text.

## The honesty contract in the UI

One component renders token counts: `TokenCount.tsx`. Every caller must hand it
a `source` alongside the number, so "never show an estimate as though it were
measured" is enforced by the type system rather than by discipline.

```
exact_local / exact_api / cached  ->  1,284
estimated                         ->  ≈1,402  + "est" marker + hover caveat
unavailable                       ->  —
```

An uncalibrated estimate (`calibrated: false`) gets deliberately softer wording
than one with a measured error band. `MetricsBar` shows "price not verified"
where a model has no sourced price, never `$0.00`.

## Still to do

- OG images (`opengraph-image.tsx`) — currently text-only cards.
- A theme toggle. Tokens and the pre-paint script are in place; the control is
  not built, so the OS preference decides.
- Component/interaction tests. The reducer is covered; the panes are not.
- Generate `src/lib/api/types.ts` from the API's `/openapi.json` at build time.
  It is hand-maintained, so the two contracts can drift.
