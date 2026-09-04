import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Page not found",
  robots: { index: false, follow: true },
};

export default function NotFound(): ReactNode {
  return (
    <div className="mx-auto max-w-[46rem] px-4 py-24 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-3 text-sm text-[var(--text-muted)]">
        That URL does not exist. The tool is at{" "}
        <Link
          href="/playground"
          className="text-[var(--accent)] underline decoration-dotted underline-offset-4"
        >
          /playground
        </Link>
        .
      </p>
    </div>
  );
}
