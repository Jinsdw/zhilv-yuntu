import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // loadEnv 读取 .env.development / .env.production（前缀 VITE_）
  const env = loadEnv(mode, process.cwd(), '')

  // 高德 JSAPI 密钥从项目根 .env 读取（AMAP_JS_API_KEY / AMAP_SECURITY_JS_CODE），
  // 经 define 注入前端常量 __AMAP_JS_API_KEY__ / __AMAP_SECURITY_JS_CODE__。
  // 注：Vite 只默认注入 VITE_ 前缀变量，根 .env 的 AMAP_* 需手动桥接。
  const rootEnv = loadEnv(mode, fileURLToPath(new URL('..', import.meta.url)), '')

  return {
    plugins: [react()],
    define: {
      __AMAP_JS_API_KEY__: JSON.stringify(rootEnv.AMAP_JS_API_KEY ?? ''),
      __AMAP_SECURITY_JS_CODE__: JSON.stringify(rootEnv.AMAP_SECURITY_JS_CODE ?? ''),
    },
    resolve: {
      alias: {
        // 路径别名：@/ 指向 src/，配合 tsconfig.app.json 的 paths
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: Number(env.VITE_DEV_PORT ?? 5173),
      // 开发代理：前端同源请求直接转发到后端 FastAPI（默认 http://localhost:8000），
      // 免跨域、免 Nginx。生产部署时由网关/Nginx 统一转发。
      proxy: {
        '/trip': {
          target: env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
          changeOrigin: true,
        },
        '/weather': {
          target: env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
          changeOrigin: true,
        },
        '/export': {
          target: env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
          changeOrigin: true,
        },
        '/health': {
          target: env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      // 本项目组件拆分粒度细，适度调高告警阈值便于观察真实告警
      chunkSizeWarningLimit: 800,
    },
  }
})