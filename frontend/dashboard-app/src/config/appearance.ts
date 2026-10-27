// Appearance configuration. Deployment defaults come from VITE_* env vars at build
// time; each user's choices from the Appearance panel are saved in localStorage and
// win over the defaults. Everything is applied as attributes/tokens on <html>, so
// index.css is the only place that knows what they look like.

export type ThemeMode = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";
export type FontScale = "default" | "large";

export interface Appearance {
  theme: ThemeMode;
  accent: string;
  density: Density;
  fontScale: FontScale;
}

export const ACCENT_PRESETS: { name: string; value: string }[] = [
  { name: "Ocean", value: "#2563a8" },
  { name: "Teal", value: "#0f7c7a" },
  { name: "Indigo", value: "#4f46e5" },
  { name: "Forest", value: "#2f7d32" },
  { name: "Slate", value: "#475569" },
  { name: "Amber", value: "#b45309" },
];

const env = import.meta.env;
const HEX = /^#[0-9a-fA-F]{6}$/;

export const APP_TITLE: string = env.VITE_APP_TITLE || "Wind Turbine PdM";
export const APP_SUBTITLE: string = env.VITE_APP_SUBTITLE || "Predictive maintenance";

function pick<T extends string>(value: string | undefined, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

export const DEFAULT_APPEARANCE: Appearance = {
  theme: pick(env.VITE_DEFAULT_THEME, ["system", "light", "dark"] as const, "system"),
  accent: HEX.test(env.VITE_DEFAULT_ACCENT ?? "") ? env.VITE_DEFAULT_ACCENT! : ACCENT_PRESETS[0].value,
  density: pick(env.VITE_DEFAULT_DENSITY, ["comfortable", "compact"] as const, "comfortable"),
  fontScale: pick(env.VITE_DEFAULT_FONT_SCALE, ["default", "large"] as const, "default"),
};

const STORAGE_KEY = "wtb-pdm.appearance";

export function loadAppearance(): Appearance {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<Appearance>;
    return {
      theme: pick(saved.theme, ["system", "light", "dark"] as const, DEFAULT_APPEARANCE.theme),
      accent: HEX.test(saved.accent ?? "") ? saved.accent! : DEFAULT_APPEARANCE.accent,
      density: pick(saved.density, ["comfortable", "compact"] as const, DEFAULT_APPEARANCE.density),
      fontScale: pick(saved.fontScale, ["default", "large"] as const, DEFAULT_APPEARANCE.fontScale),
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function saveAppearance(a: Appearance): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(a));
  } catch {
    // Private mode / blocked storage: settings still apply for this session.
  }
}

export function applyAppearance(a: Appearance): void {
  const root = document.documentElement;
  if (a.theme === "system") delete root.dataset.theme;
  else root.dataset.theme = a.theme;
  if (a.density === "compact") root.dataset.density = "compact";
  else delete root.dataset.density;
  if (a.fontScale === "large") root.dataset.fontScale = "large";
  else delete root.dataset.fontScale;
  root.style.setProperty("--accent", a.accent);
}
