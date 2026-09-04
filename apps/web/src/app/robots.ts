import type { MetadataRoute } from "next";

import { SITE } from "@/lib/config";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // /api/* is the BFF proxy — POST-only and useless to a crawler.
        // /playground is noindex; disallowing it too saves crawl budget that
        // is better spent on the guide pages.
        disallow: ["/api/", "/playground"],
      },
    ],
    sitemap: `${SITE.url}/sitemap.xml`,
    host: SITE.url,
  };
}
