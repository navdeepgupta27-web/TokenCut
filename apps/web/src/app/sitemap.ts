import type { MetadataRoute } from "next";

import { TOOL_PAGES } from "@/content/tools";
import { SITE } from "@/lib/config";

/**
 * Sitemap.
 *
 * `/playground` is deliberately absent: it is `noindex`, and listing a
 * noindex URL in a sitemap is a contradiction crawlers report as an error.
 * Only pages we actually want indexed belong here.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();

  return [
    {
      url: `${SITE.url}/`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1,
    },
    ...TOOL_PAGES.map((page) => ({
      url: `${SITE.url}/tools/${page.slug}`,
      lastModified: now,
      changeFrequency: "monthly" as const,
      priority: 0.8,
    })),
  ];
}
