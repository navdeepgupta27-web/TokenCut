"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

import { Badge, Field, Note, NumberInput } from "@/components/ui/primitives";
import type { ModelInfo, Profile } from "@/lib/api/types";
import type { Action, PlaygroundState } from "@/lib/playground/state";

const PROFILES: { id: Profile; label: string; blurb: string }[] = [
  { id: "safe", label: "Safe", blurb: "Lossless normalisation only" },
  { id: "balanced", label: "Balanced", blurb: "Adds structural re-encoding" },
  { id: "aggressive", label: "Aggressive", blurb: "Adds markup stripping" },
];

export function Controls({
  state,
  dispatch,
  models,
}: {
  state: PlaygroundState;
  dispatch: React.Dispatch<Action>;
  models: ModelInfo[];
}): ReactNode {
  const selected = new Set(state.models);

  return (
    <div className="flex flex-col gap-5">
      <Field label="Models" hint="The first selected model drives the headline figures.">
        <div className="flex flex-wrap gap-2">
          {models.map((model) => {
            const active = selected.has(model.id);
            const onlyOne = active && state.models.length === 1;

            // Counting availability and pricing availability are separate
            // facts, so the chip shows both rather than one merged status.
            const caveats: string[] = [];
            if (model.counting === "estimate_only") caveats.push("estimated");
            if (model.counting === "unavailable") caveats.push("unavailable");
            if (!model.pricing_verified) caveats.push("no price");

            return (
              <button
                key={model.id}
                type="button"
                onClick={() => dispatch({ type: "toggleModel", model: model.id })}
                disabled={onlyOne}
                aria-pressed={active}
                title={
                  [
                    model.counting === "offline"
                      ? "Counted locally — nothing leaves your browser for this model."
                      : model.counting === "api"
                        ? "Counted exactly by the provider's endpoint (free of token charges)."
                        : model.counting === "estimate_only"
                          ? model.unavailable_reason ??
                            "No provider key configured — an estimate is shown."
                          : "Counting unavailable for this model.",
                    model.pricing_verified
                      ? null
                      : "No verified price on file, so cost is suppressed for this model.",
                    onlyOne ? "At least one model must stay selected." : null,
                  ]
                    .filter(Boolean)
                    .join("\n")
                }
                className={clsx(
                  "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                  active
                    ? "border-transparent bg-[var(--accent-subtle)] text-[var(--accent)]"
                    : "bg-[var(--bg-raised)] text-[var(--text-muted)] hover:bg-[var(--bg-hover)]",
                  onlyOne && "cursor-not-allowed opacity-70",
                )}
              >
                <span
                  aria-hidden
                  className={clsx(
                    "size-1.5 rounded-full",
                    active ? "bg-[var(--accent)]" : "bg-[var(--border-strong)]",
                  )}
                />
                {model.display_name}
                {caveats.length > 0 ? (
                  <span className="text-[10px] text-[var(--text-faint)]">
                    {caveats.join(" · ")}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </Field>

      <Field label="Optimization profile">
        <div
          role="radiogroup"
          aria-label="Optimization profile"
          className="grid grid-cols-3 gap-1 rounded-[var(--radius-control)] border bg-[var(--bg-sunken)] p-1"
        >
          {PROFILES.map((profile) => (
            <button
              key={profile.id}
              type="button"
              role="radio"
              aria-checked={state.profile === profile.id}
              onClick={() => dispatch({ type: "setProfile", profile: profile.id })}
              title={profile.blurb}
              className={clsx(
                "rounded-[calc(var(--radius-control)-2px)] px-2 py-1.5 text-xs font-medium transition-colors",
                state.profile === profile.id
                  ? "bg-[var(--bg-raised)] text-[var(--text)] shadow-sm"
                  : "text-[var(--text-muted)] hover:text-[var(--text)]",
              )}
            >
              {profile.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-[var(--text-faint)]">
          {PROFILES.find((p) => p.id === state.profile)?.blurb}. Prompt-audit
          findings are never applied by a profile — you apply those one at a time.
        </p>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Calls / month" htmlFor="calls">
          <NumberInput
            id="calls"
            value={state.callsPerMonth.toLocaleString()}
            onChange={(event) => {
              const digits = event.target.value.replace(/[^\d]/g, "");
              dispatch({ type: "setCallsPerMonth", calls: Number(digits || 0) });
            }}
          />
        </Field>

        <Field label="Output tokens" htmlFor="tokens-out">
          <NumberInput
            id="tokens-out"
            placeholder="unset"
            value={state.tokensOut === null ? "" : state.tokensOut.toLocaleString()}
            onChange={(event) => {
              const digits = event.target.value.replace(/[^\d]/g, "");
              dispatch({
                type: "setTokensOut",
                tokensOut: digits === "" ? null : Number(digits),
              });
            }}
          />
        </Field>
      </div>
      <p className="-mt-3 text-xs text-[var(--text-faint)]">
        Output length cannot be derived from a prompt, so it is yours to supply.
        Leave it blank and only input-side cost is reported.
      </p>

      <Field label="Privacy">
        <label className="flex cursor-pointer items-start gap-2.5 rounded-[var(--radius-control)] border bg-[var(--bg-sunken)] p-3">
          <input
            type="checkbox"
            checked={state.localOnly}
            onChange={(event) =>
              dispatch({ type: "setLocalOnly", localOnly: event.target.checked })
            }
            className="mt-0.5 accent-[var(--accent)]"
          />
          <span className="text-xs leading-relaxed">
            <span className="font-medium text-[var(--text)]">Local-only mode</span>
            <span className="block text-[var(--text-muted)]">
              Nothing is sent anywhere. You get exact OpenAI counts from your own
              browser and nothing else — no Claude or Gemini counts, no
              optimization, no cost analysis.
            </span>
          </span>
        </label>
      </Field>

      {state.localOnly ? (
        <Note tone="accent" title="Local-only is on">
          Your prompt is not leaving this browser. Turn it off to get exact Claude
          and Gemini counts, the optimizer, and cost analysis.
        </Note>
      ) : (
        <Note tone="neutral">
          <span className="font-medium">Where your text goes.</span> OpenAI counts
          are computed in your browser and are never transmitted. Claude and Gemini
          have no public offline tokenizer, so getting an exact count for them means
          sending the text to this site&apos;s server, which forwards it to the
          provider&apos;s free token-counting endpoint. Prompt text is never logged
          or stored. Use Local-only mode above to opt out entirely.
        </Note>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        <Badge tone="neutral">
          {new TextEncoder().encode(state.text).length.toLocaleString()} bytes
        </Badge>
        <Badge tone="neutral">{state.text.length.toLocaleString()} chars</Badge>
      </div>
    </div>
  );
}
