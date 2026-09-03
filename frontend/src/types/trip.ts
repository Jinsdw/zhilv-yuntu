import type { ISODate, ISODateTime } from './common'
import type { BudgetInfo } from './budget'
import type { BudgetLevel, TravelStyle, WeatherPreference } from './enums'
import type { ItineraryDay } from './itinerary'

/** 行程规划请求：与 schemas.TripRequest 对齐 */
export interface TripRequest {
  /** 目的地城市/地区（1-50 字符） */
  destination: string
  /** 行程开始日期 */
  start_date: ISODate
  /** 行程结束日期 */
  end_date: ISODate
  /** 出行人数（1-20） */
  travelers: number
  /** 预算等级 */
  budget_level: BudgetLevel
  /** 旅行风格偏好 */
  travel_style: TravelStyle
  /** 天气偏好 */
  weather_preference: WeatherPreference
  /** 是否携带儿童 */
  with_kids: boolean
  /** 是否携带老人 */
  with_elderly: boolean
  /** 是否有行动不便人员 */
  has_disability: boolean
  /** 是否包含室内景点 */
  include_indoor: boolean
  /** 是否包含室外景点 */
  include_outdoor: boolean
  /** 偏好关键词列表 */
  preferred_keywords: string[]
  /** 排除关键词列表 */
  excluded_keywords: string[]
  /** 每日预算上限（元） */
  daily_budget?: number | null
  /** 每日最多景点数（1-10） */
  max_places_per_day: number
  /** 每餐餐饮预算（元） */
  restaurant_budget_per_meal: number
}

/** 行程编辑请求：与 schemas.TripEditRequest 对齐 */
export interface TripEditRequest {
  /** 行程 ID */
  trip_id: string
  /** 第几天（1-based） */
  day_number: number
  /** 编辑指令（自然语言） */
  instruction: string
  /** 可选的攻略上下文 */
  context?: string | null
}

/** 行程规划响应：与 schemas.TripResponse 对齐 */
export interface TripResponse {
  /** 行程唯一标识 */
  trip_id: string
  /** 目的地 */
  destination: string
  /** 行程名称 */
  trip_name: string
  /** 开始日期 */
  start_date: ISODate
  /** 结束日期 */
  end_date: ISODate
  /** 总天数 */
  total_days: number
  /** 每日行程 */
  days: ItineraryDay[]
  /** 预算信息 */
  budget: BudgetInfo
  /** 总体评分（0-5） */
  overall_rating: number
  /** 行程亮点 */
  trip_highlights: string[]
  /** 行程贴士 */
  trip_tips: string[]
  /** 结构化分类行程贴士 */
  trip_tips_grouped?: TripTipCategory[]
  /** 特殊需求（同行状态）满足说明 */
  special_needs_notes?: string[]
  /** 天气出行建议（大模型基于天气预报生成） */
  weather_suggestions?: string[]
  /** 推荐美食 */
  recommended_foods: string[]
  /** 推荐购物 */
  recommended_shopping: string[]
  /** 紧急联系电话 */
  emergency_phone?: string | null
  /** 当地旅游热线 */
  local_tourism_hotline?: string | null
  /** 生成时间 */
  generated_at: ISODateTime
  /** 生成耗时（秒） */
  generation_time: number
  /** 使用的模型 */
  model_used?: string | null
  /** 行程版本 */
  version: string
  /** 附加元数据（token 统计、降级警告等） */
  metadata: Record<string, unknown>
}

/** 结构化行程贴士分类 */
export interface TripTipCategory {
  /** 贴士分类名称 */
  category: string
  /** 分类图标 emoji */
  icon: string
  /** 该分类下的贴士列表 */
  tips: string[]
}