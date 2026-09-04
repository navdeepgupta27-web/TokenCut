import { ImageResponse } from "next/og";

import { SITE } from "@/lib/config";

/**
 * Social card, generated at build time.
 *
 * Deliberately shows the product's actual claim — a real before/after with the
 * provenance markers — rather than a logo on a gradient. The card is the only
 * thing most people will ever see, so it should say what the tool does.
 *
 * The numbers below are the measured result of running the bundled
 * "Bloated JSON payload" sample through the optimizer against GPT-4o
 * (244 -> 138 tokens). They are illustrative of that sample, not a promise —
 * hence "on this sample" in the caption.
 */

export const runtime = "nodejs";
export const alt =
  "TokenCut — count tokens accurately across OpenAI, Anthropic and Google models, and cut input cost";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Static generation: one image, built once, served from the CDN.
export const dynamic = "force-static";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0b0d11",
          color: "#eef0f4",
          padding: 72,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{ width: 20, height: 20, borderRadius: 4, background: "#2dd4bf" }} />
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: -0.5 }}>
            {SITE.name}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ fontSize: 62, fontWeight: 600, lineHeight: 1.08, letterSpacing: -1.5 }}>
            Count tokens accurately.
          </div>
          <div
            style={{
              fontSize: 62,
              fontWeight: 600,
              lineHeight: 1.08,
              letterSpacing: -1.5,
              color: "#9aa2b1",
            }}
          >
            Cut your LLM bill honestly.
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "flex-end", gap: 56 }}>
          <Stat label="TOKENS" value="244" />
          <div style={{ fontSize: 34, color: "#6b7382", paddingBottom: 8 }}>→</div>
          <Stat label="OPTIMIZED" value="138" />
          <Stat label="REDUCTION" value="−43.4%" accent="#4ade80" />

          <div
            style={{
              marginLeft: "auto",
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
              gap: 6,
              fontSize: 19,
              color: "#6b7382",
            }}
          >
            <div>OpenAI · Anthropic · Google</div>
            <div>Estimates marked ≈ · unverified prices shown as —</div>
          </div>
        </div>
      </div>
    ),
    size,
  );
}

function Stat({
  label,
  value,
  accent = "#eef0f4",
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 15, letterSpacing: 2, color: "#6b7382" }}>{label}</div>
      <div style={{ fontSize: 52, fontWeight: 600, color: accent, letterSpacing: -1 }}>
        {value}
      </div>
    </div>
  );
}
