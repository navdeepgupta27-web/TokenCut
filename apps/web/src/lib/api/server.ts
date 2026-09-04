import "server-only";

import { serverEnv } from "@/lib/config";
import type { ApiErrorBody } from "@/lib/api/types";

/**
 * Server-side client for the FastAPI service.
 *
 * `server-only` at the top makes importing this from a Client Component a build
 * error, which is what keeps `API_BASE_URL` out of the browser bundle.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  /** Real client IP, forwarded so the backend's per-IP limiter still works. */
  clientIp?: string;
  /** Correlates a browser request with backend logs. */
  requestId?: string;
  /** ISR revalidation window for GETs. Omit for no-store. */
  revalidate?: number;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const env = serverEnv();
  const { method = "GET", body, clientIp, requestId, revalidate } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (requestId) headers["X-Request-Id"] = requestId;
  if (env.API_INTERNAL_TOKEN) headers["Authorization"] = `Bearer ${env.API_INTERNAL_TOKEN}`;

  // Without this the backend sees the serverless function's address and
  // rate-limits every visitor as if they were one client. Forwarding the real
  // IP is what keeps the shared provider quota protected per user.
  if (clientIp) headers["X-Forwarded-For"] = clientIp;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), env.API_TIMEOUT_MS);

  try {
    const response = await fetch(`${env.API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      ...(revalidate === undefined ? { cache: "no-store" } : { next: { revalidate } }),
    });

    const text = await response.text();

    if (!response.ok) {
      let code = "upstream_error";
      let message = `Upstream returned ${response.status}`;
      let upstreamRequestId: string | undefined;

      try {
        const parsed = JSON.parse(text) as ApiErrorBody;
        if (parsed?.error) {
          code = parsed.error.code;
          message = parsed.error.message;
          upstreamRequestId = parsed.error.request_id;
        }
      } catch {
        // Upstream returned something that is not our envelope (a proxy error
        // page, most likely). The defaults above already cover it.
      }

      const retryAfterHeader = response.headers.get("retry-after");
      throw new ApiError(
        response.status,
        code,
        message,
        upstreamRequestId,
        retryAfterHeader ? Number(retryAfterHeader) : undefined,
      );
    }

    return (text ? JSON.parse(text) : null) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError(
        504,
        "upstream_timeout",
        `The analysis service did not respond within ${env.API_TIMEOUT_MS}ms. ` +
          `On a free-tier host this is usually a cold start — try again.`,
      );
    }
    throw new ApiError(
      502,
      "upstream_unavailable",
      "Could not reach the analysis service.",
    );
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Extract the client IP from proxy headers.
 *
 * Spoofable, and that is acceptable: this feeds a cost control, not an
 * authorisation decision. Never use it for anything that grants access.
 */
export function clientIpFrom(headers: Headers): string | undefined {
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) {
    const first = forwarded.split(",")[0]?.trim();
    if (first) return first;
  }
  return headers.get("x-real-ip") ?? undefined;
}
