/**
 * 路由路径常量：从 router/index.tsx 单独抽出，
 * 避免被 layouts/AppLayout.tsx 引用时触发循环依赖。
 */
export const ROUTES = {
  home: '/home',
  result: '/result',
  history: '/history',
} as const