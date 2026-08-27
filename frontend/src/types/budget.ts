import type { BudgetStatus } from './enums'

/** 预算信息：与 schemas.BudgetInfo 对齐 */
export interface BudgetInfo {
  /** 总预算（元） */
  total_budget: number
  /** 日均预算（元） */
  daily_avg_budget: number
  /** 人均预算（元） */
  budget_per_person: number
  /** 住宿预算（元） */
  accommodation_budget: number
  /** 餐饮预算（元） */
  food_budget: number
  /** 交通预算（元） */
  transportation_budget: number
  /** 门票预算（元） */
  ticket_budget: number
  /** 购物预算（元） */
  shopping_budget: number
  /** 其他预算（元） */
  other_budget: number
  /** 实际总花费（元） */
  actual_total?: number | null
  /** 实际住宿花费 */
  actual_accommodation?: number | null
  /** 实际餐饮花费 */
  actual_food?: number | null
  /** 实际交通花费 */
  actual_transportation?: number | null
  /** 实际门票花费 */
  actual_ticket?: number | null
  /** 预算状态 */
  budget_status: BudgetStatus
  /** 节省金额（元） */
  savings?: number | null
}