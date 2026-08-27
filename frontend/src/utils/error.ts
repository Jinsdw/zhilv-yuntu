/** 错误文案工具：统一从 ApiError 提取后端 error_message，其余走兜底文案 */

import { ApiError } from '@/services/api'

/** 提取可读错误信息；非 ApiError（未知异常）时返回兜底文案 */
export function toErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  return error instanceof ApiError ? error.message : fallback
}