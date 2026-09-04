import { theme as antdTheme, type ThemeConfig } from 'antd'

/**
 * 智旅云图设计令牌（v2 · 山海拾光）
 *
 * 设计读法（design-taste-frontend）：消费者向 AI 旅行规划产品重设计，
 * 以「温暖旅行编辑感 / 明信片杂志」视觉语言（奶油纸 + 陶土日出橙 + 暖墨 + 宋体衬线标题），
 * 反模板化：不追 AI 紫渐变、不做深色网格、不堆三张等宽卡片。
 * 旋钮：VARIANCE 7 / MOTION 4 / DENSITY 4。产品功能流程不变，仅焕新外壳与交互。
 *
 * 关键约定：
 * - 单一强调色（陶土日出橙 #C0472F），白字对比度约 5.0:1，满足 WCAG AA
 * - 标题用宋体衬线栈（系统字体，无 Web Font 加载成本），正文保持无衬线
 * - 圆角系统：控件 8px，大容器 16px，封面 20px，主 CTA 胶囊
 * - 明暗双模式由 darkAlgorithm / defaultAlgorithm 驱动
 */

/** 品牌色板 */
export const brand = {
  /** 主色：陶土日出橙（白字对比度约 5.0:1，AA） */
  primary: '#C0472F',
  /** 悬浮态 */
  primaryHover: '#D15B43',
  /** 按压态 */
  primaryActive: '#9C3723',
  /** 点缀金：评分 / 高亮（只表达语义，不承担主按钮） */
  gold: '#E8A33D',
  /** 辅助青绿：保留旧版海洋青基因，用于次级信息 */
  teal: '#2F7D7A',
  /** 浅色纸张底色（页面背景） */
  paper: '#FBF6EE',
  /** 浅色卡片表面 */
  paperCard: '#FFFDF8',
  /** 暖墨文本 */
  ink: '#2B2118',
  /** 装饰渐变（仅用于大面积背景与封面，不承担文本对比度） */
  gradientFrom: '#C0472F',
  gradientTo: '#E8A33D',
}

/** 布局常量 */
export const layout = {
  /** 内容区最大宽度（居中） */
  contentMaxWidth: 1180,
  /** 顶部导航高度 */
  headerHeight: 64,
} as const

/** 宋体衬线栈：标题用（旅行杂志编辑感），无 Web Font 加载成本 */
export const displayFont = [
  '"Noto Serif SC"',
  '"Source Han Serif SC"',
  '"Songti SC"',
  'STSong',
  'SimSun',
  'serif',
].join(',')

/** 根据明暗模式构建 antd 主题 */
export function buildTheme(dark: boolean): ThemeConfig {
  const warmBg = dark ? '#201A14' : brand.paper
  const warmContainer = dark ? '#2A221A' : brand.paperCard

  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: brand.primary,
      colorInfo: brand.primary,
      colorLink: brand.primary,
      colorLinkHover: brand.primaryHover,
      colorLinkActive: brand.primaryActive,
      colorBgLayout: warmBg,
      colorBgContainer: warmContainer,
      colorBgElevated: dark ? '#2A221A' : '#FFFDF8',
      colorText: dark ? '#F0E6D6' : brand.ink,
      borderRadius: 8,
      borderRadiusLG: 16,
      borderRadiusSM: 6,
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
        itemBorderRadius: 10,
        itemSelectedBg: dark ? 'rgba(192,71,47,0.22)' : 'rgba(192,71,47,0.10)',
        itemSelectedColor: dark ? '#FFB59E' : brand.primary,
        horizontalItemBorderRadius: 10,
      },
      Card: {
        borderRadiusLG: 16,
        boxShadowTertiary: '0 2px 14px rgba(43,33,24,0.06)',
      },
      Statistic: {
        contentFontSize: 28,
      },
      Button: {
        borderRadius: 10,
        controlHeightLG: 44,
        primaryShadow: '0 4px 12px rgba(192,71,47,0.28)',
      },
      Segmented: {
        borderRadius: 12,
        trackBg: dark ? 'rgba(255,255,255,0.06)' : 'rgba(192,71,47,0.06)',
        itemSelectedBg: dark ? '#3A2E22' : '#FFFFFF',
        itemSelectedColor: dark ? '#FFB59E' : brand.primary,
      },
      Tag: {
        borderRadiusSM: 6,
      },
      Tabs: {
        cardBg: 'transparent',
      },
      Timeline: {
        tailColor: dark ? 'rgba(240,230,214,0.18)' : 'rgba(192,71,47,0.18)',
      },
    },
  }
}
