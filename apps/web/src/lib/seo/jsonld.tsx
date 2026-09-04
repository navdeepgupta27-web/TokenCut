import type { ReactNode } from "react";

import { SITE } from "@/lib/config";

/**
 * Structured data.
 *
 * `dangerouslySetInnerHTML` is used here, and this is the only place in the app
 * that touches it. That is safe because every value is authored by us in
 * `src/content/*` — none of it is user input — and it is escaped below anyway.
 *
 * If a JSON-LD field ever needs to carry user- or API-supplied text, escape it
 * the same way and re-read this comment before shipping.
 */

/**
 * Escape the sequences that can break out of a <script> element.
 *
 * `JSON.stringify` alone is not enough: a literal "</script>" inside a string
 * value would terminate the element and everything after it becomes markup.
 */
function safeJsonLd(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}

export function JsonLd({ data, nonce }: { data: unknown; nonce?: string }): ReactNode {
  return (
    <script
      type="application/ld+json"
      nonce={nonce}
      dangerouslySetInnerHTML={{ __html: safeJsonLd(data) }}
    />
  );
}

export function softwareApplicationSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: SITE.name,
    applicationCategory: "DeveloperApplication",
    operatingSystem: "Any",
    url: SITE.url,
    description: SITE.description,
    // A real, free tool. Do not add review or rating markup unless there are
    // genuine reviews to point at — fabricated ratings are a manual-action risk
    // and, more to the point, a lie.
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
    },
  };
}

export function faqSchema(faq: { q: string; a: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faq.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };
}

export function breadcrumbSchema(trail: { name: string; path: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: trail.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: `${SITE.url}${crumb.path}`,
    })),
  };
}
