"use client";

import { useEffect, useRef } from "react";
import { EditorState, StateEffect, StateField } from "@codemirror/state";
import {
  Decoration,
  type DecorationSet,
  EditorView,
  ViewPlugin,
  type ViewUpdate,
  keymap,
  placeholder as cmPlaceholder,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";

import { LIMITS } from "@/lib/config";

/**
 * The prompt editor, with the token map drawn as CodeMirror decorations.
 *
 * Why CodeMirror rather than a textarea with a highlight overlay: a span per
 * token is the obvious approach and it dies at scale — a 10k-token prompt is
 * 10k DOM nodes rebuilt on every keystroke. CodeMirror virtualises, so the
 * ViewPlugin below only ever builds decorations for the ranges currently on
 * screen, no matter how long the document is.
 *
 * Decorations arrive as offsets from the server, because only the OpenAI
 * family can produce true token boundaries and only the backend can compute
 * them correctly in byte space (see count.worker.ts for why not here).
 */

interface Spans {
  tokens: [number, number][] | null;
  suggestions: [number, number][];
}

const setSpans = StateEffect.define<Spans>();

const spansField = StateField.define<Spans>({
  create: () => ({ tokens: null, suggestions: [] }),
  update(value, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setSpans)) return effect.value;
    }
    // Offsets are computed against a specific document. The moment the user
    // types, they are wrong — drop them rather than render a misaligned map.
    if (tr.docChanged) return { tokens: null, suggestions: [] };
    return value;
  },
});

/** First index whose end is past `from`. Offsets are sorted, so bisect. */
function lowerBound(spans: [number, number][], from: number): number {
  let lo = 0;
  let hi = spans.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const span = spans[mid];
    if (span && span[1] <= from) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function buildDecorations(view: EditorView): DecorationSet {
  const { tokens, suggestions } = view.state.field(spansField);
  const docLength = view.state.doc.length;
  const ranges: { from: number; to: number; deco: Decoration }[] = [];

  if (tokens && tokens.length <= LIMITS.maxDecoratedTokens) {
    for (const { from, to } of view.visibleRanges) {
      for (let i = lowerBound(tokens, from); i < tokens.length; i++) {
        const span = tokens[i];
        if (!span) break;
        const [start, end] = span;
        if (start >= to) break;
        // Clamp: the document can be a character shorter than the offsets if
        // a response lands a beat late, and an out-of-range decoration throws.
        const a = Math.max(0, Math.min(start, docLength));
        const b = Math.max(a, Math.min(end, docLength));
        if (b > a) {
          ranges.push({
            from: a,
            to: b,
            deco: Decoration.mark({ class: `tok-${i % 4}` }),
          });
        }
      }
    }
  }

  for (const [start, end] of suggestions) {
    const a = Math.max(0, Math.min(start, docLength));
    const b = Math.max(a, Math.min(end, docLength));
    if (b > a) {
      ranges.push({ from: a, to: b, deco: Decoration.mark({ class: "suggest-span" }) });
    }
  }

  // CodeMirror requires ranges sorted by `from`, then by `to`.
  ranges.sort((x, y) => x.from - y.from || x.to - y.to);
  return Decoration.set(
    ranges.map((r) => r.deco.range(r.from, r.to)),
    true,
  );
}

const tokenMapPlugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;

    constructor(view: EditorView) {
      this.decorations = buildDecorations(view);
    }

    update(update: ViewUpdate) {
      // Rebuild on scroll too: virtualisation means new ranges become visible
      // without the document or the spans changing at all.
      if (
        update.docChanged ||
        update.viewportChanged ||
        update.transactions.some((tr) => tr.effects.some((e) => e.is(setSpans)))
      ) {
        this.decorations = buildDecorations(update.view);
      }
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

export function PromptEditor({
  value,
  onChange,
  tokenSpans,
  suggestionSpans,
  placeholder = "Paste a prompt, a system message, or a JSON payload…",
}: {
  value: string;
  onChange: (next: string) => void;
  tokenSpans: [number, number][] | null;
  suggestionSpans: [number, number][];
  placeholder?: string;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);

  // Kept in a ref so the CodeMirror update listener never needs
  // re-registering. Synced in an effect rather than during render: mutating a
  // ref while rendering is unsafe under concurrent React, which can render a
  // component without committing it.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const view = new EditorView({
      state: EditorState.create({
        doc: value,
        extensions: [
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          EditorView.lineWrapping,
          cmPlaceholder(placeholder),
          spansField,
          tokenMapPlugin,
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              onChangeRef.current(update.state.doc.toString());
            }
          }),
          EditorView.contentAttributes.of({
            "aria-label": "Prompt text",
            spellcheck: "false",
            autocapitalize: "off",
            autocorrect: "off",
          }),
        ],
      }),
      parent: host,
    });

    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Mount once. `value` is synced by the effect below, not by re-creating
    // the editor, which would destroy the cursor and undo history.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push external text changes in (sample loading, reset) without clobbering
  // the user's own typing.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value },
    });
  }, [value]);

  // Hand new decorations to the editor as an effect rather than rebuilding
  // state, so scroll position and selection survive.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: setSpans.of({ tokens: tokenSpans, suggestions: suggestionSpans }),
    });
  }, [tokenSpans, suggestionSpans]);

  return (
    <div
      ref={hostRef}
      className="h-full min-h-[18rem] overflow-auto rounded-[var(--radius-control)] border bg-[var(--bg-sunken)]"
    />
  );
}
