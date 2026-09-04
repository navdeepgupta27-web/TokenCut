import clsx from "clsx";
import type { ReactNode } from "react";

import type { CountSource, TokenResult } from "@/lib/api/types";
import { isExact } from "@/lib/api/types";

/**
 * The honesty contract, as a component.
 *
 * There is exactly one place in this app that renders a token count, and it is
 * this file. That is deliberate: the rule "never show an estimate as though it
 * were measured" cannot be enforced by documentation, only by making the wrong
 * thing impossible to write. Any component wanting to display a number must
 * hand over the `source` alongside it.
 *
 *   exact_local / exact_api / cached -> 1,284
 *   estimated                        -> ≈1,402
 *   unavailable                      -> —
 */

const sourceLabel: Record<CountSource, string> = {
  exact_local: "Exact — counted locally with the model's own tokenizer. Nothing was sent anywhere.",
  exact_api: "Exact — counted by the provider's own token-counting endpoint.",
  cached: "Exact — a previously measured count for identical text.",
  estimated: "Estimate — the exact count is still loading or unavailable.",
  unavailable: "No count available for this model.",
};

export function TokenCount({
  result,
  size = "md",
  showSourceHint = true,
}: {
  result: Pick<
    TokenResult,
    "tokens" | "source" | "calibrated" | "estimate_error_p90" | "note"
  >;
  size?: "sm" | "md" | "lg";
  showSourceHint?: boolean;
}): ReactNode {
  const { tokens, source, calibrated, estimate_error_p90: errorP90, note } = result;

  const sizing =
    size === "lg" ? "text-2xl font-semibold" : size === "sm" ? "text-xs" : "text-sm";

  if (tokens === null || source === "unavailable") {
    return (
      <span
        className={clsx("tnum text-[var(--text-faint)]", sizing)}
        title={note ?? sourceLabel.unavailable}
        aria-label={`No token count available. ${note ?? ""}`}
      >
        —
      </span>
    );
  }

  const exact = isExact(source);

  // An uncalibrated ratio gets softer wording than a measured one. The
  // difference matters: one has a known error band, the other does not.
  const estimateTitle = exact
    ? sourceLabel[source]
    : calibrated === false
      ? "Rough estimate from an uncalibrated ratio. The exact count replaces it " +
        "as soon as it arrives — do not rely on this figure."
      : errorP90 != null
        ? `Estimate, typically within ${(errorP90 * 100).toFixed(0)}% of the exact count.`
        : sourceLabel.estimated;

  return (
    <span className="inline-flex items-baseline gap-1">
      <span
        className={clsx(
          "tnum",
          sizing,
          exact ? "text-[var(--text)]" : "text-[var(--text-muted)]",
        )}
        title={estimateTitle}
        aria-label={
          exact
            ? `${tokens.toLocaleString()} tokens, exact`
            : `Approximately ${tokens.toLocaleString()} tokens, estimated`
        }
      >
        {exact ? "" : "≈"}
        {tokens.toLocaleString()}
      </span>

      {showSourceHint && !exact ? (
        <span
          className="text-[10px] font-medium tracking-wide text-[var(--warning)] uppercase"
          title={estimateTitle}
        >
          est
        </span>
      ) : null}
    </span>
  );
}

/**
 * Per-model row: name, count, and — where it applies — the caveats that make
 * the number comparable or not.
 */
export function ModelCountRow({
  result,
  displayName,
}: {
  result: TokenResult;
  displayName?: string;
}): ReactNode {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm text-[var(--text)]">
          {displayName ?? result.model}
        </span>

        {result.includes_message_overhead ? (
          <span
            className="shrink-0 cursor-help text-[10px] text-[var(--text-faint)]"
            title={
              "Includes the provider's chat-request framing, so this is what you " +
              "will actually be billed for. It is NOT directly comparable with a " +
              "raw-text count from another provider."
            }
          >
            +framing
          </span>
        ) : null}
      </div>

      <TokenCount result={result} />
    </div>
  );
}
