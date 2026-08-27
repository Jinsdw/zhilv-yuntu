/**
 * 结果页 sessionStorage 快照（DESIGN.md §3.3 兜底方案）
 * 作用：生成成功后写入，结果页刷新或直接打开时仍能恢复行程，无需重新调用 LLM。
 * 注意：sessionStorage 随标签页关闭清空，跨会话仍需走历史（后端持久化）。
 */

import type { TripRequest, TripResponse } from '@/types'

export const LAST_TRIP_SNAPSHOT_KEY = 'zhilv-yuntu:last-trip'

export interface TripSnapshot {
  trip: TripResponse
  request?: TripRequest
}

export function writeTripSnapshot(snapshot: TripSnapshot): void {
  try {
    sessionStorage.setItem(LAST_TRIP_SNAPSHOT_KEY, JSON.stringify(snapshot))
  } catch {
    // 隐私模式 / 配额不足时静默失败，不影响主流程
  }
}

export function readTripSnapshot(): TripSnapshot | null {
  try {
    const raw = sessionStorage.getItem(LAST_TRIP_SNAPSHOT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as TripSnapshot
    if (!parsed?.trip?.trip_id) return null
    return parsed
  } catch {
    return null
  }
}