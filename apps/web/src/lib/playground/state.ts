import type { AnalyzeResponse, Profile } from "@/lib/api/types";
import type { LocalCount } from "@/lib/tokenizer/localTokenizer";

/**
 * Playground state as a pure reducer over typed actions.
 *
 * Why not Redux Toolkit (which the Phase 1 doc proposed): this is one screen
 * with one state machine and no cross-route sharing, so a store, provider,
 * slices, and middleware would be ceremony around a `useReducer`. The shape
 * here is deliberately Redux-shaped — discriminated-union actions, a pure
 * reducer, no side effects inside it — so V2's history dashboard can lift it
 * into `createSlice` almost verbatim if it needs a real store.
 *
 * The reducer stays pure: every fetch and worker call lives in the hook.
 * That is what makes this file unit-testable with no DOM and no network.
 */

export type Tab = "map" | "optimized" | "savings";
export type Status = "idle" | "loading" | "ready" | "error";

export interface PlaygroundState {
  // ---- user input ----
  text: string;
  models: string[];
  profile: Profile;
  /** Per-rule override of the profile default. rule_id -> enabled. */
  ruleOverrides: Record<string, boolean>;
  tokensOut: number | null;
  callsPerMonth: number;

  /**
   * When true, nothing is sent to the server: OpenAI counts come from the
   * local worker and nothing else is shown. The only mode in which the claim
   * "your prompt never leaves this browser" is literally true.
   */
  localOnly: boolean;

  // ---- ui ----
  activeTab: Tab;
  /** Suggestion whose detail is expanded, if any. */
  expandedSuggestion: string | null;

  // ---- async results ----
  /** Instant counts from the worker, keyed by model id. */
  localCounts: Record<string, LocalCount>;
  analysis: AnalyzeResponse | null;
  /** Text the current `analysis` corresponds to; used to detect staleness. */
  analyzedText: string | null;
  status: Status;
  error: { code: string; message: string } | null;
}

export const DEFAULT_MODELS = ["gpt-4o", "claude-opus-5"] as const;

export const initialState: PlaygroundState = {
  text: "",
  models: [...DEFAULT_MODELS],
  profile: "balanced",
  ruleOverrides: {},
  tokensOut: null,
  callsPerMonth: 30_000,
  localOnly: false,
  activeTab: "map",
  expandedSuggestion: null,
  localCounts: {},
  analysis: null,
  analyzedText: null,
  status: "idle",
  error: null,
};

export type Action =
  | { type: "setText"; text: string }
  | { type: "toggleModel"; model: string }
  | { type: "setProfile"; profile: Profile }
  | { type: "toggleRule"; ruleId: string; enabled: boolean }
  | { type: "clearRuleOverride"; ruleId: string }
  | { type: "setTokensOut"; tokensOut: number | null }
  | { type: "setCallsPerMonth"; calls: number }
  | { type: "setLocalOnly"; localOnly: boolean }
  | { type: "setTab"; tab: Tab }
  | { type: "expandSuggestion"; ruleId: string | null }
  | { type: "localCount"; model: string; count: LocalCount }
  | { type: "analyzeStart" }
  | { type: "analyzeSuccess"; text: string; data: AnalyzeResponse }
  | { type: "analyzeError"; code: string; message: string }
  | { type: "reset" };

export function reducer(state: PlaygroundState, action: Action): PlaygroundState {
  switch (action.type) {
    case "setText":
      if (action.text === state.text) return state;
      return { ...state, text: action.text, error: null };

    case "toggleModel": {
      const has = state.models.includes(action.model);
      // Never let the selection empty out — an empty model list makes the
      // whole right pane meaningless and the API reject the request.
      if (has && state.models.length === 1) return state;
      return {
        ...state,
        models: has
          ? state.models.filter((m) => m !== action.model)
          : [...state.models, action.model],
      };
    }

    case "setProfile":
      if (action.profile === state.profile) return state;
      // A profile change supersedes per-rule tinkering; keeping stale
      // overrides makes the profile buttons appear not to work.
      return { ...state, profile: action.profile, ruleOverrides: {} };

    case "toggleRule":
      return {
        ...state,
        ruleOverrides: { ...state.ruleOverrides, [action.ruleId]: action.enabled },
      };

    case "clearRuleOverride": {
      const next = { ...state.ruleOverrides };
      delete next[action.ruleId];
      return { ...state, ruleOverrides: next };
    }

    case "setTokensOut":
      return { ...state, tokensOut: action.tokensOut };

    case "setCallsPerMonth":
      return { ...state, callsPerMonth: Math.max(0, Math.floor(action.calls)) };

    case "setLocalOnly":
      return {
        ...state,
        localOnly: action.localOnly,
        // Drop any server results immediately. Leaving them on screen after
        // the user asks for local-only would misrepresent what is happening.
        analysis: action.localOnly ? null : state.analysis,
        analyzedText: action.localOnly ? null : state.analyzedText,
        status: action.localOnly ? "idle" : state.status,
        error: null,
      };

    case "setTab":
      return { ...state, activeTab: action.tab };

    case "expandSuggestion":
      return { ...state, expandedSuggestion: action.ruleId };

    case "localCount":
      return {
        ...state,
        localCounts: { ...state.localCounts, [action.model]: action.count },
      };

    case "analyzeStart":
      return { ...state, status: "loading", error: null };

    case "analyzeSuccess":
      // Drop a response that arrived after the user kept typing. Without this
      // guard a slow request can overwrite a newer, correct result.
      if (action.text !== state.text) return state;
      return {
        ...state,
        analysis: action.data,
        analyzedText: action.text,
        status: "ready",
        error: null,
      };

    case "analyzeError":
      return {
        ...state,
        status: "error",
        error: { code: action.code, message: action.message },
      };

    case "reset":
      return { ...initialState };

    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

/** True when the displayed analysis no longer matches the editor contents. */
export function isStale(state: PlaygroundState): boolean {
  return state.analysis !== null && state.analyzedText !== state.text;
}
