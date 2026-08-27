/**
 * 枚举选项与文案映射集中管理（DESIGN.md §4：枚举选项中文 label 集中为常量，不在组件内散落）
 * 取值与 backend/app/models/schemas.py 的 Enum 定义对齐
 */

import type { BudgetLevel, BudgetStatus, CityLevel, TravelStyle, WeatherPreference } from '@/types'

/** 沉淀城市（后端城市分级 A 级）：点击可快捷填入表单 */
export const PRESET_CITIES = ['北京', '大理', '成都', '西安', '厦门', '三亚'] as const

/** 旅行风格中文映射 */
export const TRAVEL_STYLE_LABEL: Record<TravelStyle, string> = {
  relaxed: '休闲度假',
  compact: '紧凑高效',
  adventure: '探险挑战',
  cultural: '文化体验',
  foodie: '美食之旅',
}

/** 旅行风格选项（Segmented 用） */
export const TRAVEL_STYLE_OPTIONS = (Object.keys(TRAVEL_STYLE_LABEL) as TravelStyle[]).map((value) => ({
  value,
  label: TRAVEL_STYLE_LABEL[value],
}))

/** 预算等级中文映射 */
export const BUDGET_LEVEL_LABEL: Record<BudgetLevel, string> = {
  economy: '经济实惠',
  standard: '标准适中',
  luxury: '豪华享受',
}

/** 预算等级选项（Select 用） */
export const BUDGET_LEVEL_OPTIONS = (Object.keys(BUDGET_LEVEL_LABEL) as BudgetLevel[]).map((value) => ({
  value,
  label: BUDGET_LEVEL_LABEL[value],
}))

/** 天气偏好中文映射 */
export const WEATHER_PREFERENCE_LABEL: Record<WeatherPreference, string> = {
  no_preference: '无偏好',
  sunny: '偏好晴天',
  cool: '偏好凉爽',
}

/** 天气偏好选项（Select 用） */
export const WEATHER_PREFERENCE_OPTIONS = (Object.keys(WEATHER_PREFERENCE_LABEL) as WeatherPreference[]).map(
  (value) => ({
    value,
    label: WEATHER_PREFERENCE_LABEL[value],
  }),
)

/** 预算状态展示（Tag 颜色 + 文案） */
export const BUDGET_STATUS_META: Record<BudgetStatus, { label: string; color: string }> = {
  within_budget: { label: '预算内', color: 'success' },
  saved: { label: '已节省', color: 'gold' },
  over_budget: { label: '超预算', color: 'error' },
}

/** 城市分级展示（目的地下的提示 Tag） */
export const CITY_LEVEL_META: Record<CityLevel, { label: string; color: string; hint: string }> = {
  A: { label: 'A级 · 沉淀城市', color: 'cyan', hint: '使用本地深度攻略生成' },
  B: { label: 'B级 · 动态城市', color: 'blue', hint: '通过高德 POI 实时检索' },
  C: { label: 'C级 · 暂不支持', color: 'red', hint: '省级或无法识别，请尝试具体城市' },
}

/** AutoComplete 候选城市（沉淀城市 + 热门目的地） */
export const COMMON_CITIES = [
  '北京',
  '大理',
  '成都',
  '西安',
  '厦门',
  '三亚',
  '上海',
  '广州',
  '深圳',
  '杭州',
  '南京',
  '苏州',
  '重庆',
  '天津',
  '武汉',
  '长沙',
  '昆明',
  '桂林',
  '青岛',
  '大连',
  '哈尔滨',
  '沈阳',
  '郑州',
  '济南',
  '合肥',
  '福州',
  '南宁',
  '贵阳',
  '兰州',
  '乌鲁木齐',
  '拉萨',
  '西宁',
  '银川',
  '呼和浩特',
  '海口',
  '珠海',
  '无锡',
  '宁波',
]

/** 前端轻量预估城市分级（最终以后端解析为准）：A 沉淀 / C 省级目的地，其余按 B 处理 */
export function estimateCityLevel(city: string): CityLevel {
  const name = city.trim()
  if (!name) return 'B'
  if ((PRESET_CITIES as readonly string[]).includes(name)) return 'A'
  if (/(省|自治区|特别行政区)$/.test(name)) return 'C'
  return 'B'
}