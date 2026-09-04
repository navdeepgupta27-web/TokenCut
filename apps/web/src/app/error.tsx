"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

/**
 * Route-level error boundary.
 *
 * Deliberately shows the digest and nothing else. `error.message` from a
 * Server Component is redacted by Next in production anyway, and echoing raw
 * error text into the page is how internals leak into a screenshot.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): ReactNode {
  useEffect(() => {
    // Wire to a real error reporter here. Never include prompt text.
    console.error("route_error", error.digest ?? error.name);
  }, [error]);

  return (
    <div className="mx-auto max-w-[46rem] px-4 py-24 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Something broke</h1>
      <p className="mt-3 text-sm text-[var(--text-muted)]">
        This page failed to render. Your prompt was not saved anywhere.
      </p>
      {error.digest ? (
        <p className="mt-2 font-mono text-xs text-[var(--text-faint)]">
          Reference: {error.digest}
        </p>
      ) : null}
      <button
        type="button"
        onClick={reset}
        className="mt-6 inline-flex items-center rounded-[var(--radius-control)] border px-4 py-2 text-sm font-medium hover:bg-[var(--bg-hover)]"
      >
        Try again
      </button>
    </div>
  );
}
