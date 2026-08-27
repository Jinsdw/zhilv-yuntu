/** 地点/景点信息：与 schemas.PlaceInfo 对齐 */

/** 地理坐标 */
export interface Coordinate {
  /** 纬度 */
  latitude: number
  /** 经度 */
  longitude: number
}

/** 地点/景点信息 */
export interface PlaceInfo {
  /** 景点唯一标识 */
  place_id: string
  /** 景点名称 */
  name: string
  /** 英文名称 */
  name_en?: string | null
  /** 详细地址 */
  address: string
  /** 地理坐标 */
  coordinate: Coordinate
  /** 所属行政区 */
  district?: string | null
  /** 景点类别（景点/餐厅/酒店等） */
  category: string
  /** 子类别 */
  subcategory?: string | null
  /** 标签列表 */
  tags: string[]
  /** 景点简介 */
  description?: string | null
  /** 营业时间 */
  opening_hours?: string | null
  /** 建议游览时长（分钟） */
  suggested_duration: number
  /** 门票价格（元） */
  ticket_price?: number | null
  /** 是否免费 */
  is_free: boolean
  /** 评分（0-5） */
  rating?: number | null
  /** 评价数量 */
  review_count: number
  /** 图片 URL 列表 */
  images: string[]
  /** 封面图片 URL */
  cover_image?: string | null
  /** 联系电话 */
  phone?: string | null
  /** 官网 URL */
  website?: string | null
  /** 是否有 WiFi */
  has_wifi: boolean
  /** 是否有停车场 */
  has_parking: boolean
  /** 是否支持轮椅 */
  has_wheelchair: boolean
  /** 是否适合儿童 */
  suitable_for_kids: boolean
  /** 是否适合老人 */
  suitable_for_elderly: boolean
  /** 是否室内景点 */
  is_indoor: boolean
  /** 推荐亮点 */
  highlight?: string | null
}

/** 餐厅信息：与 schemas.RestaurantInfo 对齐 */
export interface RestaurantInfo {
  place_id: string
  /** 餐厅名称 */
  name: string
  /** 地理坐标 */
  coordinate: Coordinate
  /** 餐厅地址 */
  address: string
  /** 菜系类型（川菜/火锅/小吃等） */
  cuisine_type: string
  /** 人均价格区间（50-100元） */
  price_range: string
  /** 人均价格（元） */
  avg_price: number
  /** 营业时间 */
  opening_hours?: string | null
  /** 营业状态 */
  business_status: string
  /** 综合评分 */
  rating?: number | null
  /** 口味评分 */
  taste_rating?: number | null
  /** 环境评分 */
  environment_rating?: number | null
  /** 服务评分 */
  service_rating?: number | null
  /** 招牌菜品 */
  signature_dishes: string[]
  /** 热门菜品 */
  popular_dishes: string[]
  /** 特色标签（老字号/网红店/必吃榜等） */
  tags: string[]
  /** 图片 URL 列表 */
  images: string[]
  /** 是否支持预订 */
  support_booking: boolean
}

/** 酒店信息：与 schemas.HotelInfo 对齐 */
export interface HotelInfo {
  place_id: string
  /** 酒店名称 */
  name: string
  /** 地理坐标 */
  coordinate: Coordinate
  /** 酒店地址 */
  address: string
  /** 酒店类型（经济型/舒适型/高档型等） */
  hotel_type: string
  /** 星级（1-5） */
  star_rating?: number | null
  /** 价格（元/晚） */
  price: number
  /** 价格区间描述 */
  price_range: string
  /** 综合评分 */
  rating?: number | null
  /** 设施列表 */
  facilities: string[]
  /** 是否有 WiFi */
  has_wifi: boolean
  /** 是否有停车场 */
  has_parking: boolean
  /** 是否含早餐 */
  has_breakfast: boolean
  /** 附近地标 */
  nearby_landmarks: string[]
  /** 距市中心距离 */
  distance_to_center?: string | null
  /** 图片 URL 列表 */
  images: string[]
  /** 封面图片 URL */
  cover_image?: string | null
  /** 特色标签 */
  tags: string[]
}