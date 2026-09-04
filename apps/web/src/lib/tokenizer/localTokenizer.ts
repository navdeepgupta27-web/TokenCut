import type { CountReply, CountRequest } from "@/lib/tokenizer/count.worker";

/**
 * Client-side handle on the tokenizer worker.
 *
 * Adapter pattern, mirroring the backend's tokenizer registry: the playground
 * asks "count this" and does not care whether the answer came from a local BPE
 * table or a keyed API. Swapping this for a WASM build later is a change to
 * this file alone.
 *
 * Degradation is a first-class path, not an error case. If workers are
 * unavailable — an old browser, a strict extension, a CSP we got wrong — every
 * method resolves to `null` and the UI falls back to the debounced server
 * count. The page stays usable either way.
 */

export interface LocalCount {
  tokens: number;
  encoding: string;
  /** False when the model id was inferred rather than known. */
  exactModelMatch: boolean;
}

type Pending = {
  resolve: (value: LocalCount | null) => void;
  reject: (reason: Error) => void;
};

export class LocalTokenizer {
  private worker: Worker | null = null;
  private readonly pending = new Map<number, Pending>();
  private nextId = 1;
  private failed = false;

  /** True once the worker has proven it cannot be used. */
  get unavailable(): boolean {
    return this.failed;
  }

  private ensureWorker(): Worker | null {
    if (this.failed) return null;
    if (this.worker) return this.worker;

    if (typeof window === "undefined" || typeof Worker === "undefined") {
      this.failed = true;
      return null;
    }

    try {
      const worker = new Worker(new URL("./count.worker.ts", import.meta.url), {
        type: "module",
      });

      worker.onmessage = (event: MessageEvent<CountReply>) => {
        const reply = event.data;
        const entry = this.pending.get(reply.id);
        if (!entry) return;
        this.pending.delete(reply.id);

        if (reply.ok) {
          entry.resolve({
            tokens: reply.tokens,
            encoding: reply.encoding,
            exactModelMatch: reply.exactModelMatch,
          });
        } else {
          entry.resolve(null);
        }
      };

      worker.onerror = () => {
        // Fail every in-flight request to null, then stop trying. A broken
        // worker must not leave promises hanging forever.
        this.failed = true;
        for (const entry of this.pending.values()) entry.resolve(null);
        this.pending.clear();
        this.worker?.terminate();
        this.worker = null;
      };

      this.worker = worker;
      return worker;
    } catch {
      this.failed = true;
      return null;
    }
  }

  /** Count `text` for `model`. Resolves to null when local counting is not possible. */
  count(text: string, model: string): Promise<LocalCount | null> {
    const worker = this.ensureWorker();
    if (!worker) return Promise.resolve(null);

    const id = this.nextId++;
    const request: CountRequest = { id, text, model };

    return new Promise<LocalCount | null>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      worker.postMessage(request);
    });
  }

  /** Warm the BPE table so the first keystroke is not the one that waits. */
  prewarm(model = "gpt-4o"): void {
    void this.count("", model);
  }

  dispose(): void {
    this.worker?.terminate();
    this.worker = null;
    this.pending.clear();
  }
}

let singleton: LocalTokenizer | null = null;

/** One worker per tab. Spawning one per component would load the BPE table repeatedly. */
export function getLocalTokenizer(): LocalTokenizer {
  singleton ??= new LocalTokenizer();
  return singleton;
}

/** Models this tokenizer can handle offline. Everything else needs the server. */
export function isLocallyCountable(model: string): boolean {
  const m = model.toLowerCase();
  return (
    m.startsWith("gpt-") ||
    m.startsWith("o1") ||
    m.startsWith("o3") ||
    m.startsWith("o4") ||
    m.startsWith("text-embedding")
  );
}
