/**
 * API 公共类型：与 backend main.py 异常处理器及 schemas 对齐
 */

/** 后端错误响应体（全局异常处理器统一格式） */
export interface ApiErrorBody {
  /** 错误代码 */
  error_code: string
  /** 错误信息 */
  error_message: string
  /** 错误详情 */
  error_details?: Record<string, unknown> | null
  /** 错误发生时间 */
  timestamp: string
  /** 请求 ID */
  request_id?: string | null
}

/** 后端已定义的错误码，便于前端分支处理 */
export const ApiErrorCode = {
  CITY_NOT_SUPPORTED: 'CITY_NOT_SUPPORTED',
  TRIP_NOT_FOUND: 'TRIP_NOT_FOUND',
  TRIP_SERVICE_ERROR: 'TRIP_SERVICE_ERROR',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  HTTP_ERROR: 'HTTP_ERROR',
} as const

export type ApiErrorCode = (typeof ApiErrorCode)[keyof typeof ApiErrorCode]

/** 健康检查响应：与 schemas.HealthCheckResponse 对齐 */
export interface HealthCheckResponse {
  status: string
  version: string
  uptime: number
  dependencies: Record<string, string>
}

/** 分页查询参数（GET /trip/history） */
export interface PaginationQuery {
  limit?: number
  offset?: number
}

/** 列表分页响应骨架 */
export interface Paginated<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}