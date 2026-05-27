/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Override: use this URL directly (skips local/production switch) */
  readonly VITE_API_BASE?: string;
  /** local | production — picks VITE_API_BASE_LOCAL or VITE_API_BASE_PRODUCTION */
  readonly VITE_API_TARGET?: string;
  readonly VITE_API_BASE_LOCAL?: string;
  readonly VITE_API_BASE_PRODUCTION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
