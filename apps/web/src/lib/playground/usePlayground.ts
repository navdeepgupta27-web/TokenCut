"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import type { AnalyzeRequest, AnalyzeResponse, ApiErrorBody } from "@/lib/api/types";
import { LIMITS } from "@/lib/config";
import { getLocalTokenizer, isLocallyCountable } from "@/lib/tokenizer/localTokenizer";
import { type Action, type PlaygroundState, initialState, reducer } from "@/lib/playground/state";

/**
 * All the side effects the reducer refuses to hold.
 *
 * Two tiers, which is the core interaction design:
 *
 *   tier 1  every keystroke, local worker, OpenAI models only  -> instant
 *   tier 2  debounced 400ms, one /api/analyze call             -> exact
 *
 * Tier 1 numbers are never presented as exact for a model the worker cannot
 * actually count; `localCounts` is keyed by model and only ever populated for
 * locally-countable ids.
 */

const utf8Bytes = (text: string) => new TextEncoder().encode(text).length;

export function usePlayground(): {
  state: PlaygroundState;
  dispatch: React.Dispatch<Action>;
  oversized: boolean;
  retry: () => void;
} {
  const [state, dispatch] = useReducer(reducer, initialState);

  // Refs so the effects below can read current values without re-subscribing.
  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);

  const oversized = useMemo(
    () => utf8Bytes(state.text) > LIMITS.maxTextBytes,
    [state.text],
  );

  // ---- warm-up ------------------------------------------------------------
  useEffect(() => {
    // Load the BPE table now, so the first keystroke is not the one that
    // waits several megabytes for it.
    getLocalTokenizer().prewarm();

    // Wake a sleeping backend while the visitor is still reading. On a
    // free-tier host a cold start can take tens of seconds, and paying that
    // on the first analyse call is the worst possible moment for it.
    // Fire-and-forget: the page is fully usable if this never resolves.
    if (!initialState.localOnly) {
      void fetch("/api/health", { method: "GET" }).catch(() => {
        // A sleeping or absent backend is an expected state, not an error.
        // Local OpenAI counts are unaffected either way.
      });
    }
  }, []);

  // ---- tier 1: local counts, every keystroke -----------------------------

  useEffect(() => {
    if (oversized) return;
    const tokenizer = getLocalTokenizer();
    const local = state.models.filter(isLocallyCountable);
    if (local.length === 0) return;

    let cancelled = false;
    for (const model of local) {
      void tokenizer.count(state.text, model).then((count) => {
        if (!cancelled && count) dispatch({ type: "localCount", model, count });
      });
    }
    return () => {
      cancelled = true;
    };
  }, [state.text, state.models, oversized]);

  // ---- tier 2: debounced server analysis ---------------------------------
  const runAnalyze = useCallback(
    async (snapshot: PlaygroundState, signal: AbortSignal) => {
      const body: AnalyzeRequest = {
        text: snapshot.text,
        models: snapshot.models,
        profile: snapshot.profile,
        rules: snapshot.ruleOverrides,
        // Offsets power the token map. Only the OpenAI family can supply
        // them, and the API says so in a warning for the others.
        include_offsets: true,
        include_segments: false,
        tokens_out: snapshot.tokensOut,
        calls_per_month: snapshot.callsPerMonth,
        cache_read_fraction: 0,
        cache_write_fraction: 0,
        batch_fraction: 0,
      };

      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });

      if (!response.ok) {
        let code = "internal_error";
        let message = `Request failed (${response.status}).`;
        try {
          const parsed = (await response.json()) as ApiErrorBody;
          if (parsed?.error) {
            code = parsed.error.code;
            message = parsed.error.message;
          }
        } catch {
          // Non-JSON error body; the defaults above are already sensible.
        }
        dispatch({ type: "analyzeError", code, message });
        return;
      }

      const data = (await response.json()) as AnalyzeResponse;
      dispatch({ type: "analyzeSuccess", text: snapshot.text, data });
    },
    [],
  );

  useEffect(() => {
    if (state.localOnly) return;
    if (oversized) return;
    if (state.text.trim().length === 0) return;

    const seq = ++requestSeq.current;
    const timer = setTimeout(() => {
      // Cancel whatever is still in flight — the user has moved on, and its
      // result is already obsolete.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      dispatch({ type: "analyzeStart" });
      void runAnalyze(state, controller.signal).catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (seq !== requestSeq.current) return;
        dispatch({
          type: "analyzeError",
          code: "network_error",
          message:
            error instanceof Error
              ? error.message
              : "Could not reach the analysis service.",
        });
      });
    }, LIMITS.debounceMs);

    return () => clearTimeout(timer);
    // Intentionally keyed on the request-shaping fields only. Including the
    // whole state object would refire on every UI-only change (tab switches,
    // expanded suggestions) and burn the rate limit for nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    state.text,
    state.models,
    state.profile,
    state.ruleOverrides,
    state.tokensOut,
    state.callsPerMonth,
    state.localOnly,
    oversized,
    runAnalyze,
  ]);

  // Abort in flight work on unmount so a late response cannot dispatch into
  // an unmounted tree.
  useEffect(() => () => abortRef.current?.abort(), []);

  const retry = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "analyzeStart" });
    void runAnalyze(state, controller.signal).catch(() => {
      dispatch({
        type: "analyzeError",
        code: "network_error",
        message: "Could not reach the analysis service.",
      });
    });
  }, [runAnalyze, state]);

  return { state, dispatch, oversized, retry };
}
