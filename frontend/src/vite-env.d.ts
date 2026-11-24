/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Where the API lives, e.g. https://hff-api.onrender.com. No trailing slash needed. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
