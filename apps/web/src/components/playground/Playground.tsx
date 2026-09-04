"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

import { Button, Card, Note } from "@/components/ui/primitives";
import { Controls } from "@/components/playground/Controls";
import { MetricsBar } from "@/components/playground/MetricsBar";
import { PromptEditor } from "@/components/playground/PromptEditor";
import { OptimizedPane, SavingsPane, TokenMapPane } from "@/components/playground/panes";
import { SAMPLES } from "@/components/playground/samples";
import { usePlayground } from "@/lib/playground/usePlayground";
import { isStale, type Tab } from "@/lib/playground/state";
import { LIMITS } from "@/lib/config";
import type { ModelInfo } from "@/lib/api/types";

/**
 * Container component: owns all state, renders no data of its own.
 *
 * The model catalog arrives as a prop from the Server Component that fetched
 * it at build/request time — so the picker is populated in the first paint
 * with no client fetch, and the page still works if the API is asleep.
 */

const TABS: { id: Tab; label: string }[] = [
  { id: "map", label: "Token map" },
  { id: "optimized", label: "Optimized" },
  { id: "savings", label: "Savings" },
];

export function Playground({ models }: { models: ModelInfo[] }): ReactNode {
  const { state, dispatch, oversized, retry } = usePlayground();

  const primaryModel = state.models[0] ?? "gpt-4o";
  const stale = isStale(state);

  // Offsets belong to the analysed text. Once it is stale they are wrong, so
  // the decorations come off rather than sitting misaligned.
  const tokenSpans = stale
    ? null
    : (state.analysis?.tokenize.results.find((r) => r.offsets)?.offsets ?? null);

  const suggestionSpans = stale
    ? []
    : (state.analysis?.optimize.suggested.flatMap((rule) => rule.spans) ?? []);

  return (
    <div className="flex min-h-screen flex-col">
      <MetricsBar
        primaryModel={primaryModel}
        analysis={state.analysis}
        localCount={state.localCounts[primaryModel]}
        stale={stale}
        loading={state.status === "loading"}
        callsPerMonth={state.callsPerMonth}
      />

      <div className="mx-auto grid w-full max-w-[1600px] flex-1 gap-4 px-4 py-4 sm:px-6 lg:grid-cols-[minmax(0,46fr)_minmax(0,54fr)]">
        {/* ------------------------------ LEFT ------------------------------ */}
        <div className="flex min-w-0 flex-col gap-4">
          <Card className="flex min-h-[22rem] flex-col p-3 lg:min-h-[28rem]">
            <PromptEditor
              value={state.text}
              onChange={(text) => dispatch({ type: "setText", text })}
              tokenSpans={tokenSpans}
              suggestionSpans={suggestionSpans}
            />
          </Card>

          {state.text.length === 0 ? (
            <Card className="p-4">
              <p className="mb-3 text-xs font-semibold tracking-wide text-[var(--text-muted)] uppercase">
                Try a sample
              </p>
              <div className="flex flex-col gap-2">
                {SAMPLES.map((sample) => (
                  <button
                    key={sample.id}
                    type="button"
                    onClick={() => dispatch({ type: "setText", text: sample.text })}
                    className="flex flex-col items-start gap-0.5 rounded-[var(--radius-control)] border bg-[var(--bg-sunken)] px-3 py-2 text-left transition-colors hover:bg-[var(--bg-hover)]"
                  >
                    <span className="text-sm text-[var(--text)]">{sample.label}</span>
                    <span className="text-xs text-[var(--text-faint)]">{sample.blurb}</span>
                  </button>
                ))}
              </div>
            </Card>
          ) : null}

          {oversized ? (
            <Note tone="danger" title="Too large to analyse">
              This prompt is over the {(LIMITS.maxTextBytes / 1000).toLocaleString()} KB
              limit. Local counts are paused and nothing has been sent to the server.
            </Note>
          ) : null}

          <Card className="p-4">
            <Controls state={state} dispatch={dispatch} models={models} />
          </Card>
        </div>

        {/* ------------------------------ RIGHT ----------------------------- */}
        <div className="flex min-w-0 flex-col gap-4">
          <Card className="flex min-w-0 flex-col overflow-hidden">
            <div
              role="tablist"
              aria-label="Analysis"
              className="flex shrink-0 gap-1 border-b bg-[var(--bg-sunken)] p-1"
            >
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={state.activeTab === tab.id}
                  onClick={() => dispatch({ type: "setTab", tab: tab.id })}
                  className={clsx(
                    "rounded-[var(--radius-control)] px-3 py-1.5 text-xs font-medium transition-colors",
                    state.activeTab === tab.id
                      ? "bg-[var(--bg-raised)] text-[var(--text)] shadow-sm"
                      : "text-[var(--text-muted)] hover:text-[var(--text)]",
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="min-w-0 flex-1">
              {state.localOnly ? (
                <div className="p-4">
                  <Note tone="accent" title="Local-only mode is on">
                    Your prompt is staying in this browser, so there is nothing to
                    show here. Exact OpenAI counts are in the bar above. Turn
                    Local-only off to get Claude and Gemini counts, the optimizer,
                    and cost analysis.
                  </Note>
                </div>
              ) : state.status === "error" && state.error ? (
                <div className="flex flex-col gap-3 p-4">
                  <Note tone="danger" title={`Analysis failed (${state.error.code})`}>
                    {state.error.message}
                  </Note>
                  <div>
                    <Button onClick={retry}>Try again</Button>
                  </div>
                  <p className="text-xs text-[var(--text-faint)]">
                    Your OpenAI counts above are computed locally and are unaffected.
                  </p>
                </div>
              ) : state.activeTab === "map" ? (
                <TokenMapPane analysis={state.analysis} models={models} />
              ) : state.activeTab === "optimized" ? (
                <OptimizedPane
                  state={state}
                  dispatch={dispatch}
                  analysis={state.analysis}
                />
              ) : (
                <SavingsPane
                  analysis={state.analysis}
                  models={models}
                  callsPerMonth={state.callsPerMonth}
                />
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
