/** 交通信息：与 schemas.TransportationInfo 对齐 */

export interface TransportationInfo {
  /** 交通类型（地铁/公交/打车/步行等） */
  transport_type: string
  /** 交通图标 */
  transport_icon?: string | null
  /** 出发地 */
  from_place: string
  /** 目的地 */
  to_place: string
  /** 路线描述 */
  route_description?: string | null
  /** 预计时长（分钟） */
  duration: number
  /** 距离（公里） */
  distance?: number | null
  /** 费用（元） */
  cost: number
  /** 是否免费 */
  is_free: boolean
  /** 导航指引 */
  instruction?: string | null
}