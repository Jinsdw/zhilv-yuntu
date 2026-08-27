import { theme as antdTheme, type ThemeConfig } from 'antd'

/**
 * 智旅云图设计令牌
 *
 * 设计读法（design-taste-frontend）：消费者向 AI 旅行规划产品 UI，
 * 使用 Ant Design 5 作为设计系统；视觉语言沉稳海洋青，功能优先，动效克制。
 * 旋钮：VARIANCE 5 / MOTION 3 / DENSITY 5。
 *
 * 关键约定：
 * - 单一强调色（深海青 #0C7C7E），白字对比度约 5.0:1，满足 WCAG AA
 * - 圆角系统：控件 6px，大容器 12px，全站统一
 * - 明暗双模式由 darkAlgorithm / defaultAlgorithm 驱动
 */

/** 品牌色板 */
export const brand = {
  /** 主色：深海青 */
  primary: '#0C7C7E',
  /** 悬浮态 */
  primaryHover: '#1D8F91',
  /** 按压态 */
  primaryActive: '#0A6668',
  /** 装饰渐变（仅用于大面积背景，不承担文本对比度） */
  gradientFrom: '#0C7C7E',
  gradientTo: '#58BFC2',
}

/** 布局常量 */
export const layout = {
  /** 内容区最大宽度（居中） */
  contentMaxWidth: 1180,
  /** 侧边栏宽度 */
  siderWidth: 216,
  /** 折叠后侧边栏宽度 */
  siderCollapsedWidth: 64,
} as const

/** 根据明暗模式构建 antd 主题 */
export function buildTheme(dark: boolean): ThemeConfig {
  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: brand.primary,
      colorInfo: brand.primary,
      colorLink: brand.primary,
      colorLinkHover: brand.primaryHover,
      colorLinkActive: brand.primaryActive,
      borderRadius: 6,
      borderRadiusLG: 12,
      fontSize: 14,
      fontFamily: [
        '-apple-system',
        'BlinkMacSystemFont',
        'Segoe UI',
        'Roboto',
        'PingFang SC',
        'Hiragino Sans GB',
        'Microsoft YaHei',
        'Helvetica Neue',
        'Arial',
        'sans-serif',
      ].join(','),
    },
    components: {
      Menu: {
        itemBorderRadius: 8,
      },
      Card: {
        borderRadiusLG: 12,
      },
      Statistic: {
        contentFontSize: 24,
      },
    },
  }
}