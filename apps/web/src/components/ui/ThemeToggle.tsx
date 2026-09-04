"use client";

import clsx from "clsx";
import { useSyncExternalStore } from "react";
import type { ReactNode } from "react";

/**
 * Three-state theme control: Auto / Light / Dark.
 *
 * "Auto" is a real state, not the absence of a choice. It removes the
 * `data-theme` attribute so `prefers-color-scheme` decides, which is what the
 * CSS in globals.css is built around.
 *
 * Implemented with `useSyncExternalStore` rather than `useState` + `useEffect`.
 * The theme genuinely *is* external state — it lives on `<html data-theme>`,
 * is written by the pre-paint script in layout.tsx before React exists, and
 * can be changed by another tab. Mirroring it into component state would mean
 * a setState inside an effect on every mount (a cascading render), and would
 * silently drift whenever the external value changed underneath.
 *
 * The bonus is cross-tab sync for free, via the `storage` event.
 */

type Choice = "system" | "light" | "dark";

const STORAGE_KEY = "tokencut-theme";
const CHANGE_EVENT = "tokencut:themechange";

const OPTIONS: { id: Choice; label: string; hint: string }[] = [
  { id: "system", label: "Auto", hint: "Follow the operating system" },
  { id: "light", label: "Light", hint: "Always light" },
  { id: "dark", label: "Dark", hint: "Always dark" },
];

/** Read the live value off the DOM — the single source of truth. */
function getSnapshot(): Choice {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "light" || attr === "dark" ? attr : "system";
}

/**
 * Server snapshot. Always "system": the server cannot know the visitor's
 * choice, and guessing would produce a hydration mismatch. The pre-paint
 * script has already applied the correct colours by the time React hydrates,
 * so only this control's own highlight settles a frame late — never the page.
 */
function getServerSnapshot(): Choice {
  return "system";
}

function subscribe(onChange: () => void): () => void {
  // Same-tab changes (our own buttons) and other-tab changes (storage event).
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function apply(choice: Choice): void {
  const root = document.documentElement;
  if (choice === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", choice);
  }

  try {
    if (choice === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Private mode, or site data blocked. The choice still applies to this
    // page view; it just will not survive a reload.
  }

  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function ThemeToggle(): ReactNode {
  const choice = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex items-center gap-0.5 rounded-full border bg-[var(--bg-sunken)] p-0.5"
    >
      {OPTIONS.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={choice === option.id}
          title={option.hint}
          onClick={() => apply(option.id)}
          className={clsx(
            "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
            choice === option.id
              ? "bg-[var(--bg-raised)] text-[var(--text)] shadow-sm"
              : "text-[var(--text-muted)] hover:text-[var(--text)]",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
