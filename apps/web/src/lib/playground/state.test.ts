import { describe, expect, it } from "vitest";

import { type PlaygroundState, initialState, isStale, reducer } from "./state";
import type { AnalyzeResponse } from "@/lib/api/types";

/**
 * Reducer tests.
 *
 * The reducer is pure, so all of this runs with no DOM, no network and no
 * React — which is the payoff for keeping every side effect in the hook.
 */

const fakeAnalysis = (text: string): AnalyzeResponse =>
  ({
    tokenize: { results: [], segments: null, chars: text.length, bytes: text.length, warnings: [] },
    optimize: {
      optimized_text: text,
      applied: [],
      suggested: [],
      tokens_before: 10,
      tokens_after: 8,
      measure_model: "gpt-4o",
      measure_source: "exact_local",
      warnings: [],
    },
    tokenize_optimized: {
      results: [],
      segments: null,
      chars: text.length,
      bytes: text.length,
      warnings: [],
    },
    cost: {
      results: [],
      tokens_saved_per_call: 2,
      assumptions: [],
      warnings: [],
      pricing_oldest_retrieved_at: null,
    },
    warnings: [],
  }) as AnalyzeResponse;

describe("model selection", () => {
  it("refuses to empty the model list", () => {
    const one: PlaygroundState = { ...initialState, models: ["gpt-4o"] };
    const next = reducer(one, { type: "toggleModel", model: "gpt-4o" });
    expect(next.models).toEqual(["gpt-4o"]);
    expect(next).toBe(one); // unchanged reference — no needless re-render
  });

  it("adds and removes models otherwise", () => {
    let state = reducer(initialState, { type: "toggleModel", model: "gemini-2.5-pro" });
    expect(state.models).toContain("gemini-2.5-pro");
    state = reducer(state, { type: "toggleModel", model: "gemini-2.5-pro" });
    expect(state.models).not.toContain("gemini-2.5-pro");
  });
});

describe("stale-response guard", () => {
  it("drops a response that arrived after the user kept typing", () => {
    const typed: PlaygroundState = { ...initialState, text: "version two" };
    const next = reducer(typed, {
      type: "analyzeSuccess",
      text: "version one", // the request this answers is obsolete
      data: fakeAnalysis("version one"),
    });
    expect(next.analysis).toBeNull();
    expect(next).toBe(typed);
  });

  it("accepts a response matching the current text", () => {
    const typed: PlaygroundState = { ...initialState, text: "hello" };
    const next = reducer(typed, {
      type: "analyzeSuccess",
      text: "hello",
      data: fakeAnalysis("hello"),
    });
    expect(next.analysis).not.toBeNull();
    expect(next.status).toBe("ready");
  });

  it("reports staleness once the text moves on", () => {
    let state = reducer({ ...initialState, text: "a" }, {
      type: "analyzeSuccess",
      text: "a",
      data: fakeAnalysis("a"),
    });
    expect(isStale(state)).toBe(false);
    state = reducer(state, { type: "setText", text: "ab" });
    expect(isStale(state)).toBe(true);
  });
});

describe("local-only mode", () => {
  it("discards server results the moment it is switched on", () => {
    let state = reducer({ ...initialState, text: "x" }, {
      type: "analyzeSuccess",
      text: "x",
      data: fakeAnalysis("x"),
    });
    expect(state.analysis).not.toBeNull();

    state = reducer(state, { type: "setLocalOnly", localOnly: true });
    // Leaving stale server output on screen after the user asks for
    // local-only would misrepresent what the page is doing.
    expect(state.analysis).toBeNull();
    expect(state.status).toBe("idle");
  });
});

describe("profile and rule overrides", () => {
  it("clears per-rule overrides when the profile changes", () => {
    let state = reducer(initialState, {
      type: "toggleRule",
      ruleId: "flag_politeness",
      enabled: true,
    });
    expect(state.ruleOverrides.flag_politeness).toBe(true);

    state = reducer(state, { type: "setProfile", profile: "aggressive" });
    // Otherwise the profile buttons appear not to work.
    expect(state.ruleOverrides).toEqual({});
  });

  it("removes an override entirely rather than setting it false", () => {
    let state = reducer(initialState, {
      type: "toggleRule",
      ruleId: "compact_json",
      enabled: true,
    });
    state = reducer(state, { type: "clearRuleOverride", ruleId: "compact_json" });
    // An absent key means "use the profile default"; false means "force off".
    expect("compact_json" in state.ruleOverrides).toBe(false);
  });
});

describe("numeric inputs", () => {
  it("floors and clamps calls per month", () => {
    expect(reducer(initialState, { type: "setCallsPerMonth", calls: -5 }).callsPerMonth).toBe(0);
    expect(reducer(initialState, { type: "setCallsPerMonth", calls: 12.7 }).callsPerMonth).toBe(12);
  });

  it("allows output tokens to be unset", () => {
    const state = reducer(initialState, { type: "setTokensOut", tokensOut: null });
    expect(state.tokensOut).toBeNull();
  });
});
