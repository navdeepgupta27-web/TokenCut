import type { NextConfig } from "next";

/**
 * Security headers that do NOT depend on a per-request nonce.
 *
 * The Content-Security-Policy is deliberately absent from this list — it needs
 * a fresh nonce per response, so it is set in `src/middleware.ts`. Everything
 * static lives here, where it is applied by the edge before any React runs.
 */
const securityHeaders = [
  // Force HTTPS for two years, including subdomains, and allow preloading.
  // Harmless on localhost (browsers ignore HSTS on http://).
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  // Stop the browser from MIME-sniffing a response away from its declared type.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Send only the origin cross-site: prompt text must never leak via a Referer
  // header, and paths on this site can carry no user content anyway.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Belt-and-braces with CSP frame-ancestors, for older browsers.
  { key: "X-Frame-Options", value: "DENY" },
  // Deny every powerful API we do not use. A text tool needs none of them.
  {
    key: "Permissions-Policy",
    value: [
      "camera=()",
      "microphone=()",
      "geolocation=()",
      "payment=()",
      "usb=()",
      "magnetometer=()",
      "gyroscope=()",
      "accelerometer=()",
      "interest-cohort=()",
    ].join(", "),
  },
  // Process isolation: blocks cross-origin windows from holding a reference to
  // ours, and cross-origin reads of our resources.
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  // Legacy header, still honoured by some crawlers and proxies.
  { key: "X-DNS-Prefetch-Control", value: "off" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Never ship the framework's own version string to attackers for free.
  poweredByHeader: false,

  // Fail the production build on a type error rather than shipping it.
  // (Next 16 dropped the `eslint` config key; linting runs via `npm run lint`
  // and in CI, not as part of `next build`.)
  typescript: { ignoreBuildErrors: false },

  experimental: {
    // CodeMirror is a large, tree-shaking-hostile dependency graph; this keeps
    // the playground chunk from dragging every module into the entry bundle.
    optimizePackageImports: [
      "@codemirror/state",
      "@codemirror/view",
      "@codemirror/language",
      "@codemirror/commands",
    ],
  },

  async headers() {
    return [
      { source: "/(.*)", headers: securityHeaders },
      {
        // The BFF proxy must never be cached by a CDN: bodies are user prompts,
        // and a shared cache keyed on URL alone would serve one user's analysis
        // to another.
        source: "/api/(.*)",
        headers: [
          { key: "Cache-Control", value: "no-store, no-cache, must-revalidate" },
          { key: "Vary", value: "*" },
        ],
      },
    ];
  },
};

export default nextConfig;
