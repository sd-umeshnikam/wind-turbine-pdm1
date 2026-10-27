/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APPSYNC_URL?: string;
  readonly VITE_APPSYNC_API_KEY?: string;
  readonly VITE_CHAT_URL?: string;
  // Branding and appearance defaults (users can override in the Appearance panel).
  readonly VITE_APP_TITLE?: string;
  readonly VITE_APP_SUBTITLE?: string;
  readonly VITE_DEFAULT_THEME?: "system" | "light" | "dark";
  readonly VITE_DEFAULT_ACCENT?: string;
  readonly VITE_DEFAULT_DENSITY?: "comfortable" | "compact";
  readonly VITE_DEFAULT_FONT_SCALE?: "default" | "large";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
