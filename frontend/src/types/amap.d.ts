/**
 * 高德 JSAPI 相关类型补充声明
 *
 * 1. @amap/amap-jsapi-loader 官方类型（index.d.ts）仅具名导出 load，但运行时为
 *    UMD（module.exports = { load, reset }），官方文档用法是默认导入
 *    `import AMapLoader from '@amap/amap-jsapi-loader'`。此处补充 default 导出，
 *    与运行时和官方用法对齐（模块增强，与包内声明合并，不冲突）。
 * 2. window._AMapSecurityConfig：JSAPI v2.0 安全密钥全局配置，见
 *    .cursor/skills/amap-jsapi-skill/references/security.md。
 */

declare module '@amap/amap-jsapi-loader' {
  interface AMapLoaderOptions {
    /** 申请好的 Web 端开发者 Key（首次调用必填） */
    key: string
    /** 要加载的 JSAPI 版本（本项目固定 2.0） */
    version: string
    /** 需要预加载的插件列表，如 ['AMap.Scale', 'AMap.Driving'] */
    plugins?: string[]
    /** AMapUI 组件库配置（本项目未使用） */
    AMapUI?: { version?: string; plugins?: string[] }
    /** Loca 数据可视化库配置（本项目未使用） */
    Loca?: { version?: string }
  }

  interface AMapLoaderInstance {
    /** 异步加载 JSAPI，resolve 后返回 AMap 命名空间 */
    load(options: AMapLoaderOptions): Promise<any>
    /** 重置加载器状态（清空 window.AMap 等） */
    reset(): void
  }

  const AMapLoader: AMapLoaderInstance
  export default AMapLoader
}

declare global {
  interface Window {
    /** 高德 JSAPI v2.0 安全密钥配置（必须在 AMapLoader.load 之前设置） */
    _AMapSecurityConfig?: {
      securityJsCode?: string
      serviceHost?: string
    }
  }
}

export {}
