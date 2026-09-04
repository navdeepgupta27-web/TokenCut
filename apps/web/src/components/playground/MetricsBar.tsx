"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/primitives";
import { TokenCount } from "@/components/playground/TokenCount";
import type { AnalyzeResponse, TokenResult } from "@/lib/api/types";
import type { LocalCount } from "@/lib/tokenizer/localTokenizer";

/**
 * The sticky metrics bar — the thing people screenshot.
 *
 * It must survive at 375px, and it must never show a dollar figure it cannot
 * defend. When no verified price exists for the primary model, the money slot
 * says so instead of quietly reading zero.
 */

function formatMoney(value: number): string {
  if (value === 0) return "$0";
  if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
  if (Math.abs(value) < 1) return `$${value.toFixed(3)}`;
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function Cell({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}): ReactNode {
  return (
    <div className="flex min-w-0 flex-col gap-0.5" title={hint}>
      <span className="text-[10px] font-medium tracking-wider text-[var(--text-faint)] uppercase">
        {label}
      </span>
      <span className="truncate">{children}</span>
    </div>
  );
}

export function MetricsBar({
  primaryModel,
  analysis,
  localCount,
  stale,
  loading,
  callsPerMonth,
}: {
  primaryModel: string;
  analysis: AnalyzeResponse | null;
  localCount: LocalCount | undefined;
  stale: boolean;
  loading: boolean;
  callsPerMonth: number;
}): ReactNode {
  const before: TokenResult | undefined = analysis?.tokenize.results.find(
    (r) => r.model === primaryModel,
  );
  const after: TokenResult | undefined = analysis?.tokenize_optimized.results.find(
    (r) => r.model === primaryModel,
  );

  // Before the first server response lands, show the local worker's count so
  // the bar is never empty while someone is typing.
  const beforeDisplay: Pick<
    TokenResult,
    "tokens" | "source" | "calibrated" | "estimate_error_p90" | "note"
  > =
    before ??
    (localCount
      ? {
          tokens: localCount.tokens,
          source: "exact_local",
          calibrated: null,
          estimate_error_p90: null,
          note: null,
        }
      : {
          tokens: null,
          source: "unavailable",
          calibrated: null,
          estimate_error_p90: null,
          note: "Start typing to see a count.",
        });

  const cost = analysis?.cost.results.find((r) => r.model === primaryModel);

  const reduction =
    before?.tokens != null && after?.tokens != null && before.tokens > 0
      ? (before.tokens - after.tokens) / before.tokens
      : null;

  return (
    <div
      className={clsx(
        "sticky top-0 z-20 border-b bg-[var(--bg)]/95 backdrop-blur",
        "supports-[backdrop-filter]:bg-[var(--bg)]/80",
      )}
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-end gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <Cell label="Tokens" hint="Your prompt as written.">
          <TokenCount result={beforeDisplay} size="lg" />
        </Cell>

        <span aria-hidden className="pb-1 text-lg text-[var(--text-faint)]">
          →
        </span>

        <Cell label="Optimized" hint="After the applied lossless rules.">
          {after ? (
            <TokenCount result={after} size="lg" />
          ) : (
            <span className="tnum text-2xl font-semibold text-[var(--text-faint)]">—</span>
          )}
        </Cell>

        <Cell label="Reduction">
          {reduction === null ? (
            <span className="tnum text-2xl font-semibold text-[var(--text-faint)]">—</span>
          ) : (
            <span
              className={clsx(
                "tnum text-2xl font-semibold",
                reduction > 0 ? "text-[var(--positive)]" : "text-[var(--text-faint)]",
              )}
            >
              {reduction > 0 ? "−" : ""}
              {(reduction * 100).toFixed(1)}%
            </span>
          )}
        </Cell>

        <div className="hidden h-10 w-px bg-[var(--border)] sm:block" />

        <Cell
          label={`Saved / month @ ${callsPerMonth.toLocaleString()} calls`}
          hint={
            cost?.available
              ? "Input-token savings only — compression does not shorten the response."
              : "No verified price on file for this model, so no dollar figure is shown."
          }
        >
          {cost?.available && cost.saved_per_month != null ? (
            <span className="tnum text-2xl font-semibold text-[var(--positive)]">
              {formatMoney(cost.saved_per_month)}
            </span>
          ) : (
            <span className="flex items-baseline gap-2">
              <span className="tnum text-2xl font-semibold text-[var(--text-faint)]">—</span>
              {analysis ? (
                <span className="text-[11px] text-[var(--text-faint)]">price not verified</span>
              ) : null}
            </span>
          )}
        </Cell>

        <div className="ml-auto flex items-center gap-2 pb-1">
          {loading ? <Badge tone="neutral">analysing…</Badge> : null}
          {stale && !loading ? (
            <Badge tone="warning">
              <span title="You have edited the prompt since this analysis ran.">
                out of date
              </span>
            </Badge>
          ) : null}
        </div>
      </div>
    </div>
  );
}
