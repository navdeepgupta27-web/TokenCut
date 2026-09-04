import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Playground } from "@/components/playground/Playground";
import { Note } from "@/components/ui/primitives";
import { getModels } from "@/lib/api/models";

/**
 * The tool.
 *
 * This route is honest about what it is: an interactive editor, which cannot be
 * usefully server-rendered. So it carries `robots: noindex` and the SEO work
 * happens on the static `/` and `/tools/*` routes instead. Trying to rank a
 * client island wastes crawl budget and produces a thin page.
 *
 * The Server Component shell still does real work: it fetches the model catalog
 * so the picker is correct in the first paint, with no client-side fetch and no
 * loading spinner on the primary control.
 */
export const metadata: Metadata = {
  title: "Playground",
  description:
    "Count tokens across OpenAI, Anthropic and Google models, see the token map, and cut input cost.",
  robots: { index: false, follow: true },
  alternates: { canonical: "/playground" },
};

export default async function PlaygroundPage(): Promise<ReactNode> {
  const { models, degraded } = await getModels();

  return (
    <>
      {degraded ? (
        <div className="mx-auto max-w-[1600px] px-4 pt-4 sm:px-6">
          <Note tone="warning" title="Running with a reduced model list">
            The analysis service did not respond, so this page is using a minimal
            built-in catalog. OpenAI counts still work — they run entirely in your
            browser. Claude and Gemini counts, the optimizer, and cost analysis
            need the service back.
          </Note>
        </div>
      ) : null}
      <Playground models={models} />
    </>
  );
}
