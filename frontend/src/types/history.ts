import type { ISODate, ISODateTime } from './common'
import type { TripRequest, TripResponse } from './trip'

/** 完整行程历史记录：与 schemas.TripHistory 对齐 */
export interface TripHistory {
  /** 历史记录唯一标识 */
  history_id: string
  /** 用户 ID */
  user_id?: string | null
  /** 原始请求 */
  request: TripRequest
  /** 生成行程 */
  response: TripResponse
  /** 创建时间 */
  created_at: ISODateTime
  /** 最后访问时间 */
  accessed_at: ISODateTime
  /** 访问次数 */
  access_count: number
  /** 是否收藏 */
  is_favorite: boolean
  /** 是否已分享 */
  is_shared: boolean
  /** 分享码 */
  share_code?: string | null
  /** 用户评分（1-5） */
  user_rating?: number | null
  /** 用户反馈 */
  user_feedback?: string | null
  /** 已导出的格式 */
  exported_formats: string[]
}

/** 行程历史摘要（列表页轻量卡片）：与 schemas.TripHistorySummary 对齐 */
export interface TripHistorySummary {
  /** 行程 ID */
  id: string
  /** 用户 ID */
  user_id?: string | null
  /** 目的地 */
  destination: string
  /** 开始日期 */
  start_date: ISODate
  /** 结束日期 */
  end_date: ISODate
  /** 总天数 */
  total_days: number
  /** 总预算（元） */
  total_budget?: number | null
  /** 创建时间 */
  created_at: ISODateTime
  /** 更新时间 */
  updated_at: ISODateTime
  /** 是否收藏 */
  is_favorite: boolean
  /** 是否已分享 */
  is_shared: boolean
  /** 分享码 */
  share_code?: string | null
  /** 访问次数 */
  access_count: number
  /** 用户评分 */
  user_rating?: number | null
  /** 使用的模型 */
  model_used?: string | null
  /** 生成耗时（秒） */
  generation_time?: number | null
}

/** 行程历史分页响应：与 schemas.TripHistoryListResponse 对齐 */
export interface TripHistoryListResponse {
  /** 行程摘要列表 */
  items: TripHistorySummary[]
  /** 总记录数 */
  total: number
  /** 每页数量 */
  limit: number
  /** 偏移量 */
  offset: number
}