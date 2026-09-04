import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { TOOL_PAGES, getToolPage } from "@/content/tools";
import { JsonLd, breadcrumbSchema, faqSchema } from "@/lib/seo/jsonld";

/**
 * Programmatic SEO routes — the pages that actually earn organic traffic.
 *
 * Fully static: `generateStaticParams` prerenders every slug at build time, so
 * each one is HTML on a CDN with no client JavaScript and no API dependency.
 * That is the whole point of splitting these from the playground.
 */

export const dynamicParams = false; // an unknown slug 404s rather than rendering

export function generateStaticParams(): { slug: string }[] {
  return TOOL_PAGES.map((page) => ({ slug: page.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = getToolPage(slug);
  if (!page) return { title: "Not found", robots: { index: false, follow: false } };

  const path = `/tools/${page.slug}`;
  return {
    title: page.title,
    description: page.description,
    // Explicit canonical per page. Without it, query-string variants of the
    // same URL get indexed separately and split their own ranking signal.
    alternates: { canonical: path },
    openGraph: {
      type: "article",
      title: page.title,
      description: page.description,
      url: path,
    },
    twitter: { card: "summary_large_image", title: page.title, description: page.description },
  };
}

export default async function ToolPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<ReactNode> {
  const { slug } = await params;
  const page = getToolPage(slug);
  if (!page) notFound();

  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <article className="mx-auto max-w-[46rem] px-4 py-14 sm:px-6">
      <JsonLd data={faqSchema(page.faq)} nonce={nonce} />
      <JsonLd
        data={breadcrumbSchema([
          { name: "Home", path: "/" },
          { name: page.h1, path: `/tools/${page.slug}` },
        ])}
        nonce={nonce}
      />

      <nav aria-label="Breadcrumb" className="mb-6 text-xs text-[var(--text-faint)]">
        <Link href="/" className="hover:text-[var(--text-muted)]">
          Home
        </Link>
        <span aria-hidden> / </span>
        <span className="text-[var(--text-muted)]">{page.h1}</span>
      </nav>

      <h1 className="text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
        {page.h1}
      </h1>

      {/* The query gets answered here, above the fold, before any CTA. A page
          that withholds the answer to force a click loses the click. */}
      <p className="mt-5 text-base leading-relaxed text-[var(--text-muted)]">
        {page.answer}
      </p>

      <div className="mt-7 flex flex-wrap gap-3">
        <Link
          href="/playground"
          className="inline-flex items-center rounded-[var(--radius-control)] bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-[var(--accent-fg)] transition-colors hover:bg-[var(--accent-hover)]"
        >
          Open the playground
        </Link>
      </div>

      {page.sections.map((section) => (
        <section key={section.heading} className="mt-11">
          <h2 className="text-lg font-semibold tracking-tight">{section.heading}</h2>
          {section.body.map((paragraph) => (
            <p
              key={paragraph.slice(0, 40)}
              className="mt-3 text-sm leading-relaxed text-[var(--text-muted)]"
            >
              {paragraph}
            </p>
          ))}
        </section>
      ))}

      <section className="mt-14 border-t pt-8">
        <h2 className="text-lg font-semibold tracking-tight">
          Frequently asked questions
        </h2>
        <dl className="mt-4 divide-y">
          {page.faq.map((item) => (
            <div key={item.q} className="py-4">
              <dt className="text-sm font-medium">{item.q}</dt>
              <dd className="mt-1.5 text-sm leading-relaxed text-[var(--text-muted)]">
                {item.a}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Internal linking: keeps crawl paths short and spreads authority
          between the guide pages instead of dead-ending each one. */}
      <section className="mt-12 border-t pt-8">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--text-muted)] uppercase">
          Related
        </h2>
        <ul className="mt-3 space-y-2">
          {TOOL_PAGES.filter((other) => other.slug !== page.slug).map((other) => (
            <li key={other.slug}>
              <Link
                href={`/tools/${other.slug}`}
                className="text-sm text-[var(--accent)] underline decoration-dotted underline-offset-4 hover:text-[var(--accent-hover)]"
              >
                {other.h1}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}
