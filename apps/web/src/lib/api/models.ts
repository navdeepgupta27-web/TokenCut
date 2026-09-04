import "server-only";

import { apiRequest } from "@/lib/api/server";
import type { ModelInfo, ModelsResponse } from "@/lib/api/types";

/**
 * Model catalog for Server Components.
 *
 * The fallback below is not defensive padding — it is load-bearing. `next build`
 * statically renders these routes, so if the catalog came only from a live API
 * call then a sleeping free-tier backend would fail the deploy. With the
 * fallback, the site builds and serves whether or not the API is up; the
 * catalog is simply less complete until it revalidates.
 *
 * Fallback entries carry NO prices. A model with no verified price renders no
 * cost figure at all, which is the correct behaviour here — inventing prices to
 * fill a fallback would be exactly the failure this product exists to avoid.
 */

const FALLBACK_MODELS: ModelInfo[] = [
  {
    id: "gpt-4o",
    provider: "openai",
    display_name: "GPT-4o",
    context_window: null,
    tokenizer: "tiktoken/o200k_base",
    supports_offsets: true,
    counting: "offline",
    available: true,
    unavailable_reason: null,
    input_per_mtok: null,
    output_per_mtok: null,
    pricing_source_url: null,
    pricing_retrieved_at: null,
    pricing_verified: false,
  },
  {
    id: "claude-opus-5",
    provider: "anthropic",
    display_name: "Claude Opus 5",
    context_window: null,
    tokenizer: "anthropic_count_tokens_api",
    supports_offsets: false,
    counting: "api",
    available: true,
    unavailable_reason: null,
    input_per_mtok: null,
    output_per_mtok: null,
    pricing_source_url: null,
    pricing_retrieved_at: null,
    pricing_verified: false,
  },
];

export async function getModels(): Promise<{
  models: ModelInfo[];
  degraded: boolean;
  pricingStale: boolean;
}> {
  try {
    const data = await apiRequest<ModelsResponse>("/v1/models", {
      // Revalidate hourly. The catalog changes when a model or a price is
      // added, which is a human-scale event, not a per-request one.
      revalidate: 3600,
    });
    return {
      models: data.models,
      degraded: false,
      pricingStale: data.pricing_stale,
    };
  } catch {
    return { models: FALLBACK_MODELS, degraded: true, pricingStale: false };
  }
}
