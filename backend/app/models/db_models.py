"""
智旅云图 - SQLAlchemy数据库模型
定义数据库表结构和ORM映射
"""

from datetime import datetime, date
from typing import Optional, List
import uuid

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date,
    Text, ForeignKey, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.orm import relationship, declarative_base, Mapped, mapped_column
from sqlalchemy.sql import func

Base = declarative_base()


def generate_uuid() -> str:
    """生成UUID"""
    return str(uuid.uuid4())


def generate_trip_id() -> str:
    """生成行程ID"""
    return f"TRP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"


class TripHistoryDB(Base):
    """行程历史表"""
    
    __tablename__ = "trip_history"
    
    # 主键
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=generate_trip_id)
    
    # 用户信息
    user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    
    # 请求信息 (JSON存储)
    request_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    
    # 响应信息 (JSON存储)
    response_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    
    # 行程基本信息
    destination: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_days: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # 预算信息
    total_budget: Mapped[float] = mapped_column(Float, default=0)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    
    # 访问统计
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # 收藏和分享
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    share_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    
    # 用户反馈
    user_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 导出记录
    exported_formats: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 生成元数据
    generation_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # 索引
    __table_args__ = (
        Index('idx_trip_history_destination_date', 'destination', 'start_date'),
        Index('idx_trip_history_user_created', 'user_id', 'created_at'),
        Index('idx_trip_history_favorite', 'is_favorite'),
    )
    
    def __repr__(self) -> str:
        return f"<TripHistoryDB(id={self.id}, destination={self.destination}, days={self.total_days})>"


class GuideDocumentDB(Base):
    """攻略文档表"""
    
    __tablename__ = "guide_documents"
    
    # 主键
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=generate_uuid)
    
    # 文档基本信息
    city: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # 文档类型
    doc_type: Mapped[str] = mapped_column(String(50), default="travel_guide")  # travel_guide, food_guide, etc.
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # 标签
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 向量信息
    vector_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # 统计信息
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # 质量评分
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # 来源
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    
    # 索引
    __table_args__ = (
        Index('idx_guide_city_type', 'city', 'doc_type'),
        Index('idx_guide_tags', 'tags', postgresql_using='gin'),
    )
    
    def __repr__(self) -> str:
        return f"<GuideDocumentDB(id={self.id}, city={self.city}, title={self.title})>"


class UserPreferenceDB(Base):
    """用户偏好表"""
    
    __tablename__ = "user_preferences"
    
    # 主键
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=generate_uuid)
    
    # 用户信息
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    
    # 偏好设置 (JSON存储)
    travel_style: Mapped[str] = mapped_column(String(50), default="relaxed")
    budget_level: Mapped[str] = mapped_column(String(50), default="standard")
    
    # 饮食偏好
    dietary_restrictions: Mapped[List[str]] = mapped_column(JSON, default=list)
    preferred_cuisines: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 特殊需求
    with_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    with_elderly: Mapped[bool] = mapped_column(Boolean, default=False)
    has_disability: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # 景点偏好
    preferred_place_types: Mapped[List[str]] = mapped_column(JSON, default=list)
    excluded_place_types: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 关键词偏好
    preferred_keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    excluded_keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 住宿偏好
    hotel_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # 交通偏好
    transport_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    
    def __repr__(self) -> str:
        return f"<UserPreferenceDB(user_id={self.user_id})>"


class QueryCacheDB(Base):
    """查询缓存表"""
    
    __tablename__ = "query_cache"
    
    # 主键
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    
    # 缓存键
    cache_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    
    # 缓存值
    cache_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    
    # 缓存类型
    cache_type: Mapped[str] = mapped_column(String(50), default="query")  # query, rag, weather, etc.
    
    # 过期时间
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    
    # 统计
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # 元数据
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    
    # 索引
    __table_args__ = (
        Index('idx_cache_type_expires', 'cache_type', 'expires_at'),
    )
    
    def __repr__(self) -> str:
        return f"<QueryCacheDB(key={self.cache_key[:30]}...)>"


class CityInfoDB(Base):
    """城市信息表"""
    
    __tablename__ = "city_info"
    
    # 主键
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=generate_uuid)
    
    # 城市信息
    city_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    city_name_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 城市编码
    
    # 行政区划
    province: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    country: Mapped[str] = mapped_column(String(50), default="中国")
    
    # 地理坐标
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    
    # 城市级别
    city_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 一线, 二线, etc.
    
    # 城市标签
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 特色信息
    specialties: Mapped[List[str]] = mapped_column(JSON, default=list)  # 特色美食
    attractions: Mapped[List[str]] = mapped_column(JSON, default=list)  # 著名景点
    
    # 最佳旅行时间
    best_travel_months: Mapped[List[int]] = mapped_column(JSON, default=list)
    
    # 当地信息
    local_tips: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emergency_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tourism_hotline: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # 货币和时间
    currency: Mapped[str] = mapped_column(String(20), default="CNY")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Shanghai")
    
    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    
    def __repr__(self) -> str:
        return f"<CityInfoDB(city={self.city_name})>"


class ApiUsageLogDB(Base):
    """API使用日志表"""
    
    __tablename__ = "api_usage_log"
    
    # 主键
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=generate_uuid)
    
    # 用户信息
    user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    
    # API信息
    api_endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    api_method: Mapped[str] = mapped_column(String(10), default="POST")
    
    # 请求信息
    request_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    request_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # 响应信息
    response_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    
    # 性能指标
    latency_ms: Mapped[float] = mapped_column(Float, default=0)
    token_usage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # LLM使用情况
    llm_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # 错误信息
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    
    # 索引
    __table_args__ = (
        Index('idx_usage_user_time', 'user_id', 'created_at'),
        Index('idx_usage_endpoint_time', 'api_endpoint', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<ApiUsageLogDB(endpoint={self.api_endpoint}, status={self.status_code})>"


def init_db(engine) -> None:
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


def drop_db(engine) -> None:
    """删除所有表"""
    Base.metadata.drop_all(bind=engine)
