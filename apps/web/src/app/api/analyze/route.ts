import { NextResponse } from "next/server";
import { z } from "zod";

import { ApiError, apiRequest, clientIpFrom } from "@/lib/api/server";
import { LIMITS } from "@/lib/config";
import type { AnalyzeResponse } from "@/lib/api/types";

/**
 * BFF proxy for POST /v1/analyze.
 *
 * Why proxy instead of calling the Python service from the browser:
 *
 * - **CSP stays at `connect-src 'self'`.** No backend host to allowlist, and
 *   rotating the backend URL is not a CSP change.
 * - **No CORS in the browser at all.** The single most common cause of
 *   "works locally, breaks in production" simply cannot happen.
 * - **The backend address is never public**, so it can sit on a private network
 *   or behind a shared secret.
 * - **One validation boundary.** Nothing reaches the upstream unvalidated.
 *
 * The cost: prompt text transits this function. It is never logged here, and
 * the playground's Local-only mode does not call this route at all.
 */

// Deliberately strict. Anything unexpected is rejected rather than forwarded —
// the upstream should not be a place where unvalidated shapes get discovered.
const AnalyzeBody = z
  .object({
    text: z.string().max(LIMITS.maxTextBytes, "Text exceeds the size limit."),
    models: z.array(z.string().min(1).max(120)).min(1).max(12),
    profile: z.enum(["safe", "balanced", "aggressive"]).default("balanced"),
    rules: z.record(z.string(), z.boolean()).default({}),
    include_offsets: z.boolean().default(false),
    include_segments: z.boolean().default(false),
    tokens_out: z.number().int().min(0).max(10_000_000).nullable().default(null),
    calls_per_month: z.number().int().min(0).max(1_000_000_000).default(1),
    cache_read_fraction: z.number().min(0).max(1).default(0),
    cache_write_fraction: z.number().min(0).max(1).default(0),
    batch_fraction: z.number().min(0).max(1).default(0),
  })
  .strict();

function errorResponse(status: number, code: string, message: string, retryAfter?: number) {
  return NextResponse.json(
    { error: { code, message, details: {}, request_id: "" } },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        ...(retryAfter ? { "Retry-After": String(retryAfter) } : {}),
      },
    },
  );
}

export async function POST(request: Request): Promise<NextResponse> {
  // Reject oversized payloads on the declared length before reading the body,
  // so a large upload is not buffered just to be refused.
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (declaredLength > LIMITS.maxTextBytes * 2) {
    return errorResponse(413, "text_too_large", "Request body is too large.");
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return errorResponse(400, "invalid_request", "Body must be valid JSON.");
  }

  const parsed = AnalyzeBody.safeParse(raw);
  if (!parsed.success) {
    // Field names and messages only. The body itself is user prompt text and
    // must not be echoed into an error payload or a log line.
    return errorResponse(
      422,
      "invalid_request",
      Object.entries(parsed.error.flatten().fieldErrors)
        .map(([field, errors]) => `${field}: ${errors?.join(", ")}`)
        .join("; ") || "Request failed validation.",
    );
  }

  const requestId = crypto.randomUUID().replace(/-/g, "").slice(0, 16);

  try {
    const data = await apiRequest<AnalyzeResponse>("/v1/analyze", {
      method: "POST",
      body: parsed.data,
      clientIp: clientIpFrom(request.headers),
      requestId,
    });

    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store", "X-Request-Id": requestId },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return errorResponse(error.status, error.code, error.message, error.retryAfter);
    }
    // Never surface an unexpected error's details — they can carry internals.
    return errorResponse(500, "internal_error", "Analysis failed unexpectedly.");
  }
}

/** GET is meaningless here; answer explicitly rather than 404-ing confusingly. */
export function GET(): NextResponse {
  return errorResponse(405, "method_not_allowed", "Use POST.");
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
