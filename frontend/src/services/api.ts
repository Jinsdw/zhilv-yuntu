/**
 * 智旅云图 - API 服务封装（Phase 8.2）
 *
 * 职责：统一 axios 实例 + 拦截器 + 各域接口封装，页面与组件只消费本文件，
 * 不直接触碰 axios。
 *
 * 设计要点（与 backend/app/api/main.py 路由注册及 DESIGN.md 第 5 节数据流对齐）：
 *     - baseURL 读取 VITE_API_BASE_URL：开发环境为空串 → 同源请求，由 vite dev
 *       server 代理转发到后端（见 vite.config.ts proxy）；生产由网关/Nginx 反代。
 *     - 响应拦截器：2xx 直接返回 response.data 解包；204 无内容返回 undefined；
 *       非 2xx 统一解析后端 ErrorResponse 结构（error_code / error_message），
 *       抛出 ApiError；网络错误 / 超时构造带 isNetworkError 标记的 ApiError。
 *     - 错误码分支参考 types/api.ts 的 ApiErrorCode 常量。
 *     - 行程生成 / 编辑涉及 LLM 调用，超时单独放宽；导出走 blob 下载。
 */

import axios, { AxiosError } from 'axios'
import type { AxiosRequestConfig } from 'axios'

import { getDeviceId } from '@/utils/deviceFingerprint'

import type {
  ApiErrorBody,
  CityWeatherResponse,
  HealthCheckResponse,
  TripBatchResult,
  TripEditRequest,
  TripHistoryListResponse,
  TripRequest,
  TripResponse,
} from '@/types'

/** API 基础路径：VITE_API_BASE_URL 为空时保持同源（vite 代理 / 生产反代） */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

/** 默认请求超时：30s */
const DEFAULT_TIMEOUT = 30_000

/** 行程生成超时：LLM 编排耗时较长，放宽到 5 分钟 */
const GENERATE_TIMEOUT = 300_000

/** 行程编辑超时：单日 LLM 编辑，放宽到 2 分钟 */
const EDIT_TIMEOUT = 120_000

/** 导出下载超时：PDF 渲染较慢，放宽到 2 分钟 */
const EXPORT_TIMEOUT = 120_000

/**
 * API 错误：后端结构化错误体（ApiErrorBody）或网络层错误统一抛此类型。
 * 可依据 code 对照 ApiErrorCode 分支处理，或依据 isNetworkError 做重试/提示。
 */
export class ApiError extends Error {
  /** 错误码（对应后端 error_code；网络层错误为 NETWORK_ERROR） */
  readonly code: string
  /** HTTP 状态码；网络错误为 null */
  readonly status: number | null
  /** 错误详情（后端 error_details） */
  readonly details: Record<string, unknown> | null
  /** 请求 ID（后端 request_id） */
  readonly requestId: string | null
  /** 是否网络层错误（断网 / 超时 / 无响应），非后端业务错误 */
  readonly isNetworkError: boolean

  constructor(
    body: ApiErrorBody | null,
    status: number | null,
    message: string,
    isNetworkError = false,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = body?.error_code ?? (isNetworkError ? 'NETWORK_ERROR' : 'HTTP_ERROR')
    this.status = status
    this.details = body?.error_details ?? null
    this.requestId = body?.request_id ?? null
    this.isNetworkError = isNetworkError
  }
}

/** 判断未知值是否为记录（对象），用于安全解析响应体 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** 解析后端 ErrorResponse 结构；不匹配时返回 null */
function parseErrorBody(data: unknown): ApiErrorBody | null {
  if (!isRecord(data)) return null
  const { error_code: code, error_message: message, error_details: details, timestamp, request_id: reqId } = data
  if (typeof code !== 'string' || typeof message !== 'string') return null
  return {
    error_code: code,
    error_message: message,
    error_details: isRecord(details) ? (details as Record<string, unknown>) : null,
    timestamp: typeof timestamp === 'string' ? timestamp : new Date().toISOString(),
    request_id: typeof reqId === 'string' ? reqId : null,
  }
}

/** 解析错误响应体：兼容 JSON 与 blob（导出接口 404 时返回 JSON）两种形态 */
async function resolveErrorBody(data: unknown): Promise<ApiErrorBody | null> {
  if (data instanceof Blob) {
    try {
      return parseErrorBody(JSON.parse(await data.text()))
    } catch {
      return null
    }
  }
  return parseErrorBody(data)
}

// ----------------------------------------
// axios 实例 + 拦截器
// ----------------------------------------

/** 底层 axios 实例：baseURL 读 VITE_API_BASE_URL，开发环境经 vite 代理转发 */
const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_TIMEOUT,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截器：统一附加浏览器设备指纹 header（X-Device-Id）。
// 项目无登录体系，后端以该标识做历史记录的数据隔离与归属校验。
// 拦截器支持 async（axios 内部为 promise 链），指纹计算失败时静默跳过，
// 由后端对需要设备标识的接口返回明确错误。
http.interceptors.request.use(async (config) => {
  try {
    const deviceId = await getDeviceId()
    if (deviceId) {
      config.headers.set('X-Device-Id', deviceId)
    }
  } catch {
    // 指纹不可用（如极端隐私环境）：不附加 header，后端会返回 DEVICE_ID_REQUIRED
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    // 204 无内容（如 DELETE /trip/history/{id}）
    if (response.status === 204) return undefined as never
    // 解包：调用方直接拿到业务数据结构
    return response.data
  },
  async (error: AxiosError<unknown>) => {
    if (error.response) {
      // 后端有响应：优先解析结构化错误体（ErrorResponse）
      const body = await resolveErrorBody(error.response.data)
      if (body) {
        throw new ApiError(body, error.response.status, body.error_message)
      }
      // 无结构化错误体（如网关 502 / HTML 错误页）
      throw new ApiError(
        null,
        error.response.status,
        `请求失败 (${error.response.status})`,
      )
    }
    // 网络层错误：断网 / 超时 / 无响应
    const isTimeout = error.code === 'ECONNABORTED'
    throw new ApiError(
      null,
      null,
      isTimeout ? '请求超时，请稍后重试' : '网络异常，请检查网络连接',
      true,
    )
  },
)

/**
 * 解包型请求封装：屏蔽 AxiosResponse，让接口函数返回值即业务数据。
 * 注：axios 1.20 类型将 get/post/delete 的返回包为 AxiosResponseResult 条件类型，
 * 泛型参数无法直接收窄，故统一以 as Promise<T> 收口（响应拦截器已在运行时解包）。
 */
const api = {
  get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return http.get(url, config) as Promise<T>
  },
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return http.post(url, data, config) as Promise<T>
  },
  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return http.delete(url, config) as Promise<T>
  },
}

/** 触发浏览器下载（blob → 临时 URL → a.click） */
function downloadBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(objectUrl)
}

// ----------------------------------------
// 8.2.2 / 8.2.3 / 8.2.4 行程 API（对齐 routes/trip.py）
// ----------------------------------------

/** 行程历史查询参数（对齐 GET /trip/history 的 Query 参数） */
export interface HistoryQueryParams {
  /** 按用户 ID 筛选（可选） */
  user_id?: string
  /** 按目的地筛选（可选） */
  destination?: string
  /** 按收藏状态筛选（可选） */
  is_favorite?: boolean
  /** 每页数量（1-100，默认 20） */
  limit?: number
  /** 偏移量（默认 0） */
  offset?: number
  /** 排序字段（默认 created_at） */
  order_by?: string
  /** 是否降序（默认 true） */
  order_desc?: boolean
}

export const tripApi = {
  /**
   * 8.2.2 行程生成
   * POST /trip/generate
   * 说明：LLM 编排耗时较长，单独放宽超时；生成成功后后端已持久化并回填 trip_id。
   */
  generate(request: TripRequest, userId?: string): Promise<TripResponse> {
    return api.post<TripResponse>(
      '/trip/generate',
      request,
      {
        timeout: GENERATE_TIMEOUT,
        params: userId ? { user_id: userId } : undefined,
      },
    )
  },

  /**
   * 8.2.3 行程编辑（单日自然语言编辑）
   * POST /trip/edit
   * 说明：返回编辑后的完整 TripResponse，前端就地替换当天数据。
   */
  edit(request: TripEditRequest): Promise<TripResponse> {
    return api.post<TripResponse>('/trip/edit', request, { timeout: EDIT_TIMEOUT })
  },

  /**
   * 行程详情（历史记录点击回看）
   * GET /trip/{trip_id}
   * 说明：返回完整 TripResponse（含每日明细、天气、预算），后端同时累加访问次数。
   */
  getTrip(tripId: string): Promise<TripResponse> {
    return api.get<TripResponse>(`/trip/${encodeURIComponent(tripId)}`)
  },

  /**
   * 8.2.4 行程历史列表（分页摘要，不含每日明细）
   * GET /trip/history
   */
  listHistory(params: HistoryQueryParams = {}): Promise<TripHistoryListResponse> {
    return api.get<TripHistoryListResponse>('/trip/history', { params })
  },

  /**
   * 批量删除行程历史
   * POST /trip/history/batch-delete
   * 说明：请求体 { trip_ids: string[] }，返回受影响数量。
   */
  batchDeleteHistory(tripIds: string[]): Promise<TripBatchResult> {
    return api.post<TripBatchResult>('/trip/history/batch-delete', { trip_ids: tripIds })
  },

  /**
   * 批量收藏 / 取消收藏行程历史
   * POST /trip/history/batch-favorite
   * 说明：请求体 { trip_ids: string[], is_favorite: boolean }，返回受影响数量。
   */
  batchSetFavorite(tripIds: string[], isFavorite: boolean): Promise<TripBatchResult> {
    return api.post<TripBatchResult>('/trip/history/batch-favorite', {
      trip_ids: tripIds,
      is_favorite: isFavorite,
    })
  },

  /**
   * 8.2.4 删除行程历史
   * DELETE /trip/history/{trip_id}
   * 说明：成功返回 204 无内容；行程不存在时后端返回 404（TRIP_NOT_FOUND）。
   */
  deleteHistory(tripId: string): Promise<void> {
    return api.delete<void>(`/trip/history/${encodeURIComponent(tripId)}`)
  },
}

// ----------------------------------------
// 8.2.5 天气 API（对齐 routes/weather.py）
// ----------------------------------------

/** 天气返回模式：live=实时 / forecast=预报 / both=两者 */
export type WeatherMode = 'live' | 'forecast' | 'both'

/** 天气查询参数（对齐 GET /weather/{city} 的 Query 参数） */
export interface WeatherQueryParams {
  /** 预报天数（1-4，高德上限 4 天，默认 3） */
  days?: number
  /** 返回内容（默认 both） */
  mode?: WeatherMode
}

export const weatherApi = {
  /**
   * 8.2.5 城市天气查询（实时 + 预报）
   * GET /weather/{city}?days=3&mode=both
   */
  get(city: string, params: WeatherQueryParams = {}): Promise<CityWeatherResponse> {
    return api.get<CityWeatherResponse>(`/weather/${encodeURIComponent(city)}`, { params })
  },
}

// ----------------------------------------
// 8.2.6 导出 API（对齐 routes/export.py）
// ----------------------------------------

export const exportApi = {
  /**
   * 8.2.6 导出行程为 Markdown 文档
   * GET /export/markdown/{trip_id}
   * 说明：以 blob 下载方式触发浏览器保存；filename 缺省时用 trip_id 命名。
   */
  markdown(tripId: string, filename?: string): Promise<void> {
    return api
      .get<Blob>(`/export/markdown/${encodeURIComponent(tripId)}`, {
        responseType: 'blob',
        timeout: EXPORT_TIMEOUT,
      })
      .then((blob) => {
        downloadBlob(blob, filename ?? `${tripId}.md`)
      })
  },

  /**
   * 8.2.6 导出行程为 PDF 文档
   * GET /export/pdf/{trip_id}
   */
  pdf(tripId: string, filename?: string): Promise<void> {
    return api
      .get<Blob>(`/export/pdf/${encodeURIComponent(tripId)}`, {
        responseType: 'blob',
        timeout: EXPORT_TIMEOUT,
      })
      .then((blob) => {
        downloadBlob(blob, filename ?? `${tripId}.pdf`)
      })
  },
}

// ----------------------------------------
// 系统 API（健康检查，可选：顶栏后端状态灯）
// ----------------------------------------

export const systemApi = {
  /** GET /health 健康检查（200=healthy / 503=unhealthy） */
  health(): Promise<HealthCheckResponse> {
    return api.get<HealthCheckResponse>('/health')
  },
}
