"use client";

import { useCallback, useSyncExternalStore } from "react";
import { THEME_KEY } from "./theme-script";

/** Light or dark mode (SC-07). The choice is kept in this browser (localStorage) and applied as
 * data-theme on <html>, which switches the neutral colour tokens in globals.css. Light is the
 * default. ThemeScript (theme-script.tsx) applies a saved choice before the first paint. */
export type Theme = "light" | "dark";

const listeners = new Set<() => void>();

function current(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_KEY) return;
    apply(event.newValue === "dark" ? "dark" : "light", false);
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function apply(theme: Theme, save: boolean) {
  const html = document.documentElement;
  if (theme === "dark") html.dataset.theme = "dark";
  else delete html.dataset.theme;
  if (save) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Storage blocked (private mode): the choice lasts for this page only.
    }
  }
  listeners.forEach((l) => l());
}

/** The current theme and a toggle. The server renders light; the browser's value follows. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const theme = useSyncExternalStore(subscribe, current, () => "light" as Theme);
  const toggle = useCallback(() => apply(current() === "dark" ? "light" : "dark", true), []);
  return { theme, toggle };
}
