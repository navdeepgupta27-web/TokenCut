import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { SITE } from "@/lib/config";
import { JsonLd, softwareApplicationSchema } from "@/lib/seo/jsonld";

import "./globals.css";

/**
 * Root layout.
 *
 * `metadataBase` is what makes every relative canonical/OG URL in child routes
 * resolve to an absolute one. Without it Next emits relative OG tags, which
 * most crawlers and link unfurlers ignore.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE.url),
  title: {
    default: `${SITE.name} — ${SITE.tagline}`,
    template: `%s · ${SITE.name}`,
  },
  description: SITE.description,
  applicationName: SITE.name,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: SITE.name,
    title: `${SITE.name} — ${SITE.tagline}`,
    description: SITE.description,
    url: SITE.url,
  },
  twitter: {
    card: "summary_large_image",
    title: `${SITE.name} — ${SITE.tagline}`,
    description: SITE.description,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large" },
  },
  formatDetection: { telephone: false, address: false, email: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The metrics bar is the point of the page; let people zoom it.
  maximumScale: 5,
  colorScheme: "dark light",
};

/**
 * Applies a saved theme before first paint.
 *
 * Inline because it has to run before the browser paints — a deferred script
 * would produce a visible flash of the wrong theme. It carries the CSP nonce,
 * which is why this app can keep `script-src` free of 'unsafe-inline'.
 */
const themeScript = `
(function(){
  try {
    var saved = localStorage.getItem("tokencut-theme");
    if (saved === "dark" || saved === "light") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) {
    /* Private mode, or site data blocked. The OS preference still applies. */
  }
})();
`;

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}): Promise<ReactNode> {
  // Set by src/middleware.ts on the forwarded request.
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript }} />
        <JsonLd data={softwareApplicationSchema()} nonce={nonce} />
      </head>
      <body className="min-h-screen antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-[var(--bg-raised)] focus:px-3 focus:py-2 focus:text-sm"
        >
          Skip to content
        </a>

        <header className="border-b bg-[var(--bg)]">
          <nav
            aria-label="Main"
            className="mx-auto flex max-w-[1600px] items-center gap-6 px-4 py-3 sm:px-6"
          >
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span
                aria-hidden
                className="inline-block size-2.5 rounded-sm bg-[var(--accent)]"
              />
              {SITE.name}
            </Link>
            <div className="flex items-center gap-4 text-sm text-[var(--text-muted)]">
              <Link href="/playground" className="hover:text-[var(--text)]">
                Playground
              </Link>
              <Link href="/tools/claude-token-counter" className="hover:text-[var(--text)]">
                Guides
              </Link>
            </div>
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </nav>
        </header>

        <main id="main">{children}</main>

        <footer className="mt-16 border-t bg-[var(--bg)]">
          <div className="mx-auto flex max-w-[1600px] flex-col gap-3 px-4 py-8 text-xs text-[var(--text-faint)] sm:px-6">
            <p className="max-w-2xl leading-relaxed">
              {SITE.name} labels every number by how it was measured. Counts marked
              &ldquo;≈&rdquo; are estimates, not measurements, and models with no
              verified published price show no cost at all rather than a guess.
            </p>
            <p>
              Not affiliated with OpenAI, Anthropic or Google. Model names are the
              trademarks of their respective owners.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
