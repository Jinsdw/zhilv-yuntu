"""
智旅云图 - Pydantic数据模型
定义API请求/响应的数据结构
"""

from datetime import date as date_type, datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, field_validator


class TravelStyle(str, Enum):
    """旅行风格枚举"""
    RELAXED = "relaxed"           # 休闲度假
    COMPACT = "compact"           # 紧凑高效
    ADVENTURE = "adventure"       # 探险挑战
    CULTURAL = "cultural"          # 文化体验
    FOODIE = "foodie"             # 美食之旅


class BudgetLevel(str, Enum):
    """预算等级枚举"""
    ECONOMY = "economy"           # 经济实惠
    STANDARD = "standard"         # 标准适中
    LUXURY = "luxury"            # 豪华享受


class WeatherPreference(str, Enum):
    """天气偏好枚举"""
    NO_PREFERENCE = "no_preference"  # 无偏好
    SUNNY = "sunny"                  # 晴天偏好
    COOL = "cool"                    # 凉爽偏好


# ==================== 请求模型 ====================

class TripRequest(BaseModel):
    """行程规划请求模型"""
    
    # 必填字段
    destination: str = Field(..., description="目的地城市/地区", min_length=1, max_length=50)
    start_date: date_type = Field(..., description="行程开始日期")
    end_date: date_type = Field(..., description="行程结束日期")
    
    # 可选字段
    travelers: int = Field(default=1, ge=1, le=20, description="出行人数")
    budget_level: BudgetLevel = Field(default=BudgetLevel.STANDARD, description="预算等级")
    travel_style: TravelStyle = Field(default=TravelStyle.RELAXED, description="旅行风格偏好")
    weather_preference: WeatherPreference = Field(default=WeatherPreference.NO_PREFERENCE, description="天气偏好")
    
    # 特殊需求
    with_kids: bool = Field(default=False, description="是否携带儿童")
    with_elderly: bool = Field(default=False, description="是否携带老人")
    has_disability: bool = Field(default=False, description="是否有行动不便人员")
    include_indoor: bool = Field(default=True, description="是否包含室内景点")
    include_outdoor: bool = Field(default=True, description="是否包含室外景点")
    
    # 用户偏好关键词
    preferred_keywords: List[str] = Field(default_factory=list, description="偏好关键词列表")
    excluded_keywords: List[str] = Field(default_factory=list, description="排除关键词列表")
    
    # 高级选项
    daily_budget: Optional[float] = Field(default=None, ge=0, description="每日预算上限(元)")
    max_places_per_day: int = Field(default=5, ge=1, le=10, description="每日最多景点数")
    restaurant_budget_per_meal: float = Field(default=100.0, ge=0, description="每餐餐饮预算(元)")
    
    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: date_type, info) -> date_type:
        """验证结束日期不早于开始日期"""
        if "start_date" in info.data and v < info.data["start_date"]:
            raise ValueError("结束日期不能早于开始日期")
        return v
    
    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, v: date_type) -> date_type:
        """验证开始日期不早于今天"""
        if v < date_type.today():
            raise ValueError("开始日期不能早于今天")
        return v
    
    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """支持JSON序列化"""
        return super().model_dump(**kwargs)


# ==================== 响应模型 ====================

class Coordinate(BaseModel):
    """地理坐标"""
    latitude: float = Field(..., ge=-90, le=90, description="纬度")
    longitude: float = Field(..., ge=-180, le=180, description="经度")


class PlaceInfo(BaseModel):
    """地点/景点信息模型"""
    
    # 基本信息
    place_id: str = Field(..., description="景点唯一标识")
    name: str = Field(..., description="景点名称", min_length=1)
    name_en: Optional[str] = Field(default=None, description="英文名称")
    
    # 位置信息
    address: str = Field(..., description="详细地址")
    coordinate: Coordinate = Field(..., description="地理坐标")
    district: Optional[str] = Field(default=None, description="所属行政区")
    
    # 分类信息
    category: str = Field(..., description="景点类别(如:景点,餐厅,酒店)")
    subcategory: Optional[str] = Field(default=None, description="子类别")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    
    # 游览信息
    description: Optional[str] = Field(default=None, description="景点简介")
    opening_hours: Optional[str] = Field(default=None, description="营业时间")
    suggested_duration: int = Field(default=120, ge=0, description="建议游览时长(分钟)")
    
    # 费用信息
    ticket_price: Optional[float] = Field(default=None, ge=0, description="门票价格(元)")
    is_free: bool = Field(default=False, description="是否免费")
    
    # 评分信息
    rating: Optional[float] = Field(default=None, ge=0, le=5, description="评分(0-5)")
    review_count: int = Field(default=0, ge=0, description="评价数量")
    
    # 图片信息
    images: List[str] = Field(default_factory=list, description="图片URL列表")
    cover_image: Optional[str] = Field(default=None, description="封面图片URL")
    
    # 附加信息
    phone: Optional[str] = Field(default=None, description="联系电话")
    website: Optional[str] = Field(default=None, description="官网URL")
    has_wifi: bool = Field(default=False, description="是否有WiFi")
    has_parking: bool = Field(default=False, description="是否有停车场")
    has_wheelchair: bool = Field(default=False, description="是否支持轮椅")
    
    # 适合人群
    suitable_for_kids: bool = Field(default=True, description="是否适合儿童")
    suitable_for_elderly: bool = Field(default=True, description="是否适合老人")
    
    # 室内/室外
    is_indoor: bool = Field(default=False, description="是否室内景点")
    
    # 推荐理由
    highlight: Optional[str] = Field(default=None, description="推荐亮点")
    
    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """支持JSON序列化"""
        return super().model_dump(**kwargs)


class RestaurantInfo(BaseModel):
    """餐厅信息模型（继承自PlaceInfo扩展）"""
    
    place_id: str = Field(..., description="餐厅唯一标识")
    name: str = Field(..., description="餐厅名称")
    coordinate: Coordinate = Field(..., description="地理坐标")
    address: str = Field(..., description="餐厅地址")
    
    # 餐饮特色
    cuisine_type: str = Field(..., description="菜系类型(如:川菜,火锅,小吃)")
    price_range: str = Field(..., description="人均价格区间(如:50-100元)")
    avg_price: float = Field(..., ge=0, description="人均价格(元)")
    
    # 营业信息
    opening_hours: Optional[str] = Field(default=None, description="营业时间")
    business_status: str = Field(default="营业中", description="营业状态")
    
    # 评分
    rating: Optional[float] = Field(default=None, ge=0, le=5, description="评分")
    taste_rating: Optional[float] = Field(default=None, ge=0, le=5, description="口味评分")
    environment_rating: Optional[float] = Field(default=None, ge=0, le=5, description="环境评分")
    service_rating: Optional[float] = Field(default=None, ge=0, le=5, description="服务评分")
    
    # 推荐菜
    signature_dishes: List[str] = Field(default_factory=list, description="招牌菜品")
    popular_dishes: List[str] = Field(default_factory=list, description="热门菜品")
    
    # 特色标签
    tags: List[str] = Field(default_factory=list, description="标签(如:老字号,网红店,必吃榜)")
    
    # 图片
    images: List[str] = Field(default_factory=list, description="餐厅图片")
    
    # 预订
    support_booking: bool = Field(default=False, description="是否支持预订")


class HotelInfo(BaseModel):
    """酒店信息模型"""
    
    place_id: str = Field(..., description="酒店唯一标识")
    name: str = Field(..., description="酒店名称")
    coordinate: Coordinate = Field(..., description="地理坐标")
    address: str = Field(..., description="酒店地址")
    
    # 酒店类型
    hotel_type: str = Field(..., description="酒店类型(如:经济型,舒适型,高档型)")
    star_rating: Optional[int] = Field(default=None, ge=1, le=5, description="星级(1-5)")
    
    # 价格
    price: float = Field(..., ge=0, description="价格(元/晚)")
    price_range: str = Field(..., description="价格区间描述")
    
    # 评分
    rating: Optional[float] = Field(default=None, ge=0, le=5, description="综合评分")
    
    # 设施
    facilities: List[str] = Field(default_factory=list, description="设施列表")
    has_wifi: bool = Field(default=True, description="是否有WiFi")
    has_parking: bool = Field(default=False, description="是否有停车场")
    has_breakfast: bool = Field(default=True, description="是否含早餐")
    
    # 位置
    nearby_landmarks: List[str] = Field(default_factory=list, description="附近地标")
    distance_to_center: Optional[str] = Field(default=None, description="距市中心距离")
    
    # 图片
    images: List[str] = Field(default_factory=list, description="酒店图片")
    cover_image: Optional[str] = Field(default=None, description="封面图片")
    
    # 特色
    tags: List[str] = Field(default_factory=list, description="特色标签")


class WeatherInfo(BaseModel):
    """天气信息模型"""
    
    forecast_date: date_type = Field(..., description="日期")
    
    # 温度
    temp_high: int = Field(..., description="最高温度(℃)")
    temp_low: int = Field(..., description="最低温度(℃)")
    temp_avg: Optional[int] = Field(default=None, description="平均温度(℃)")
    
    # 天气状况
    weather_type: str = Field(..., description="天气类型(如:晴,多云,小雨)")
    weather_icon: Optional[str] = Field(default=None, description="天气图标")
    
    # 空气质量
    aqi: Optional[int] = Field(default=None, ge=0, le=500, description="空气质量指数")
    aqi_level: Optional[str] = Field(default=None, description="空气质量等级")
    
    # 附加信息
    humidity: Optional[int] = Field(default=None, ge=0, le=100, description="湿度(%)")
    wind_speed: Optional[float] = Field(default=None, ge=0, description="风速(km/h)")
    wind_direction: Optional[str] = Field(default=None, description="风向")
    
    # 出行建议
    travel_suggestion: Optional[str] = Field(default=None, description="出行建议")
    
    # 穿衣建议
    dressing_suggestion: Optional[str] = Field(default=None, description="穿衣建议")


class BudgetInfo(BaseModel):
    """预算信息模型"""
    
    # 预算摘要
    total_budget: float = Field(..., ge=0, description="总预算(元)")
    daily_avg_budget: float = Field(..., ge=0, description="日均预算(元)")
    budget_per_person: float = Field(..., ge=0, description="人均预算(元)")
    
    # 预算明细
    accommodation_budget: float = Field(default=0, ge=0, description="住宿预算(元)")
    food_budget: float = Field(default=0, ge=0, description="餐饮预算(元)")
    transportation_budget: float = Field(default=0, ge=0, description="交通预算(元)")
    ticket_budget: float = Field(default=0, ge=0, description="门票预算(元)")
    shopping_budget: float = Field(default=0, ge=0, description="购物预算(元)")
    other_budget: float = Field(default=0, ge=0, description="其他预算(元)")
    
    # 实际花费（行程结束后更新）
    actual_total: Optional[float] = Field(default=None, ge=0, description="实际总花费(元)")
    actual_accommodation: Optional[float] = Field(default=None, ge=0, description="实际住宿花费")
    actual_food: Optional[float] = Field(default=None, ge=0, description="实际餐饮花费")
    actual_transportation: Optional[float] = Field(default=None, ge=0, description="实际交通花费")
    actual_ticket: Optional[float] = Field(default=None, ge=0, description="实际门票花费")
    
    # 预算状态
    budget_status: str = Field(default="within_budget", description="预算状态:within_budget/over_budget/saved")
    savings: Optional[float] = Field(default=None, description="节省金额(元)")


class TransportationInfo(BaseModel):
    """交通信息模型"""
    
    # 交通类型
    transport_type: str = Field(..., description="交通类型(如:地铁,公交,打车,步行)")
    transport_icon: Optional[str] = Field(default=None, description="交通图标")
    
    # 路线信息
    from_place: str = Field(..., description="出发地")
    to_place: str = Field(..., description="目的地")
    route_description: Optional[str] = Field(default=None, description="路线描述")
    
    # 时间和距离
    duration: int = Field(..., ge=0, description="预计时长(分钟)")
    distance: Optional[float] = Field(default=None, ge=0, description="距离(公里)")
    
    # 费用
    cost: float = Field(default=0, ge=0, description="费用(元)")
    is_free: bool = Field(default=False, description="是否免费")
    
    # 详细说明
    instruction: Optional[str] = Field(default=None, description="导航指引")


class ItineraryItem(BaseModel):
    """行程项目（单个景点/餐厅）"""
    
    # 时间安排
    start_time: str = Field(..., description="开始时间(如:09:00)")
    end_time: str = Field(..., description="结束时间(如:11:00)")
    
    # 地点信息
    place: PlaceInfo = Field(..., description="地点信息")
    
    # 活动信息
    activity: str = Field(..., description="活动描述")
    activity_detail: Optional[str] = Field(default=None, description="活动详情")
    
    # 交通信息（从上一站到本站）
    arrival_transport: Optional[TransportationInfo] = Field(default=None, description="到达交通")
    
    # 费用
    ticket_price: Optional[float] = Field(default=None, ge=0, description="门票费用(元)")
    food_cost: Optional[float] = Field(default=None, ge=0, description="餐饮费用(元)")
    
    # 注意事项
    tips: List[str] = Field(default_factory=list, description="游览提示")
    highlights: List[str] = Field(default_factory=list, description="游览亮点")
    
    # 预订信息
    booking_required: bool = Field(default=False, description="是否需要预约")
    booking_url: Optional[str] = Field(default=None, description="预约链接")
    
    # 照片拍摄点
    photo_spot: Optional[str] = Field(default=None, description="推荐拍照点")


class ItineraryDay(BaseModel):
    """每日行程模型"""
    
    # 日期信息
    day_number: int = Field(..., ge=1, description="第几天")
    itinerary_date: date_type = Field(..., description="日期")
    day_theme: Optional[str] = Field(default=None, description="当日主题(如:文化之旅)")
    
    # 天气信息
    weather: Optional[WeatherInfo] = Field(default=None, description="当天天气")
    
    # 行程安排
    items: List[ItineraryItem] = Field(default_factory=list, description="行程项目列表")
    
    # 每日摘要
    total_places: int = Field(default=0, ge=0, description="总景点数")
    total_distance: Optional[float] = Field(default=None, ge=0, description="总行程距离(公里)")
    total_duration: int = Field(default=0, ge=0, description="总游览时长(分钟)")
    
    # 费用统计
    daily_cost: float = Field(default=0, ge=0, description="当日总费用(元)")
    cost_breakdown: Dict[str, float] = Field(default_factory=dict, description="费用明细")
    
    # 总体评价
    total_rating: float = Field(default=0, ge=0, le=5, description="当日综合评分")
    
    # 小贴士
    daily_tips: List[str] = Field(default_factory=list, description="当日小贴士")
    
    # 早餐/午餐/晚餐安排
    breakfast: Optional[RestaurantInfo] = Field(default=None, description="早餐餐厅")
    lunch: Optional[RestaurantInfo] = Field(default=None, description="午餐餐厅")
    dinner: Optional[RestaurantInfo] = Field(default=None, description="晚餐餐厅")
    
    # 住宿（过夜城市）
    hotel: Optional[HotelInfo] = Field(default=None, description="住宿酒店")


class TripResponse(BaseModel):
    """行程规划响应模型"""
    
    # 基本信息
    trip_id: str = Field(..., description="行程唯一标识")
    destination: str = Field(..., description="目的地")
    trip_name: str = Field(..., description="行程名称")
    
    # 时间范围
    start_date: date_type = Field(..., description="开始日期")
    end_date: date_type = Field(..., description="结束日期")
    total_days: int = Field(..., ge=1, description="总天数")
    
    # 行程详情
    days: List[ItineraryDay] = Field(default_factory=list, description="每日行程")
    
    # 预算信息
    budget: BudgetInfo = Field(..., description="预算信息")
    
    # 总体评价
    overall_rating: float = Field(default=0, ge=0, le=5, description="总体评分")
    
    # 行程特点
    trip_highlights: List[str] = Field(default_factory=list, description="行程亮点")
    trip_tips: List[str] = Field(default_factory=list, description="行程贴士")
    
    # 推荐美食
    recommended_foods: List[str] = Field(default_factory=list, description="推荐美食")
    
    # 推荐购物
    recommended_shopping: List[str] = Field(default_factory=list, description="推荐购物")
    
    # 附加信息
    emergency_phone: Optional[str] = Field(default=None, description="紧急联系电话")
    local_tourism_hotline: Optional[str] = Field(default=None, description="当地旅游热线")
    
    # 生成信息
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")
    generation_time: float = Field(default=0, ge=0, description="生成耗时(秒)")
    model_used: Optional[str] = Field(default=None, description="使用的模型")
    
    # 版本信息
    version: str = Field(default="1.0", description="行程版本")
    
    # 元数据
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class TripHistory(BaseModel):
    """行程历史记录模型"""
    
    # 基本信息
    history_id: str = Field(..., description="历史记录唯一标识")
    user_id: Optional[str] = Field(default=None, description="用户ID")
    
    # 行程信息
    request: TripRequest = Field(..., description="原始请求")
    response: TripResponse = Field(..., description="生成行程")
    
    # 使用信息
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    accessed_at: datetime = Field(default_factory=datetime.now, description="最后访问时间")
    access_count: int = Field(default=0, ge=0, description="访问次数")
    
    # 状态
    is_favorite: bool = Field(default=False, description="是否收藏")
    is_shared: bool = Field(default=False, description="是否已分享")
    share_code: Optional[str] = Field(default=None, description="分享码")
    
    # 反馈
    user_rating: Optional[int] = Field(default=None, ge=1, le=5, description="用户评分")
    user_feedback: Optional[str] = Field(default=None, description="用户反馈")
    
    # 导出记录
    exported_formats: List[str] = Field(default_factory=list, description="已导出的格式")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    
    error_code: str = Field(..., description="错误代码")
    error_message: str = Field(..., description="错误信息")
    error_details: Optional[Dict[str, Any]] = Field(default=None, description="错误详情")
    timestamp: datetime = Field(default_factory=datetime.now, description="错误发生时间")
    request_id: Optional[str] = Field(default=None, description="请求ID")


class HealthCheckResponse(BaseModel):
    """健康检查响应模型"""
    
    status: str = Field(default="healthy", description="服务状态")
    version: str = Field(..., description="服务版本")
    uptime: float = Field(..., ge=0, description="运行时间(秒)")
    dependencies: Dict[str, str] = Field(default_factory=dict, description="依赖服务状态")


# ==================== 第七阶段 API 层新增模型 ====================

class TripEditRequest(BaseModel):
    """行程编辑请求模型（Phase 7.1.3）"""

    trip_id: str = Field(..., min_length=1, description="行程ID")
    day_number: int = Field(..., ge=1, description="第几天(1-based)")
    instruction: str = Field(..., min_length=1, max_length=500, description="编辑指令(自然语言)")
    context: Optional[str] = Field(default=None, description="可选的攻略上下文")


class TripHistorySummary(BaseModel):
    """行程历史摘要模型（列表页轻量卡片，不含每日明细）"""

    id: str = Field(..., description="行程ID")
    user_id: Optional[str] = Field(default=None, description="用户ID")
    destination: str = Field(..., description="目的地")
    start_date: date_type = Field(..., description="开始日期")
    end_date: date_type = Field(..., description="结束日期")
    total_days: int = Field(..., description="总天数")
    total_budget: Optional[float] = Field(default=None, description="总预算(元)")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    is_favorite: bool = Field(default=False, description="是否收藏")
    is_shared: bool = Field(default=False, description="是否已分享")
    share_code: Optional[str] = Field(default=None, description="分享码")
    access_count: int = Field(default=0, description="访问次数")
    user_rating: Optional[int] = Field(default=None, description="用户评分")
    model_used: Optional[str] = Field(default=None, description="使用的模型")
    generation_time: Optional[float] = Field(default=None, description="生成耗时(秒)")


class TripHistoryListResponse(BaseModel):
    """行程历史分页响应模型（Phase 7.1.4）"""

    items: List[TripHistorySummary] = Field(default_factory=list, description="行程摘要列表")
    total: int = Field(..., ge=0, description="总记录数")
    limit: int = Field(..., ge=0, description="每页数量")
    offset: int = Field(..., ge=0, description="偏移量")
