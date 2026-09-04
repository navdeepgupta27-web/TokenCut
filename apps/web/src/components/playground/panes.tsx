"use client";

import { useState } from "react";
import type { ReactNode } from "react";

import { Badge, Button, Note } from "@/components/ui/primitives";
import { ModelCountRow } from "@/components/playground/TokenCount";
import { LIMITS } from "@/lib/config";
import type { AnalyzeResponse, ModelInfo, RiskLevel } from "@/lib/api/types";
import type { Action, PlaygroundState } from "@/lib/playground/state";

const riskTone: Record<RiskLevel, "positive" | "warning" | "danger"> = {
  safe: "positive",
  moderate: "warning",
  aggressive: "danger",
};

function money(value: number): string {
  if (value === 0) return "$0";
  if (Math.abs(value) < 0.01) return `$${value.toFixed(5)}`;
  if (Math.abs(value) < 1) return `$${value.toFixed(3)}`;
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function displayName(models: ModelInfo[], id: string): string {
  return models.find((m) => m.id === id)?.display_name ?? id;
}

function EmptyPane({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="flex h-full min-h-[16rem] items-center justify-center p-8 text-center">
      <p className="max-w-sm text-sm text-[var(--text-faint)]">{children}</p>
    </div>
  );
}

/* ========================================================================== */

export function TokenMapPane({
  analysis,
  models,
}: {
  analysis: AnalyzeResponse | null;
  models: ModelInfo[];
}): ReactNode {
  if (!analysis) {
    return <EmptyPane>Type or paste a prompt to see how it tokenizes.</EmptyPane>;
  }

  const results = analysis.tokenize.results;
  const withOffsets = results.filter((r) => r.offsets && r.offsets.length > 0);
  const tokenCount = withOffsets[0]?.offsets?.length ?? 0;
  const overCap = tokenCount > LIMITS.maxDecoratedTokens;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="rounded-[var(--radius-control)] border bg-[var(--bg-sunken)] p-3">
        {results.map((result) => (
          <ModelCountRow
            key={result.model}
            result={result}
            displayName={displayName(models, result.model)}
          />
        ))}
      </div>

      {withOffsets.length > 0 ? (
        <Note tone="accent" title="Token boundaries are shaded in the editor">
          Alternating shades mark where one token ends and the next begins for{" "}
          <strong>{displayName(models, withOffsets[0]!.model)}</strong>.
          {overCap ? (
            <>
              {" "}
              Showing the first {LIMITS.maxDecoratedTokens.toLocaleString()} of{" "}
              {tokenCount.toLocaleString()} tokens — decorating every token in a
              document this long would make the editor unusable.
            </>
          ) : null}
        </Note>
      ) : null}

      <Note tone="warning" title="Why only one model gets a token map">
        Exact token boundaries are recoverable for the OpenAI family because its
        tokenizer is available offline and reverses to bytes. Anthropic&apos;s and
        Google&apos;s counting endpoints return a total and nothing else — there is
        no way to know where their token boundaries fall. Showing OpenAI&apos;s
        boundaries under a Claude label would be a guess dressed as data, so we
        don&apos;t.
      </Note>

      {analysis.tokenize.warnings.map((warning) => (
        <Note key={warning} tone="neutral">
          {warning}
        </Note>
      ))}
    </div>
  );
}

/* ========================================================================== */

export function OptimizedPane({
  state,
  dispatch,
  analysis,
}: {
  state: PlaygroundState;
  dispatch: React.Dispatch<Action>;
  analysis: AnalyzeResponse | null;
}): ReactNode {
  const [copied, setCopied] = useState(false);

  if (!analysis) {
    return <EmptyPane>The optimized version of your prompt will appear here.</EmptyPane>;
  }

  const { optimize } = analysis;
  const saved = optimize.tokens_before - optimize.tokens_after;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(optimize.optimized_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked by permissions policy or an insecure origin.
      // Failing silently is wrong; the text is selectable in the box below.
      setCopied(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[var(--text-muted)]">
          <span className="tnum font-semibold text-[var(--text)]">
            {saved.toLocaleString()}
          </span>{" "}
          tokens removed losslessly
          <span className="text-[var(--text-faint)]">
            {" "}
            (measured with {optimize.measure_model})
          </span>
        </p>
        <Button variant="primary" onClick={copy} data-testid="copy-optimized">
          {copied ? "Copied" : "Copy optimized"}
        </Button>
      </div>

      <pre className="max-h-72 overflow-auto rounded-[var(--radius-control)] border bg-[var(--bg-sunken)] p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {optimize.optimized_text}
      </pre>

      {/* ---- applied ---- */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-[var(--text-muted)] uppercase">
          Applied · {optimize.applied.length}
        </h3>
        {optimize.applied.length === 0 ? (
          <p className="text-xs text-[var(--text-faint)]">
            Nothing to clean up losslessly — this prompt is already tight.
          </p>
        ) : (
          optimize.applied.map((rule) => (
            <div
              key={rule.rule_id}
              className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border bg-[var(--bg-sunken)] px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <Badge tone={riskTone[rule.risk]}>{rule.risk}</Badge>
                <span className="truncate text-xs text-[var(--text)]">{rule.name}</span>
                <span className="shrink-0 text-[10px] text-[var(--text-faint)]">
                  ×{rule.occurrences}
                </span>
              </div>
              <span className="tnum shrink-0 text-xs font-medium text-[var(--positive)]">
                −{rule.tokens_saved}
              </span>
            </div>
          ))
        )}
      </section>

      {/* ---- suggested ---- */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-[var(--text-muted)] uppercase">
          Suggested · {optimize.suggested.length}
        </h3>
        <p className="text-xs text-[var(--text-faint)]">
          Not applied. Each of these could change how the model behaves, so it is
          yours to decide — read the note, then apply it if you agree.
        </p>

        {optimize.suggested.map((rule) => {
          const expanded = state.expandedSuggestion === rule.rule_id;
          const enabled = state.ruleOverrides[rule.rule_id] === true;
          const advisory = rule.category === "advisory";

          return (
            <div
              key={rule.rule_id}
              className="rounded-[var(--radius-control)] border bg-[var(--bg-sunken)]"
            >
              <button
                type="button"
                onClick={() =>
                  dispatch({
                    type: "expandSuggestion",
                    ruleId: expanded ? null : rule.rule_id,
                  })
                }
                aria-expanded={expanded}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Badge tone={advisory ? "accent" : riskTone[rule.risk]}>
                    {advisory ? "advice" : rule.risk}
                  </Badge>
                  <span className="truncate text-xs text-[var(--text)]">{rule.name}</span>
                  <span className="shrink-0 text-[10px] text-[var(--text-faint)]">
                    ×{rule.occurrences}
                  </span>
                </div>
                <span className="tnum shrink-0 text-xs text-[var(--text-muted)]">
                  {advisory
                    ? ""
                    : rule.tokens_saved_if_applied > 0
                      ? `−${rule.tokens_saved_if_applied}`
                      : "±0"}
                </span>
              </button>

              {expanded ? (
                <div className="flex flex-col gap-2 border-t px-3 py-2.5">
                  <p className="text-xs leading-relaxed text-[var(--text-muted)]">
                    {rule.advice ?? rule.semantic_risk_note}
                  </p>

                  {!advisory ? (
                    <>
                      {rule.tokens_saved_if_applied === 0 ? (
                        <Note tone="warning">
                          Applying this would not actually save any tokens here.
                          Shorter text is not always fewer tokens — removing a word
                          can force the next one to split.
                        </Note>
                      ) : null}
                      <label className="flex cursor-pointer items-center gap-2 text-xs">
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={(event) =>
                            event.target.checked
                              ? dispatch({
                                  type: "toggleRule",
                                  ruleId: rule.rule_id,
                                  enabled: true,
                                })
                              : dispatch({
                                  type: "clearRuleOverride",
                                  ruleId: rule.rule_id,
                                })
                          }
                          className="accent-[var(--accent)]"
                        />
                        Apply this rule
                      </label>
                    </>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </section>

      {optimize.warnings.map((warning) => (
        <Note key={warning} tone="warning">
          {warning}
        </Note>
      ))}
    </div>
  );
}

/* ========================================================================== */

export function SavingsPane({
  analysis,
  models,
  callsPerMonth,
}: {
  analysis: AnalyzeResponse | null;
  models: ModelInfo[];
  callsPerMonth: number;
}): ReactNode {
  if (!analysis) {
    return <EmptyPane>Cost analysis appears once there is a prompt to analyse.</EmptyPane>;
  }

  const { cost } = analysis;
  const priced = cost.results.filter((r) => r.available);
  const unpriced = cost.results.filter((r) => !r.available);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="overflow-x-auto rounded-[var(--radius-control)] border">
        <table className="w-full min-w-[30rem] text-sm">
          <thead className="bg-[var(--bg-sunken)] text-left">
            <tr className="text-[10px] font-semibold tracking-wider text-[var(--text-faint)] uppercase">
              <th className="px-3 py-2">Model</th>
              <th className="px-3 py-2 text-right">Per call</th>
              <th className="px-3 py-2 text-right">Saved / call</th>
              <th className="px-3 py-2 text-right">Saved / month</th>
            </tr>
          </thead>
          <tbody>
            {priced.map((row) => (
              <tr key={row.model} className="border-t">
                <td className="px-3 py-2">
                  <span className="text-[var(--text)]">
                    {displayName(models, row.model)}
                  </span>
                  {row.input_only ? (
                    <span
                      className="ml-1.5 text-[10px] text-[var(--text-faint)]"
                      title="No output-token estimate supplied, so this covers input only."
                    >
                      input only
                    </span>
                  ) : null}
                  {row.crossed_pricing_tier ? (
                    <span
                      className="ml-1.5 rounded-full bg-[var(--positive-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--positive)]"
                      title="Optimization dropped this prompt into a cheaper pricing band, so the per-token rate fell too — the saving is larger than the token reduction alone."
                    >
                      band change
                    </span>
                  ) : null}
                </td>
                <td className="tnum px-3 py-2 text-right text-[var(--text-muted)]">
                  {row.cost_before_per_call != null ? money(row.cost_before_per_call) : "—"}
                  <span className="text-[var(--text-faint)]"> → </span>
                  {row.cost_after_per_call != null ? money(row.cost_after_per_call) : "—"}
                </td>
                <td className="tnum px-3 py-2 text-right text-[var(--positive)]">
                  {row.saved_per_call != null ? money(row.saved_per_call) : "—"}
                </td>
                <td className="tnum px-3 py-2 text-right font-semibold text-[var(--positive)]">
                  {row.saved_per_month != null ? money(row.saved_per_month) : "—"}
                </td>
              </tr>
            ))}

            {unpriced.map((row) => (
              <tr key={row.model} className="border-t bg-[var(--bg-sunken)]/50">
                <td className="px-3 py-2 text-[var(--text-muted)]">
                  {displayName(models, row.model)}
                </td>
                <td
                  className="px-3 py-2 text-right text-xs text-[var(--text-faint)]"
                  colSpan={3}
                >
                  {row.unavailable_reason ?? "no verified price"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="tnum text-xs text-[var(--text-muted)]">
        {cost.tokens_saved_per_call.toLocaleString()} input tokens saved per call ×{" "}
        {callsPerMonth.toLocaleString()} calls / month
      </p>

      {/* Per-model pricing caveats: length-tiered rates, weaker cache
          discounts, verified-price-but-estimated-tokens, and so on. These
          change what the numbers above mean, so they sit next to them. */}
      {cost.results
        .filter((row) => row.pricing_note)
        .map((row) => (
          <Note key={row.model} tone="neutral" title={displayName(models, row.model)}>
            {row.pricing_note}
          </Note>
        ))}

      {cost.assumptions.length > 0 ? (
        <Note tone="neutral" title="Assumptions behind these figures">
          <ul className="list-disc space-y-1 pl-4">
            {cost.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </Note>
      ) : null}

      {cost.warnings.map((warning) => (
        <Note key={warning} tone="warning">
          {warning}
        </Note>
      ))}

      {cost.pricing_oldest_retrieved_at ? (
        <p className="text-[11px] text-[var(--text-faint)]">
          Prices as of {cost.pricing_oldest_retrieved_at}.{" "}
          {priced.map((row) =>
            row.pricing_source_url ? (
              <a
                key={row.model}
                href={row.pricing_source_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="mr-2 underline decoration-dotted hover:text-[var(--text-muted)]"
              >
                {displayName(models, row.model)} source
              </a>
            ) : null,
          )}
        </p>
      ) : null}
    </div>
  );
}
