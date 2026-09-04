import { z } from "zod";

/**
 * Environment access, validated once, in one place.
 *
 * Two rules this file exists to enforce:
 *
 * 1. **No component reads `process.env` directly.** An unvalidated env read is
 *    a runtime crash waiting for a deploy.
 * 2. **The backend URL is server-only.** It has no `NEXT_PUBLIC_` prefix, so it
 *    cannot reach the client bundle. The browser talks only to `/api/*` on this
 *    origin; the Python service is never addressed from a user's machine.
 */

const serverSchema = z.object({
  /** Internal address of the FastAPI service. Server-only. */
  API_BASE_URL: z.string().url().default("http://127.0.0.1:8000"),
  /** Upstream timeout for the BFF proxy, in ms. */
  API_TIMEOUT_MS: z.coerce.number().int().positive().default(15_000),
  /** Optional shared secret, if the backend is not on a private network. */
  API_INTERNAL_TOKEN: z.string().optional(),
});

const publicSchema = z.object({
  /** Canonical origin. Drives canonical URLs, sitemap, and OG tags. */
  NEXT_PUBLIC_SITE_URL: z.string().url().default("http://localhost:3000"),
});

/**
 * Server env. Calling this from a Client Component is a build error by
 * convention — keep the call inside route handlers and Server Components.
 */
export function serverEnv() {
  const parsed = serverSchema.safeParse({
    API_BASE_URL: process.env.API_BASE_URL,
    API_TIMEOUT_MS: process.env.API_TIMEOUT_MS,
    API_INTERNAL_TOKEN: process.env.API_INTERNAL_TOKEN,
  });

  if (!parsed.success) {
    // Fail loudly at boot rather than returning 500s once traffic arrives.
    throw new Error(
      `Invalid server environment: ${JSON.stringify(parsed.error.flatten().fieldErrors)}`,
    );
  }
  return parsed.data;
}

const publicParsed = publicSchema.safeParse({
  NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
});

if (!publicParsed.success) {
  throw new Error(
    `Invalid public environment: ${JSON.stringify(publicParsed.error.flatten().fieldErrors)}`,
  );
}

export const publicEnv = publicParsed.data;

export const SITE = {
  name: "TokenCut",
  url: publicEnv.NEXT_PUBLIC_SITE_URL.replace(/\/$/, ""),
  tagline: "Count tokens accurately. Cut your LLM bill honestly.",
  description:
    "Count tokens across OpenAI, Anthropic and Google models, see exactly which " +
    "parts of your prompt cost the most, and cut the waste — with every number " +
    "labelled by how it was measured.",
} as const;

/** Client-side limits, mirroring the API so the UI can pre-empt a 413. */
export const LIMITS = {
  maxTextBytes: 400_000,
  /** Beyond this, token-level decoration is replaced by the segment heat bar. */
  maxDecoratedTokens: 5_000,
  debounceMs: 400,
} as const;
