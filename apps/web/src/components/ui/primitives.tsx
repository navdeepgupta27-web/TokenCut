import clsx from "clsx";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

/**
 * Hand-rolled primitives rather than a component library.
 *
 * The surface here is small (six components), the CSP forbids CDN assets
 * anyway, and every dependency added to a page whose whole pitch is "we count
 * your bytes honestly" is a byte someone can point at. These are Server
 * Components by default — none of them holds state.
 */

export function Card({
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"div">): ReactNode {
  return (
    <div
      className={clsx(
        "rounded-[var(--radius-card)] border bg-[var(--bg-raised)]",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "secondary",
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"button"> & { variant?: ButtonVariant }): ReactNode {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)]",
        "px-3.5 py-2 text-sm font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" &&
          "bg-[var(--accent)] text-[var(--accent-fg)] hover:bg-[var(--accent-hover)]",
        variant === "secondary" &&
          "border bg-[var(--bg-raised)] text-[var(--text)] hover:bg-[var(--bg-hover)]",
        variant === "ghost" &&
          "text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text)]",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

type BadgeTone = "neutral" | "accent" | "positive" | "warning" | "danger";

const badgeTones: Record<BadgeTone, string> = {
  neutral: "bg-[var(--bg-sunken)] text-[var(--text-muted)] border-[var(--border)]",
  accent: "bg-[var(--accent-subtle)] text-[var(--accent)] border-transparent",
  positive: "bg-[var(--positive-subtle)] text-[var(--positive)] border-transparent",
  warning: "bg-[var(--warning-subtle)] text-[var(--warning)] border-transparent",
  danger: "bg-[var(--danger-subtle)] text-[var(--danger)] border-transparent",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}): ReactNode {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        badgeTones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Field({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
}): ReactNode {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={htmlFor}
        className="text-xs font-medium tracking-wide text-[var(--text-muted)] uppercase"
      >
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs text-[var(--text-faint)]">{hint}</p> : null}
    </div>
  );
}

export function NumberInput({
  className,
  ...rest
}: ComponentPropsWithoutRef<"input">): ReactNode {
  return (
    <input
      type="text"
      inputMode="numeric"
      className={clsx(
        "tnum w-full rounded-[var(--radius-control)] border bg-[var(--bg-sunken)]",
        "px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-faint)]",
        className,
      )}
      {...rest}
    />
  );
}

/**
 * A callout used for assumptions and warnings.
 *
 * This component gets used a lot, on purpose. Every number this product shows
 * that rests on an assumption has one of these next to it.
 */
export function Note({
  tone = "neutral",
  title,
  children,
}: {
  tone?: BadgeTone;
  title?: string;
  children: ReactNode;
}): ReactNode {
  return (
    <div
      className={clsx(
        "rounded-[var(--radius-control)] border px-3 py-2 text-xs leading-relaxed",
        badgeTones[tone],
      )}
    >
      {title ? <p className="mb-1 font-semibold">{title}</p> : null}
      {children}
    </div>
  );
}
