/**
 * 枚举与字面量类型
 * 与 backend/app/models/schemas.py 的 Enum 定义对齐
 */

/** 旅行风格 */
export type TravelStyle = 'relaxed' | 'compact' | 'adventure' | 'cultural' | 'foodie'

/** 预算等级 */
export type BudgetLevel = 'economy' | 'standard' | 'luxury'

/** 天气偏好 */
export type WeatherPreference = 'no_preference' | 'sunny' | 'cool'

/** 预算状态 */
export type BudgetStatus = 'within_budget' | 'over_budget' | 'saved'

/** 城市分级：A 沉淀城市（本地攻略）/ B 动态城市（高德 POI）/ C 不支持 */
export type CityLevel = 'A' | 'B' | 'C'