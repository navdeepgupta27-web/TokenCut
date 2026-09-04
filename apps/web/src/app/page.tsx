import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/primitives";
import { TOOL_PAGES } from "@/content/tools";
import { SITE } from "@/lib/config";
import { getModels } from "@/lib/api/models";

/**
 * Landing page. A Server Component with zero client JavaScript.
 *
 * This is the page that has to rank, so it is fully static HTML: the content
 * is in the markup, not assembled after hydration. The playground is one link
 * away rather than embedded, which keeps this route's bundle at nothing.
 */

// Statically generated, revalidated hourly so the model table does not go stale.
export const revalidate = 3600;

const CLAIMS = [
  {
    title: "Exact, not approximated",
    body:
      "OpenAI counts run in your browser with the model's own tokenizer. Claude and Gemini counts come from the providers' own counting endpoints, which cost nothing in tokens. Anything we could not measure is labelled as an estimate.",
  },
  {
    title: "Every number shows its work",
    body:
      "A count is either exact, marked ≈ as an estimate, or shown as — when it cannot be obtained. A cost figure always lists the assumptions behind it. Models with no verified published price get no dollar figure at all.",
  },
  {
    title: "Lossless first, suggestions second",
    body:
      "Whitespace, Unicode and JSON cleanups are provably information-preserving, so they are applied. Anything that could change how the model behaves is offered with its risk stated — never applied behind your back.",
  },
  {
    title: "Your code is protected",
    body:
      "Code fences, JSON string literals, URLs and template variables are classified before any rule runs, and no cleanup is allowed to touch them. Corrupting a prompt to save four tokens is not optimization.",
  },
];

export default async function HomePage(): Promise<ReactNode> {
  const { models } = await getModels();
  const priced = models.filter((m) => m.pricing_verified);

  return (
    <div className="mx-auto max-w-[1100px] px-4 sm:px-6">
      {/* ---------------------------- hero ---------------------------- */}
      <section className="py-16 sm:py-24">
        <h1 className="max-w-3xl text-4xl leading-[1.1] font-semibold tracking-tight sm:text-5xl">
          Count tokens accurately.
          <br />
          <span className="text-[var(--text-muted)]">Cut your LLM bill honestly.</span>
        </h1>

        <p className="mt-6 max-w-2xl text-base leading-relaxed text-[var(--text-muted)]">
          Most token counters run OpenAI&apos;s tokenizer against every model and
          call it a day — which undercounts Claude by roughly 15–20% on ordinary
          prose, and by more on code. {SITE.name} counts each model with its own
          tokenizer, shows you which parts of a prompt cost the most, and cuts the
          waste without quietly changing what your prompt means.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/playground"
            className="inline-flex items-center rounded-[var(--radius-control)] bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-[var(--accent-fg)] transition-colors hover:bg-[var(--accent-hover)]"
          >
            Open the playground
          </Link>
          <Link
            href="/tools/reduce-openai-api-bill"
            className="inline-flex items-center rounded-[var(--radius-control)] border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--bg-hover)]"
          >
            How to cut an API bill
          </Link>
        </div>

        <p className="mt-4 text-xs text-[var(--text-faint)]">
          No sign-up. No prompt logging. OpenAI counts never leave your browser.
        </p>
      </section>

      {/* --------------------------- claims --------------------------- */}
      <section className="grid gap-4 pb-16 sm:grid-cols-2">
        <h2 className="sr-only">What makes this different</h2>
        {CLAIMS.map((claim) => (
          <Card key={claim.title} className="p-5">
            <h3 className="text-sm font-semibold">{claim.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-[var(--text-muted)]">
              {claim.body}
            </p>
          </Card>
        ))}
      </section>

      {/* --------------------------- models --------------------------- */}
      <section className="pb-16">
        <h2 className="text-xl font-semibold tracking-tight">Supported models</h2>
        <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
          Counting availability and pricing availability are separate facts, so
          both are shown. A model can be counted exactly while its price is not
          yet verified — in which case you get the token count and no cost figure.
        </p>

        <div className="mt-5 overflow-x-auto rounded-[var(--radius-card)] border">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="bg-[var(--bg-sunken)] text-left">
              <tr className="text-[10px] font-semibold tracking-wider text-[var(--text-faint)] uppercase">
                <th className="px-4 py-2.5">Model</th>
                <th className="px-4 py-2.5">Counting</th>
                <th className="px-4 py-2.5">Token map</th>
                <th className="px-4 py-2.5">Price on file</th>
              </tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.id} className="border-t">
                  <td className="px-4 py-2.5">{model.display_name}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {model.counting === "offline"
                      ? "In your browser"
                      : model.counting === "api"
                        ? "Provider endpoint"
                        : model.counting === "estimate_only"
                          ? "Estimate only"
                          : "Unavailable"}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {model.supports_offsets ? "Yes" : "No"}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {model.pricing_verified ? (
                      model.pricing_retrieved_at
                    ) : (
                      <span className="text-[var(--text-faint)]">not verified</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {priced.length < models.length ? (
          <p className="mt-3 text-xs text-[var(--text-faint)]">
            Prices are only listed once read from the provider&apos;s official
            pricing page and dated. Until then the model works for counting and
            optimization, and shows no cost.
          </p>
        ) : null}
      </section>

      {/* --------------------------- guides --------------------------- */}
      <section className="pb-20">
        <h2 className="text-xl font-semibold tracking-tight">Guides</h2>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {TOOL_PAGES.map((page) => (
            <Link
              key={page.slug}
              href={`/tools/${page.slug}`}
              className="rounded-[var(--radius-card)] border bg-[var(--bg-raised)] p-5 transition-colors hover:bg-[var(--bg-hover)]"
            >
              <h3 className="text-sm font-semibold">{page.h1}</h3>
              <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-[var(--text-muted)]">
                {page.answer}
              </p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
