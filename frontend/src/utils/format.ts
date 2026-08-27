/** 通用展示格式化工具（数字走 .num 表格数字约定，见 DESIGN.md §2.3） */

import dayjs from 'dayjs'

/** 金额格式化：¥1,234（整数展示，避免小数点噪音） */
export function formatMoney(value: number | null | undefined): string {
  if (value == null) return '—'
  return `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

/** 分钟 → 中文时长：90 → “1 小时 30 分钟” */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest > 0 ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`
}

/** 日期 → 中文：2026-08-27 → “2026年8月27日 周四”（zh-cn locale 已全局注册） */
export function formatDateCN(date: string): string {
  return dayjs(date).format('YYYY年M月D日 ddd')
}