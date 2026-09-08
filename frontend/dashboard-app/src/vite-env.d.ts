/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APPSYNC_URL?: string;
  readonly VITE_APPSYNC_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
