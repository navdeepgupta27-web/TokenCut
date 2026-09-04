import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Nonce-based Content-Security-Policy.
 *
 * Lives in `proxy.ts`: Next 16 renamed the `middleware` file convention to
 * `proxy`. Same execution model, same matcher semantics.
 *
 * Why a nonce rather than the usual `'unsafe-inline'` escape hatch: Next.js
 * emits inline bootstrap scripts, so a script-src that omits `'unsafe-inline'`
 * breaks hydration. The lazy fix is to allow all inline script, which defeats
 * the point of having a CSP at all. The correct fix is a per-response nonce
 * that Next attaches to its own scripts automatically once it sees one in the
 * header — which is what this middleware does.
 *
 * `'strict-dynamic'` then lets those nonced scripts load the chunks they need
 * without us maintaining a host allowlist.
 */

function buildCsp(nonce: string, isDev: boolean): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],

    "script-src": [
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      // React Fast Refresh compiles with eval in development only. Shipping
      // this to production would undo most of the CSP's value.
      ...(isDev ? ["'unsafe-eval'"] : []),
    ],

    // CodeMirror injects its theme as inline <style> at runtime, and Next
    // inlines critical CSS. Nonce-ing those is not currently possible, so
    // 'unsafe-inline' stays here.
    //
    // This is a deliberate, bounded trade: inline STYLE cannot execute code.
    // The realistic risk is CSS-based exfiltration of already-visible content,
    // which is a far smaller problem than inline SCRIPT would be.
    "style-src": ["'self'", "'unsafe-inline'"],

    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],

    // Same-origin only. The browser never talks to the Python API directly —
    // everything goes through the BFF at /api/*. That is what lets this stay
    // locked to 'self' instead of allowlisting a backend host, and it means a
    // rotated backend URL is not a CSP change.
    "connect-src": ["'self'", ...(isDev ? ["ws:", "wss:"] : [])],

    // The local tokenizer runs in a Web Worker built by the bundler.
    "worker-src": ["'self'", "blob:"],

    "manifest-src": ["'self'"],
    "form-action": ["'self'"],
    "base-uri": ["'self'"],
    "frame-ancestors": ["'none'"],
    "frame-src": ["'none'"],
    "object-src": ["'none'"],
  };

  const csp = Object.entries(directives)
    .map(([key, values]) => `${key} ${values.join(" ")}`)
    .join("; ");

  // upgrade-insecure-requests is meaningless (and noisy) on http://localhost.
  return isDev ? csp : `${csp}; upgrade-insecure-requests`;
}

export function proxy(request: NextRequest) {
  const isDev = process.env.NODE_ENV !== "production";

  // crypto.randomUUID is available in the Edge runtime; base64 keeps the
  // header compact and matches the nonce grammar.
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce, isDev);

  // Next reads the nonce off the *request* headers to stamp its own <script>
  // tags, so it has to be set on the forwarded request, not just the response.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Skip static assets and image optimisation: they need no nonce, and running
  // middleware on them is pure latency on every page load.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff|woff2)$).*)",
  ],
};
