"""
智旅云图 - 存储服务

提供行程数据的持久化存储和查询功能:
- 数据库连接管理
- 行程数据 CRUD 操作
- 历史记录查询与统计
- 数据导出接口
"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Generator
import uuid

from sqlalchemy import create_engine, and_, or_, desc, asc, func, text, String
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..models.db_models import Base, TripHistoryDB, GuideDocumentDB, UserPreferenceDB
from ..models.schemas import (
    TripRequest,
    TripResponse,
    TripHistory,
    BudgetLevel,
    TravelStyle,
)

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """支持 date/datetime 序列化的 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def json_serialize(obj: Any) -> str:
    """将对象序列化为 JSON 字符串"""
    return json.dumps(obj, cls=DateTimeEncoder, ensure_ascii=False)


def json_deserialize(data: str) -> Any:
    """反序列化 JSON 字符串"""
    if not data:
        return None
    return json.loads(data)


def _first_image(images: List[str], cover: Optional[str] = None) -> Optional[str]:
    """取第一张可用图片 URL（优先封面），供历史卡片封面使用。"""
    candidates = ([cover] if cover else []) + list(images or [])
    for url in candidates:
        if url and str(url).strip():
            return str(url).strip()
    return None


def _pick_cover_image(response_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """从行程响应数据中挑选首张景点/美食图片作为历史卡片封面。"""
    if not response_data:
        return None
    for day in response_data.get("days") or []:
        for item in day.get("items") or []:
            place = item.get("place") or {}
            url = _first_image(place.get("images") or [], place.get("cover_image"))
            if url:
                return url
        for meal_key in ("breakfast", "lunch", "dinner"):
            meal = day.get(meal_key) or {}
            url = _first_image(meal.get("images") or [])
            if url:
                return url
        hotel = day.get("hotel") or {}
        url = _first_image(hotel.get("images") or [], hotel.get("cover_image"))
        if url:
            return url
    return None


class DatabaseError(Exception):
    """数据库错误"""
    pass


class StorageService:
    """
    存储服务
    
    提供行程数据的 CRUD 操作和历史查询功能
    """
    
    def __init__(self, database_url: Optional[str] = None):
        self._database_url = database_url or settings.DATABASE_URL
        self._engine = None
        self._session_factory = None
        self._connect()
    
    def _connect(self):
        """建立数据库连接"""
        try:
            # SQLite 不支持 pool_size 和 max_overflow
            is_sqlite = "sqlite" in self._database_url.lower()
            
            engine_kwargs = {
                "echo": settings.DEBUG,
                "pool_pre_ping": not is_sqlite,
            }
            
            if not is_sqlite:
                engine_kwargs.update({
                    "pool_size": 5,
                    "max_overflow": 10,
                })
            
            self._engine = create_engine(self._database_url, **engine_kwargs)
            self._session_factory = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False,
            )
            logger.info(f"数据库连接成功: {self._database_url}")
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise DatabaseError(f"无法连接数据库: {e}")
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        获取数据库会话上下文管理器
        
        Usage:
            with storage_service.get_session() as session:
                trips = session.query(TripHistoryDB).all()
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise DatabaseError(f"数据库操作失败: {e}")
        finally:
            session.close()
    
    @contextmanager
    def get_session_direct(self) -> Generator[Session, None, None]:
        """
        获取数据库会话（不自动过期）
        
        Usage:
            with storage_service.get_session_direct() as session:
                trip = session.query(TripHistoryDB).first()
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise DatabaseError(f"数据库操作失败: {e}")
        finally:
            session.close()
    
    def get_session_with_data(self) -> Generator[Session, None, None]:
        """
        获取数据库会话并立即加载所有数据
        
        Usage:
            with storage_service.get_session_with_data() as session:
                trip = session.query(TripHistoryDB).first()
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise DatabaseError(f"数据库操作失败: {e}")
        finally:
            session.close()
    
    def init_database(self) -> bool:
        """
        初始化数据库表
        
        Returns:
            是否初始化成功
        """
        try:
            Base.metadata.create_all(bind=self._engine)
            logger.info("数据库表初始化成功")
            return True
        except Exception as e:
            logger.error(f"数据库表初始化失败: {e}")
            return False
    
    def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            健康状态信息
        """
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return {
                "status": "healthy",
                "database": "connected",
                "url": self._database_url.split("@")[-1] if "@" in self._database_url else "unknown",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
            }
    
    # ==================== 行程数据 CRUD ====================
    
    def create_trip(
        self,
        request: TripRequest,
        response: TripResponse,
        user_id: Optional[str] = None,
    ) -> str:
        """
        创建行程记录
        
        Args:
            request: 请求数据
            response: 响应数据
            user_id: 用户ID
            
        Returns:
            行程ID
        """
        try:
            with self.get_session() as session:
                # 生成行程ID
                trip_id = response.trip_id or f"TRP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
                
                # 计算总天数
                total_days = (response.end_date - response.start_date).days + 1
                
                # 序列化 JSON 字段（确保 date/datetime 可序列化）；
                # 若未指定 trip_id，先把生成的 ID 回填到响应，保证落库数据自洽
                if not response.trip_id:
                    response = response.model_copy(update={"trip_id": trip_id})
                request_data = json.loads(json_serialize(request.model_dump()))
                response_data = json.loads(json_serialize(response.model_dump()))
                
                # 创建数据库记录
                trip_db = TripHistoryDB(
                    id=trip_id,
                    user_id=user_id,
                    request_data=request_data,
                    response_data=response_data,
                    destination=response.destination,
                    start_date=response.start_date,
                    end_date=response.end_date,
                    total_days=total_days,
                    total_budget=response.budget.total_budget if response.budget else 0,
                    generation_time=response.generation_time,
                    model_used=response.model_used,
                )
                
                session.add(trip_db)
                session.commit()
                
                logger.info(f"行程记录创建成功: {trip_id}")
                return trip_id
                
        except SQLAlchemyError as e:
            logger.error(f"创建行程记录失败: {e}")
            raise DatabaseError(f"创建行程记录失败: {e}")
    
    def get_trip(self, trip_id: str) -> Optional[Dict[str, Any]]:
        """
        获取行程记录
        
        Args:
            trip_id: 行程ID
            
        Returns:
            行程数据字典或None
        """
        try:
            with self.get_session_direct() as session:
                trip = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id == trip_id
                ).first()
                
                if not trip:
                    return None
                
                # 预先加载所有属性到字典
                trip_data = {
                    "id": trip.id,
                    "user_id": trip.user_id,
                    "destination": trip.destination,
                    "start_date": trip.start_date,
                    "end_date": trip.end_date,
                    "total_days": trip.total_days,
                    "total_budget": trip.total_budget,
                    "created_at": trip.created_at,
                    "updated_at": trip.updated_at,
                    "access_count": trip.access_count,
                    "last_accessed_at": trip.last_accessed_at,
                    "is_favorite": trip.is_favorite,
                    "is_shared": trip.is_shared,
                    "share_code": trip.share_code,
                    "user_rating": trip.user_rating,
                    "user_feedback": trip.user_feedback,
                    "exported_formats": trip.exported_formats,
                    "generation_time": trip.generation_time,
                    "model_used": trip.model_used,
                    "request_data": trip.request_data,
                    "response_data": trip.response_data,
                }
                
                # 更新访问统计（需要新事务）
                trip.access_count += 1
                trip.last_accessed_at = datetime.now()
                
                return trip_data
                
        except SQLAlchemyError as e:
            logger.error(f"获取行程记录失败: {e}")
            raise DatabaseError(f"获取行程记录失败: {e}")
    
    def get_trip_as_history(self, trip_id: str) -> Optional[TripHistory]:
        """
        获取行程历史记录（Pydantic格式）
        
        Args:
            trip_id: 行程ID
            
        Returns:
            TripHistory 或 None
        """
        trip_db = self.get_trip(trip_id)
        if not trip_db:
            return None
        
        try:
            # get_trip 返回 dict（trip_data），不能按 ORM 属性访问
            request = TripRequest(**trip_db["request_data"])
            response = TripResponse(**trip_db["response_data"])
            
            return TripHistory(
                history_id=trip_db["id"],
                user_id=trip_db["user_id"],
                request=request,
                response=response,
                created_at=trip_db["created_at"],
                accessed_at=trip_db["last_accessed_at"] or trip_db["created_at"],
                access_count=trip_db["access_count"],
                is_favorite=trip_db["is_favorite"],
                is_shared=trip_db["is_shared"],
                share_code=trip_db["share_code"],
                user_rating=trip_db["user_rating"],
                user_feedback=trip_db["user_feedback"],
                exported_formats=trip_db["exported_formats"] or [],
            )
        except Exception as e:
            logger.error(f"转换行程数据失败: {e}")
            return None
    
    def update_trip(self, trip_id: str, **updates) -> bool:
        """
        更新行程记录
        
        Args:
            trip_id: 行程ID
            **updates: 要更新的字段
            
        Returns:
            是否更新成功
        """
        try:
            with self.get_session() as session:
                trip = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id == trip_id
                ).first()
                
                if not trip:
                    return False
                
                # 允许更新的字段
                allowed_fields = {
                    "is_favorite", "user_rating", "user_feedback",
                    "exported_formats", "is_shared", "share_code",
                    "response_data", "request_data",
                }
                
                for key, value in updates.items():
                    if key in allowed_fields and hasattr(trip, key):
                        setattr(trip, key, value)
                
                trip.updated_at = datetime.now()
                session.commit()
                return True
                
        except SQLAlchemyError as e:
            logger.error(f"更新行程记录失败: {e}")
            raise DatabaseError(f"更新行程记录失败: {e}")
    
    def delete_trip(self, trip_id: str) -> bool:
        """
        删除行程记录
        
        Args:
            trip_id: 行程ID
            
        Returns:
            是否删除成功
        """
        try:
            with self.get_session() as session:
                result = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id == trip_id
                ).delete()
                session.commit()
                return result > 0
                
        except SQLAlchemyError as e:
            logger.error(f"删除行程记录失败: {e}")
            raise DatabaseError(f"删除行程记录失败: {e}")

    def delete_trips(self, trip_ids: List[str]) -> int:
        """
        批量删除行程记录
        
        Args:
            trip_ids: 行程ID列表
            
        Returns:
            删除的记录数
        """
        if not trip_ids:
            return 0
        try:
            with self.get_session() as session:
                result = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id.in_(trip_ids)
                ).delete(synchronize_session=False)
                session.commit()
                return result
                
        except SQLAlchemyError as e:
            logger.error(f"批量删除行程记录失败: {e}")
            raise DatabaseError(f"批量删除行程记录失败: {e}")

    def set_favorites(self, trip_ids: List[str], is_favorite: bool) -> int:
        """
        批量设置收藏状态
        
        Args:
            trip_ids: 行程ID列表
            is_favorite: 是否收藏
            
        Returns:
            更新的记录数
        """
        if not trip_ids:
            return 0
        try:
            with self.get_session() as session:
                result = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id.in_(trip_ids)
                ).update(
                    {"is_favorite": is_favorite, "updated_at": datetime.now()},
                    synchronize_session=False,
                )
                session.commit()
                return result
                
        except SQLAlchemyError as e:
            logger.error(f"批量设置收藏状态失败: {e}")
            raise DatabaseError(f"批量设置收藏状态失败: {e}")
    
    # ==================== 历史记录查询 ====================
    
    def list_trips(
        self,
        user_id: Optional[str] = None,
        destination: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        列出行程记录
        
        Args:
            user_id: 用户ID筛选
            destination: 目的地筛选
            is_favorite: 是否收藏
            limit: 每页数量
            offset: 偏移量
            order_by: 排序字段
            order_desc: 是否降序
            
        Returns:
            (行程列表, 总数)
        """
        try:
            with self.get_session_direct() as session:
                query = session.query(TripHistoryDB)
                
                # 筛选条件
                filters = []
                if user_id:
                    filters.append(TripHistoryDB.user_id == user_id)
                if destination:
                    filters.append(TripHistoryDB.destination.like(f"%{destination}%"))
                if is_favorite is not None:
                    filters.append(TripHistoryDB.is_favorite == is_favorite)
                
                if filters:
                    query = query.filter(and_(*filters))
                
                # 排序
                order_column = getattr(TripHistoryDB, order_by, TripHistoryDB.created_at)
                if order_desc:
                    query = query.order_by(desc(order_column))
                else:
                    query = query.order_by(asc(order_column))
                
                # 总数
                total = query.count()
                
                # 分页
                trips_db = query.offset(offset).limit(limit).all()
                
                # 转换为字典
                trips = [
                    {
                        "id": t.id,
                        "user_id": t.user_id,
                        "destination": t.destination,
                        "start_date": t.start_date,
                        "end_date": t.end_date,
                        "total_days": t.total_days,
                        "total_budget": t.total_budget,
                        "created_at": t.created_at,
                        "updated_at": t.updated_at,
                        "is_favorite": t.is_favorite,
                        "is_shared": t.is_shared,
                        "share_code": t.share_code,
                        "access_count": t.access_count,
                        "user_rating": t.user_rating,
                        "model_used": t.model_used,
                        "generation_time": t.generation_time,
                        "cover_image": _pick_cover_image(t.response_data),
                    }
                    for t in trips_db
                ]
                
                return trips, total
                
        except SQLAlchemyError as e:
            logger.error(f"查询行程列表失败: {e}")
            raise DatabaseError(f"查询行程列表失败: {e}")
    
    def search_trips(
        self,
        keyword: str,
        user_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        搜索行程记录
        
        Args:
            keyword: 搜索关键词
            user_id: 用户ID筛选
            limit: 返回数量
            
        Returns:
            匹配的行程列表
        """
        try:
            with self.get_session_direct() as session:
                # 搜索条件：目的地
                query = session.query(TripHistoryDB).filter(
                    TripHistoryDB.destination.like(f"%{keyword}%")
                )
                
                if user_id:
                    query = query.filter(TripHistoryDB.user_id == user_id)
                
                trips_db = query.order_by(desc(TripHistoryDB.created_at)).limit(limit).all()
                
                # 转换为字典
                return [
                    {
                        "id": t.id,
                        "user_id": t.user_id,
                        "destination": t.destination,
                        "start_date": t.start_date,
                        "end_date": t.end_date,
                        "total_days": t.total_days,
                        "total_budget": t.total_budget,
                        "created_at": t.created_at,
                    }
                    for t in trips_db
                ]
                
        except SQLAlchemyError as e:
            logger.error(f"搜索行程失败: {e}")
            raise DatabaseError(f"搜索行程失败: {e}")
    
    def get_user_trip_count(self, user_id: str) -> int:
        """
        获取用户的行程数量
        
        Args:
            user_id: 用户ID
            
        Returns:
            行程数量
        """
        try:
            with self.get_session() as session:
                return session.query(TripHistoryDB).filter(
                    TripHistoryDB.user_id == user_id
                ).count()
        except SQLAlchemyError as e:
            logger.error(f"查询用户行程数量失败: {e}")
            return 0
    
    def get_favorites(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取用户收藏的行程
        
        Args:
            user_id: 用户ID
            limit: 返回数量
            
        Returns:
            收藏行程列表
        """
        try:
            with self.get_session_direct() as session:
                trips_db = session.query(TripHistoryDB).filter(
                    and_(
                        TripHistoryDB.user_id == user_id,
                        TripHistoryDB.is_favorite == True
                    )
                ).order_by(desc(TripHistoryDB.updated_at)).limit(limit).all()
                
                return [
                    {
                        "id": t.id,
                        "destination": t.destination,
                        "start_date": t.start_date,
                        "end_date": t.end_date,
                        "total_days": t.total_days,
                        "total_budget": t.total_budget,
                        "created_at": t.created_at,
                        "user_rating": t.user_rating,
                    }
                    for t in trips_db
                ]
        except SQLAlchemyError as e:
            logger.error(f"查询收藏行程失败: {e}")
            return []
    
    def toggle_favorite(self, trip_id: str) -> bool:
        """
        切换收藏状态
        
        Args:
            trip_id: 行程ID
            
        Returns:
            新的收藏状态
        """
        try:
            with self.get_session() as session:
                trip = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id == trip_id
                ).first()
                
                if not trip:
                    return False
                
                trip.is_favorite = not trip.is_favorite
                trip.updated_at = datetime.now()
                session.commit()
                
                return trip.is_favorite
                
        except SQLAlchemyError as e:
            logger.error(f"切换收藏状态失败: {e}")
            raise DatabaseError(f"切换收藏状态失败: {e}")
    
    def generate_share_code(self, trip_id: str) -> Optional[str]:
        """
        生成分享码
        
        Args:
            trip_id: 行程ID
            
        Returns:
            分享码
        """
        try:
            with self.get_session() as session:
                trip = session.query(TripHistoryDB).filter(
                    TripHistoryDB.id == trip_id
                ).first()
                
                if not trip:
                    return None
                
                # 如果已有分享码，直接返回
                if trip.share_code:
                    return trip.share_code
                
                # 生成新的分享码
                share_code = uuid.uuid4().hex[:8].upper()
                
                trip.share_code = share_code
                trip.is_shared = True
                trip.updated_at = datetime.now()
                session.commit()
                
                return share_code
                
        except SQLAlchemyError as e:
            logger.error(f"生成分享码失败: {e}")
            raise DatabaseError(f"生成分享码失败: {e}")
    
    def get_by_share_code(self, share_code: str) -> Optional[Dict[str, Any]]:
        """
        通过分享码获取行程
        
        Args:
            share_code: 分享码
            
        Returns:
            行程数据
        """
        try:
            with self.get_session_direct() as session:
                trip = session.query(TripHistoryDB).filter(
                    TripHistoryDB.share_code == share_code
                ).first()
                
                if not trip:
                    return None
                
                return {
                    "id": trip.id,
                    "destination": trip.destination,
                    "start_date": trip.start_date,
                    "end_date": trip.end_date,
                    "total_days": trip.total_days,
                    "response_data": trip.response_data,
                }
        except SQLAlchemyError as e:
            logger.error(f"通过分享码查询行程失败: {e}")
            return None
    
    # ==================== 数据导出接口 ====================
    
    def export_trip(
        self,
        trip_id: str,
        export_format: str = "json",
    ) -> Optional[Dict[str, Any]]:
        """
        导出行程数据
        
        Args:
            trip_id: 行程ID
            export_format: 导出格式 (json, summary)
            
        Returns:
            导出的数据
        """
        trip = self.get_trip(trip_id)
        if not trip:
            return None
        
        # 记录导出格式
        current_formats = trip.get("exported_formats") or []
        self.update_trip(
            trip_id,
            exported_formats=current_formats + [export_format]
        )
        
        if export_format == "json":
            return {
                "request": trip.get("request_data"),
                "response": trip.get("response_data"),
                "metadata": {
                    "trip_id": trip.get("id"),
                    "created_at": trip.get("created_at"),
                    "destination": trip.get("destination"),
                    "total_days": trip.get("total_days"),
                }
            }
        elif export_format == "summary":
            return {
                "destination": trip.get("destination"),
                "start_date": trip.get("start_date"),
                "end_date": trip.get("end_date"),
                "total_days": trip.get("total_days"),
                "total_budget": trip.get("total_budget"),
                "model_used": trip.get("model_used"),
                "generation_time": trip.get("generation_time"),
            }
        
        return None
    
    def batch_export(
        self,
        trip_ids: List[str],
        export_format: str = "json",
    ) -> List[Dict[str, Any]]:
        """
        批量导出行程
        
        Args:
            trip_ids: 行程ID列表
            export_format: 导出格式
            
        Returns:
            导出数据列表
        """
        results = []
        for trip_id in trip_ids:
            data = self.export_trip(trip_id, export_format)
            if data:
                results.append(data)
        return results
    
    # ==================== 数据统计接口 ====================
    
    def get_statistics(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取统计信息
        
        Args:
            user_id: 用户ID筛选
            
        Returns:
            统计数据
        """
        try:
            with self.get_session() as session:
                query = session.query(TripHistoryDB)
                
                if user_id:
                    query = query.filter(TripHistoryDB.user_id == user_id)
                
                # 总行程数
                total_trips = query.count()
                
                # 总预算
                total_budget = session.query(
                    func.sum(TripHistoryDB.total_budget)
                ).filter(
                    TripHistoryDB.user_id == user_id if user_id else True
                ).scalar() or 0
                
                # 收藏数
                favorites_count = query.filter(
                    TripHistoryDB.is_favorite == True
                ).count()
                
                # 平均生成时间
                avg_generation_time = session.query(
                    func.avg(TripHistoryDB.generation_time)
                ).filter(
                    TripHistoryDB.user_id == user_id if user_id else True,
                    TripHistoryDB.generation_time.isnot(None)
                ).scalar() or 0
                
                # 热门目的地
                popular_destinations = session.query(
                    TripHistoryDB.destination,
                    func.count(TripHistoryDB.id).label("count")
                ).filter(
                    TripHistoryDB.user_id == user_id if user_id else True
                ).group_by(
                    TripHistoryDB.destination
                ).order_by(
                    desc("count")
                ).limit(5).all()
                
                # 最近的行程
                recent_trips = query.order_by(
                    desc(TripHistoryDB.created_at)
                ).limit(5).all()
                
                return {
                    "total_trips": total_trips,
                    "total_budget": round(total_budget, 2),
                    "favorites_count": favorites_count,
                    "avg_generation_time": round(avg_generation_time, 2),
                    "popular_destinations": [
                        {"destination": d, "count": c}
                        for d, c in popular_destinations
                    ],
                    "recent_trips": [
                        {
                            "trip_id": t.id,
                            "destination": t.destination,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                        }
                        for t in recent_trips
                    ],
                }
                
        except SQLAlchemyError as e:
            logger.error(f"获取统计信息失败: {e}")
            raise DatabaseError(f"获取统计信息失败: {e}")
    
    def get_usage_stats(
        self,
        days: int = 30,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取使用统计（按天聚合）
        
        Args:
            days: 统计天数
            user_id: 用户ID筛选
            
        Returns:
            每日使用统计
        """
        try:
            with self.get_session() as session:
                start_date = datetime.now() - timedelta(days=days)
                
                query = session.query(
                    func.date(TripHistoryDB.created_at).label("date"),
                    func.count(TripHistoryDB.id).label("count"),
                    func.sum(TripHistoryDB.generation_time).label("total_time"),
                ).filter(
                    TripHistoryDB.created_at >= start_date,
                    TripHistoryDB.user_id == user_id if user_id else True,
                ).group_by(
                    func.date(TripHistoryDB.created_at)
                ).order_by("date")
                
                results = query.all()
                
                return {
                    "period_days": days,
                    "daily_stats": [
                        {
                            "date": str(r.date),
                            "trip_count": r.count,
                            "total_generation_time": round(r.total_time or 0, 2),
                        }
                        for r in results
                    ],
                }
                
        except SQLAlchemyError as e:
            logger.error(f"获取使用统计失败: {e}")
            raise DatabaseError(f"获取使用统计失败: {e}")
    
    def get_destination_stats(self) -> List[Dict[str, Any]]:
        """
        获取目的地统计
        
        Returns:
            各目的地统计
        """
        try:
            with self.get_session() as session:
                results = session.query(
                    TripHistoryDB.destination,
                    func.count(TripHistoryDB.id).label("trip_count"),
                    func.avg(TripHistoryDB.total_budget).label("avg_budget"),
                    func.max(TripHistoryDB.generation_time).label("avg_time"),
                ).group_by(
                    TripHistoryDB.destination
                ).order_by(
                    desc("trip_count")
                ).all()
                
                return [
                    {
                        "destination": r.destination,
                        "trip_count": r.trip_count,
                        "avg_budget": round(r.avg_budget or 0, 2),
                        "avg_generation_time": round(r.avg_time or 0, 2),
                    }
                    for r in results
                ]
                
        except SQLAlchemyError as e:
            logger.error(f"获取目的地统计失败: {e}")
            raise DatabaseError(f"获取目的地统计失败: {e}")
    
    # ==================== 用户偏好 ====================
    
    def save_user_preference(
        self,
        user_id: str,
        preferences: Dict[str, Any],
    ) -> bool:
        """
        保存用户偏好
        
        Args:
            user_id: 用户ID
            preferences: 偏好设置
            
        Returns:
            是否保存成功
        """
        try:
            with self.get_session() as session:
                # 查找现有偏好
                pref = session.query(UserPreferenceDB).filter(
                    UserPreferenceDB.user_id == user_id
                ).first()
                
                if pref:
                    # 更新
                    for key, value in preferences.items():
                        if hasattr(pref, key):
                            setattr(pref, key, value)
                else:
                    # 创建
                    pref = UserPreferenceDB(
                        user_id=user_id,
                        travel_style=preferences.get("travel_style", "relaxed"),
                        budget_level=preferences.get("budget_level", "standard"),
                    )
                    session.add(pref)
                
                session.commit()
                return True
                
        except SQLAlchemyError as e:
            logger.error(f"保存用户偏好失败: {e}")
            raise DatabaseError(f"保存用户偏好失败: {e}")
    
    def get_user_preference(self, user_id: str) -> Optional[UserPreferenceDB]:
        """
        获取用户偏好
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户偏好或None
        """
        try:
            with self.get_session() as session:
                return session.query(UserPreferenceDB).filter(
                    UserPreferenceDB.user_id == user_id
                ).first()
        except SQLAlchemyError as e:
            logger.error(f"获取用户偏好失败: {e}")
            return None
    
    # ==================== 清理和维护 ====================
    
    def cleanup_old_records(self, days: int = 90) -> int:
        """
        清理旧记录
        
        Args:
            days: 保留天数
            
        Returns:
            删除的记录数
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with self.get_session() as session:
                result = session.query(TripHistoryDB).filter(
                    TripHistoryDB.created_at < cutoff_date,
                    TripHistoryDB.is_favorite == False,  # 不删除收藏的
                ).delete()
                session.commit()
                
                logger.info(f"清理了 {result} 条旧记录")
                return result
                
        except SQLAlchemyError as e:
            logger.error(f"清理旧记录失败: {e}")
            raise DatabaseError(f"清理旧记录失败: {e}")


# 全局存储服务实例
storage_service = StorageService()
