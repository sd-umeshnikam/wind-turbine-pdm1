import { useEffect, useState, useSyncExternalStore } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "wtpdm.theme";

function read(): ThemeChoice {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function useThemeChoice(): [ThemeChoice, (t: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(read);
  useEffect(() => {
    const root = document.documentElement;
    if (choice === "system") delete root.dataset.theme;
    else root.dataset.theme = choice;
    try {
      if (choice === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      // storage blocked: the choice lasts for this page
    }
  }, [choice]);
  return [choice, setChoice];
}

const media = () => window.matchMedia("(prefers-color-scheme: dark)");

function subscribe(cb: () => void) {
  const m = media();
  m.addEventListener("change", cb);
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => {
    m.removeEventListener("change", cb);
    obs.disconnect();
  };
}

function isDark(): boolean {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : media().matches;
}

/** Effective theme, re-rendering when the OS setting or the toggle changes. */
export const useIsDark = () => useSyncExternalStore(subscribe, isDark);

/** Resolve CSS custom properties (for chart options, which need concrete colours). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
