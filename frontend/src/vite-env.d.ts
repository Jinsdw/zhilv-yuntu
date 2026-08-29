/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_TITLE: string
  readonly VITE_API_BASE_URL: string
  readonly VITE_API_PROXY_TARGET: string
  readonly VITE_DEV_PORT: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** 高德 JS API Key：由 vite.config.ts define 从项目根 .env（AMAP_JS_API_KEY）注入 */
declare const __AMAP_JS_API_KEY__: string

/** 高德安全密钥：由 vite.config.ts define 从项目根 .env（AMAP_SECURITY_JS_CODE）注入 */
declare const __AMAP_SECURITY_JS_CODE__: string