import type { ISODate } from './common'
import type { HotelInfo, PlaceInfo, RestaurantInfo } from './place'
import type { TransportationInfo } from './transport'
import type { WeatherInfo } from './weather'

/** 行程项目（单个景点/餐厅）：与 schemas.ItineraryItem 对齐 */
export interface ItineraryItem {
  /** 开始时间（HH:mm） */
  start_time: string
  /** 结束时间（HH:mm） */
  end_time: string
  /** 地点信息 */
  place: PlaceInfo
  /** 活动描述 */
  activity: string
  /** 活动详情 */
  activity_detail?: string | null
  /** 到达交通（从上一站到本站） */
  arrival_transport?: TransportationInfo | null
  /** 门票费用（元） */
  ticket_price?: number | null
  /** 餐饮费用（元） */
  food_cost?: number | null
  /** 游览提示 */
  tips: string[]
  /** 游览亮点 */
  highlights: string[]
  /** 是否需要预约 */
  booking_required: boolean
  /** 预约链接 */
  booking_url?: string | null
  /** 推荐拍照点 */
  photo_spot?: string | null
}

/** 每日行程：与 schemas.ItineraryDay 对齐 */
export interface ItineraryDay {
  /** 第几天 */
  day_number: number
  /** 日期 */
  itinerary_date: ISODate
  /** 当日主题（文化之旅等） */
  day_theme?: string | null
  /** 当天天气 */
  weather?: WeatherInfo | null
  /** 行程项目列表 */
  items: ItineraryItem[]
  /** 总景点数 */
  total_places: number
  /** 总行程距离（公里） */
  total_distance?: number | null
  /** 总游览时长（分钟） */
  total_duration: number
  /** 当日总费用（元） */
  daily_cost: number
  /** 费用明细 */
  cost_breakdown: Record<string, number>
  /** 当日综合评分（0-5） */
  total_rating: number
  /** 当日小贴士 */
  daily_tips: string[]
  /** 早餐餐厅 */
  breakfast?: RestaurantInfo | null
  /** 午餐餐厅 */
  lunch?: RestaurantInfo | null
  /** 晚餐餐厅 */
  dinner?: RestaurantInfo | null
  /** 住宿酒店 */
  hotel?: HotelInfo | null
}