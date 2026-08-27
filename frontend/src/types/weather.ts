import type { ISODate } from './common'

/** 天气信息：与 schemas.WeatherInfo 对齐 */
export interface WeatherInfo {
  /** 日期 */
  forecast_date: ISODate
  /** 最高温度（℃） */
  temp_high: number
  /** 最低温度（℃） */
  temp_low: number
  /** 平均温度（℃） */
  temp_avg?: number | null
  /** 天气类型（晴/多云/小雨等） */
  weather_type: string
  /** 天气图标 */
  weather_icon?: string | null
  /** 空气质量指数 */
  aqi?: number | null
  /** 空气质量等级 */
  aqi_level?: string | null
  /** 湿度（%） */
  humidity?: number | null
  /** 风速（km/h） */
  wind_speed?: number | null
  /** 风向 */
  wind_direction?: string | null
  /** 出行建议 */
  travel_suggestion?: string | null
  /** 穿衣建议 */
  dressing_suggestion?: string | null
}

/** 城市天气响应：与 weather.py 的 CityWeatherResponse 对齐 */
export interface CityWeatherResponse {
  /** 城市名或 adcode */
  city: string
  /** 行政区编码 */
  adcode?: string | null
  /** 实时天气 */
  live?: WeatherInfo | null
  /** 未来 N 天预报 */
  forecast: WeatherInfo[]
}