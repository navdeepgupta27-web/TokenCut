import { NextResponse } from "next/server";

import { ApiError, apiRequest } from "@/lib/api/server";
import type { HealthResponse } from "@/lib/api/types";

/**
 * Backend warm-up / status probe, reachable from the browser.
 *
 * Exists for one deployment reality: a free-tier backend sleeps after idling,
 * and its cold start can take tens of seconds. The playground fires this on
 * mount so the wake-up begins while the visitor is still reading the page,
 * rather than on the first debounced analyse call — which is the one moment
 * latency is most visible.
 *
 * Kept behind the BFF like every other backend call, so `connect-src 'self'`
 * still holds.
 *
 * Deliberately generous timeout and a soft failure: this is a hint, not a
 * dependency. A sleeping or missing backend must never surface an error here.
 */
export async function GET(): Promise<NextResponse> {
  try {
    const data = await apiRequest<HealthResponse>("/health", {
      // A cold container can exceed the normal request timeout. This route
      // has nothing to render, so waiting is free.
      revalidate: 0,
    });
    return NextResponse.json(
      { reachable: true, backend: data },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    // 200 with reachable:false, not a 5xx. The caller treats this as
    // information; an error status would show up as noise in monitoring for
    // an entirely expected free-tier condition.
    return NextResponse.json(
      {
        reachable: false,
        code: error instanceof ApiError ? error.code : "unknown",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
