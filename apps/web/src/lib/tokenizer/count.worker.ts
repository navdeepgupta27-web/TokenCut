/// <reference lib="webworker" />

import { Tiktoken } from "js-tiktoken/lite";

/**
 * Local OpenAI token counting, off the main thread.
 *
 * Scope is deliberately narrow: **counts only, no offsets.**
 *
 * Reconstructing per-token character offsets requires decoding each token id
 * back to *bytes*. `js-tiktoken` decodes to a JavaScript string, so a token
 * that ends mid-character comes back with a replacement char — decoding
 * "Hello, world! Café 🎉" one token at a time yields `" �" "�"` for the emoji.
 * Offsets built from that would be silently misaligned on any text containing
 * emoji, CJK, or Indic script.
 *
 * The Python backend does this correctly in byte space, so offsets come from
 * `/api/analyze` and this worker exists purely to make the counter feel
 * instant. That division is why the token map is trustworthy.
 *
 * The BPE tables are several megabytes, so they are fetched lazily on first
 * use and cached per encoding — nothing is downloaded until someone types.
 */

type EncodingName = "o200k_base" | "cl100k_base";

export interface CountRequest {
  id: number;
  text: string;
  model: string;
}

export type CountReply =
  | { id: number; ok: true; tokens: number; encoding: EncodingName; exactModelMatch: boolean }
  | { id: number; ok: false; error: string };

/**
 * Model -> encoding. Mirrors `resolve_encoding` in
 * `apps/api/app/services/tokenizer/openai_tiktoken.py`; keep the two in step.
 */
function encodingFor(model: string): { encoding: EncodingName; exact: boolean } {
  const m = model.toLowerCase();

  const exactMap: Record<string, EncodingName> = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
  };
  const hit = exactMap[m];
  if (hit) return { encoding: hit, exact: true };

  // Prefix inference for models newer than this table. Usually right, but
  // reported as inexact so the UI can say the count is unverified.
  if (m.startsWith("gpt-3.5") || m.startsWith("gpt-4-")) {
    return { encoding: "cl100k_base", exact: false };
  }
  return { encoding: "o200k_base", exact: false };
}

const encoders = new Map<EncodingName, Tiktoken>();
const loading = new Map<EncodingName, Promise<Tiktoken>>();

async function getEncoder(name: EncodingName): Promise<Tiktoken> {
  const ready = encoders.get(name);
  if (ready) return ready;

  const inFlight = loading.get(name);
  if (inFlight) return inFlight;

  const task = (async () => {
    const ranks =
      name === "o200k_base"
        ? (await import("js-tiktoken/ranks/o200k_base")).default
        : (await import("js-tiktoken/ranks/cl100k_base")).default;
    const encoder = new Tiktoken(ranks);
    encoders.set(name, encoder);
    loading.delete(name);
    return encoder;
  })();

  loading.set(name, task);
  return task;
}

self.onmessage = async (event: MessageEvent<CountRequest>) => {
  const { id, text, model } = event.data;

  try {
    const { encoding, exact } = encodingFor(model);
    const encoder = await getEncoder(encoding);
    const tokens = encoder.encode(text).length;

    const reply: CountReply = { id, ok: true, tokens, encoding, exactModelMatch: exact };
    self.postMessage(reply);
  } catch (error) {
    const reply: CountReply = {
      id,
      ok: false,
      error: error instanceof Error ? error.message : "tokenizer failed",
    };
    self.postMessage(reply);
  }
};
