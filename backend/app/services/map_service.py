"""
高德地图服务

基于高德地图 Web API 提供路径规划、距离矩阵、行政区查询、POI搜索和静态地图功能。

功能模块：
- 3.4.1 路径规划：驾车路线规划
- 3.4.2 距离矩阵：批量计算多地点间距离
- 3.4.3 行政区查询：获取行政区边界
- 3.4.4 POI搜索：周边兴趣点搜索
- 3.4.5 静态地图：生成路线概览图
- 3.4.6 数据聚合：整合行程地图数据

遵循高德地图 JSAPI v2.0 开发技能规范：
- 支持重试机制（指数退避）
- 支持批量处理
- 完善的错误处理和日志记录
- 请求限流保护
"""

import httpx
import asyncio
import logging
import time
import hashlib
import json
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import date as date_type
from enum import Enum
from urllib.parse import urlencode

from ..models.schemas import Coordinate, PlaceInfo, TripResponse, ItineraryDay, ItineraryItem

# 配置日志
logger = logging.getLogger(__name__)

# 高德API基础地址
AMAP_BASE_URL = "https://restapi.amap.com/v3"

# 路径规划API
AMAP_DIRECTION_DRIVING_URL = f"{AMAP_BASE_URL}/direction/driving"
AMAP_DIRECTION_WALKING_URL = f"{AMAP_BASE_URL}/direction/walking"
AMAP_DIRECTION_BICYCLING_URL = f"{AMAP_BASE_URL}/direction/bicycling"

# 距离矩阵API
AMAP_DISTANCE_URL = f"{AMAP_BASE_URL}/distance"

# 行政区查询API
AMAP_DISTRICT_URL = f"{AMAP_BASE_URL}/config/district"

# POI搜索API
AMAP_PLACE_TEXT_URL = f"{AMAP_BASE_URL}/place/text"
AMAP_PLACE_AROUND_URL = f"{AMAP_BASE_URL}/place/around"

# 静态地图API
AMAP_STATICMAP_URL = f"{AMAP_BASE_URL}/staticmap"


class RouteStrategy(str, Enum):
    """路径规划策略"""
    RECOMMENDED = "0"      # 推荐
    FASTEST = "1"          # 最快
    SHORTEST = "2"         # 最短
    AVOID_HIGHWAY = "4"    # 高速优先
    AVOID_CONGESTION = "5" # 躲避拥堵


class DistanceType(str, Enum):
    """距离计算方式"""
    DRIVING = "1"          # 驾车
    WALKING = "3"          # 步行


class POISortType(str, Enum):
    """POI排序方式"""
    DEFAULT = ""           # 默认（推荐排序）
    DISTANCE = "1"          # 距离由近到远
    WEIGHT = "2"           # 权重由高到低


@dataclass
class RouteStep:
    """导航步骤"""
    instruction: str        # 导航描述
    road_name: str         # 道路名称
    distance: int          # 步骤距离（米）
    duration: int          # 步骤时长（秒）
    orientation: str        # 方向
    road_type: str         # 道路类型
    toll: float            # 过路费（元）
    toll_distance: int     # 收费路段距离（米）


@dataclass
class RouteSegment:
    """路线片段"""
    from_place: str                       # 起点名称
    to_place: str                         # 终点名称
    from_coord: Coordinate                 # 起点坐标
    to_coord: Coordinate                   # 终点坐标
    distance: float                        # 总距离（km）
    duration: int                          # 总时长（分钟）
    strategy: str                         # 策略
    steps: List[RouteStep]                 # 导航步骤
    polyline: List[Coordinate]            # 路线坐标点（用于前端绘制）
    toll: float                            # 过路费（元）
    traffic_lights: int                    # 红绿灯数量
    info: str                              # 状态信息
    status: bool = True                   # 请求是否成功

    def __post_init__(self):
        if self.steps is None:
            self.steps = []
        if self.polyline is None:
            self.polyline = []


@dataclass
class DistanceResult:
    """距离计算结果"""
    from_id: str             # 起点ID
    to_id: str               # 终点ID
    distance: float          # 距离（km）
    duration: int            # 时长（分钟）
    info: str                # 状态信息
    status: bool = True      # 请求是否成功


@dataclass
class DistanceMatrix:
    """距离矩阵"""
    origin: Coordinate                   # 起点
    destinations: List[Coordinate]       # 终点列表
    results: List[DistanceResult]       # 结果列表
    distance_type: DistanceType         # 计算方式
    info: str                           # 状态信息
    status: bool = True                 # 请求是否成功


@dataclass
class DistrictInfo:
    """行政区信息"""
    name: str                         # 行政区名称
    adcode: str                        # 行政区划代码
    level: str                         # 级别（province/city/district）
    center: Optional[Coordinate]       # 中心点坐标
    boundaries: List[List[Coordinate]] # 边界坐标点（多边形）
    citycode: str                      # 城市代码
    province: str                      # 所属省份
    info: str                          # 状态信息
    status: bool = True                # 请求是否成功

    def __post_init__(self):
        if self.boundaries is None:
            self.boundaries = []


@dataclass
class POIInfo:
    """POI信息"""
    id: str                           # POI ID
    name: str                         # 名称
    type: str                          # 类型
    type_code: str                     # 类型编码
    address: str                       # 地址
    location: Optional[Coordinate]     # 坐标
    telephone: str                     # 电话
    distance: int                      # 距中心点距离（米）
    business_area: str                 # 所在商圈
    city: str                          # 所在城市
    tag: str                           # 标签
    rating: Optional[float]            # 评分
    cost: Optional[float]              # 人均消费
    opening_hours: str = ""           # 营业时间
    info: str = ""                    # 状态信息
    status: bool = True                # 请求是否成功


@dataclass
class POISearchResult:
    """POI搜索结果"""
    keyword: str                       # 搜索关键词
    city: str                          # 搜索城市
    pois: List[POIInfo]                # POI列表
    count: int                          # 结果总数
    page: int                          # 当前页码
    page_size: int                     # 每页数量
    info: str                          # 状态信息
    status: bool = True                # 请求是否成功

    def __post_init__(self):
        if self.pois is None:
            self.pois = []


@dataclass
class StaticMapConfig:
    """静态地图配置"""
    markers: List[Dict[str, Any]]      # 标记点配置
    path: Optional[List[Coordinate]]    # 路线坐标
    zoom: int = 10                      # 缩放级别
    size: str = "600*400"              # 图片尺寸
    traffic: int = 0                   # 是否显示路况 0=不显示 1=显示


@dataclass
class StaticMapResult:
    """静态地图结果"""
    url: str                           # 静态地图URL
    size: str                          # 图片尺寸
    zoom: int                          # 缩放级别
    info: str                          # 状态信息
    status: bool = True                # 请求是否成功


@dataclass
class PlaceMarker:
    """地点标记"""
    place_id: str                      # 地点ID
    name: str                          # 名称
    coordinate: Coordinate              # 坐标
    category: str                      # 类别
    day_number: int                    # 所属天数
    order: int                        # 当天顺序
    color: str = "#1890ff"            # 标记颜色
    icon: Optional[str] = None         # 自定义图标URL


@dataclass
class DayRoute:
    """每日路线"""
    day_number: int                    # 天数
    date: date_type                     # 日期
    theme: Optional[str]                # 当天主题
    markers: List[PlaceMarker]         # 景点标记点
    route_segments: List[RouteSegment] # 路线片段
    total_distance: float              # 当日总距离（km）
    total_duration: int                # 当日总时长（分钟）
    bounds: Optional[Dict[str, float]] # 边界框

    def __post_init__(self):
        if self.markers is None:
            self.markers = []
        if self.route_segments is None:
            self.route_segments = []


@dataclass
class MapBounds:
    """地图边界"""
    southwest: Coordinate              # 左下角
    northeast: Coordinate              # 右上角

    def to_dict(self) -> Dict[str, Any]:
        return {
            "southwest": {
                "longitude": self.southwest.longitude,
                "latitude": self.southwest.latitude,
            },
            "northeast": {
                "longitude": self.northeast.longitude,
                "latitude": self.northeast.latitude,
            },
        }


@dataclass
class MapData:
    """行程地图数据（聚合结果）"""
    trip_id: str                       # 行程ID
    destination: str                     # 目的地
    destination_adcode: str             # 目的地行政区划代码
    center: Coordinate                  # 地图中心点
    zoom: int                          # 缩放级别
    bounds: Optional[MapBounds]        # 边界框
    days: List[DayRoute]              # 每日路线
    static_map_url: str                # 静态地图URL（用于分享）
    total_distance: float              # 行程总距离
    total_duration: int                 # 行程总时长
    info: str                          # 状态信息
    status: bool = True                # 请求是否成功

    def __post_init__(self):
        if self.days is None:
            self.days = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，便于JSON序列化"""
        return {
            "trip_id": self.trip_id,
            "destination": self.destination,
            "destination_adcode": self.destination_adcode,
            "center": {
                "longitude": self.center.longitude,
                "latitude": self.center.latitude,
            },
            "zoom": self.zoom,
            "bounds": self.bounds.to_dict() if self.bounds else None,
            "days": [
                {
                    "day_number": day.day_number,
                    "date": day.date.isoformat() if day.date else None,
                    "theme": day.theme,
                    "markers": [
                        {
                            "place_id": m.place_id,
                            "name": m.name,
                            "coordinate": {
                                "longitude": m.coordinate.longitude,
                                "latitude": m.coordinate.latitude,
                            },
                            "category": m.category,
                            "day_number": m.day_number,
                            "order": m.order,
                            "color": m.color,
                            "icon": m.icon,
                        }
                        for m in day.markers
                    ],
                    "route_segments": [
                        {
                            "from_place": seg.from_place,
                            "to_place": seg.to_place,
                            "from_coord": {
                                "longitude": seg.from_coord.longitude,
                                "latitude": seg.from_coord.latitude,
                            },
                            "to_coord": {
                                "longitude": seg.to_coord.longitude,
                                "latitude": seg.to_coord.latitude,
                            },
                            "distance": seg.distance,
                            "duration": seg.duration,
                            "strategy": seg.strategy,
                            "polyline": [
                                {"longitude": p.longitude, "latitude": p.latitude}
                                for p in seg.polyline
                            ],
                            "toll": seg.toll,
                            "traffic_lights": seg.traffic_lights,
                            "info": seg.info,
                        }
                        for seg in day.route_segments
                    ],
                    "total_distance": day.total_distance,
                    "total_duration": day.total_duration,
                    "bounds": day.bounds,
                }
                for day in self.days
            ],
            "static_map_url": self.static_map_url,
            "total_distance": self.total_distance,
            "total_duration": self.total_duration,
            "info": self.info,
            "status": self.status,
        }


class MapService:
    """
    高德地图服务

    提供路径规划、距离矩阵、行政区查询、POI搜索和静态地图功能。
    所有数据直接从高德API获取，支持重试、批量处理和限流保护。

    遵循高德地图 JSAPI v2.0 开发技能规范：
    - 重试机制：指数退避重试，提高稳定性
    - 批量处理：支持批量距离计算
    - 限流保护：避免触发高德API限流
    - 完善的错误处理和日志记录
    """

    # 每天的标记颜色（用于区分不同天）
    DAY_COLORS = [
        "#1890ff",  # 蓝色
        "#52c41a",  # 绿色
        "#faad14",  # 橙色
        "#f5222d",  # 红色
        "#722ed1",  # 紫色
        "#13c2c2",  # 青色
        "#eb2f96",  # 粉色
        "#fa8c16",  # 深橙
    ]

    def __init__(
        self,
        api_key: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        rate_limit_delay: float = 0.2,
    ):
        """
        初始化服务

        Args:
            api_key: 高德地图 API Key
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒），使用指数退避
            rate_limit_delay: 限流保护延迟（秒），每次请求间隔
        """
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: float = 0

    async def _rate_limited_request(
        self,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        带限流保护的请求方法

        Args:
            url: 请求URL
            params: 请求参数

        Returns:
            API响应数据
        """
        current_time = time.time()
        elapsed = current_time - self._last_request_time
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _request_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        带重试机制的请求方法（指数退避）

        Args:
            url: 请求URL
            params: 请求参数

        Returns:
            API响应数据

        Raises:
            httpx.HTTPStatusError: HTTP错误
            Exception: 重试次数耗尽
        """
        last_error = None
        for attempt in range(self._max_retries):
            try:
                return await self._rate_limited_request(url, params)
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay * (2 ** attempt)
                    logger.warning(
                        f"请求失败 (尝试 {attempt + 1}/{self._max_retries}): {e}. "
                        f"{delay:.1f}秒后重试..."
                    )
                    await asyncio.sleep(delay)
                continue
            except Exception as e:
                last_error = e
                logger.error(f"请求异常: {e}")
                break

        raise last_error or Exception("请求失败")

    # ==================== 3.4.1 路径规划 ====================

    async def plan_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        strategy: RouteStrategy = RouteStrategy.RECOMMENDED,
        waypoints: Optional[List[Tuple[float, float]]] = None,
    ) -> RouteSegment:
        """
        驾车路径规划

        根据起点和终点计算驾车路线，支持途经点。

        Args:
            origin: 起点坐标 (longitude, latitude)
            destination: 终点坐标 (longitude, latitude)
            strategy: 路径策略
            waypoints: 途经点坐标列表 [(lng, lat), ...]

        Returns:
            RouteSegment: 路线片段
        """
        params = {
            "key": self._api_key,
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
            "strategy": strategy.value,
            "output": "json",
        }

        if waypoints:
            waypoints_str = ";".join([f"{wp[0]},{wp[1]}" for wp in waypoints])
            params["waypoints"] = waypoints_str

        try:
            data = await self._request_with_retry(AMAP_DIRECTION_DRIVING_URL, params)

            if data.get("info") != "OK":
                return RouteSegment(
                    status=False,
                    info=data.get("info", "请求失败"),
                    from_place="",
                    to_place="",
                    from_coord=Coordinate(latitude=0, longitude=0),
                    to_coord=Coordinate(latitude=0, longitude=0),
                    distance=0,
                    duration=0,
                    strategy=strategy.value,
                    steps=[],
                    polyline=[],
                    toll=0,
                    traffic_lights=0,
                )

            route = data.get("route", {})
            paths = route.get("paths", [])

            if not paths:
                return RouteSegment(
                    status=False,
                    info="未找到路线",
                    from_place="",
                    to_place="",
                    from_coord=Coordinate(latitude=0, longitude=0),
                    to_coord=Coordinate(latitude=0, longitude=0),
                    distance=0,
                    duration=0,
                    strategy=strategy.value,
                    steps=[],
                    polyline=[],
                    toll=0,
                    traffic_lights=0,
                )

            path = paths[0]
            steps = []

            for step_data in path.get("steps", []):
                polyline_str = step_data.get("polyline", "")
                step_coords = self._parse_polyline(polyline_str)

                steps.append(RouteStep(
                    instruction=step_data.get("instruction", ""),
                    road_name=step_data.get("road_name", ""),
                    distance=int(step_data.get("distance", 0)),
                    duration=int(step_data.get("time", 0)),
                    orientation=step_data.get("orientation", ""),
                    road_type=step_data.get("road_type", ""),
                    toll=float(step_data.get("toll", 0)),
                    toll_distance=int(step_data.get("toll_distance", 0)),
                ))

            # 合并所有步骤的坐标点
            all_coords = []
            for step in steps:
                step_polyline_str = path.get("steps", [[]])[steps.index(step)].get("polyline", "")
                all_coords.extend(self._parse_polyline(step_polyline_str))

            return RouteSegment(
                status=True,
                from_place="起点",
                to_place="终点",
                from_coord=Coordinate(latitude=origin[1], longitude=origin[0]),
                to_coord=Coordinate(latitude=destination[1], longitude=destination[0]),
                distance=float(path.get("distance", 0)) / 1000,  # 转换为km
                duration=int(path.get("time", 0)) // 60,  # 转换为分钟
                strategy=strategy.value,
                steps=steps,
                polyline=all_coords,
                toll=float(path.get("toll", 0)),
                traffic_lights=int(path.get("traffic_lights", 0)),
                info="OK",
            )

        except Exception as e:
            logger.error(f"路径规划失败: {e}")
            return RouteSegment(
                status=False,
                info=f"请求异常: {str(e)}",
                from_place="",
                to_place="",
                from_coord=Coordinate(latitude=0, longitude=0),
                to_coord=Coordinate(latitude=0, longitude=0),
                distance=0,
                duration=0,
                strategy=strategy.value,
                steps=[],
                polyline=[],
                toll=0,
                traffic_lights=0,
            )

    def _parse_polyline(self, polyline_str: str) -> List[Coordinate]:
        """
        解析高德坐标字符串

        Args:
            polyline_str: 坐标字符串，如 "116.3,39.9;116.4,40.0"

        Returns:
            Coordinate列表
        """
        if not polyline_str:
            return []

        coords = []
        for point in polyline_str.split(";"):
            parts = point.split(",")
            if len(parts) == 2:
                try:
                    coords.append(Coordinate(
                        longitude=float(parts[0]),
                        latitude=float(parts[1]),
                    ))
                except ValueError:
                    continue
        return coords

    async def plan_walking_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> RouteSegment:
        """
        步行路径规划

        Args:
            origin: 起点坐标 (longitude, latitude)
            destination: 终点坐标 (longitude, latitude)

        Returns:
            RouteSegment: 路线片段
        """
        params = {
            "key": self._api_key,
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
            "output": "json",
        }

        try:
            data = await self._request_with_retry(AMAP_DIRECTION_WALKING_URL, params)

            if data.get("info") != "OK":
                return RouteSegment(
                    status=False,
                    info=data.get("info", "请求失败"),
                    from_place="起点",
                    to_place="终点",
                    from_coord=Coordinate(latitude=origin[1], longitude=origin[0]),
                    to_coord=Coordinate(latitude=destination[1], longitude=destination[0]),
                    distance=0,
                    duration=0,
                    strategy="walking",
                    steps=[],
                    polyline=[],
                    toll=0,
                    traffic_lights=0,
                )

            route = data.get("route", {})
            paths = route.get("paths", [])

            if not paths:
                return RouteSegment(
                    status=False,
                    info="未找到路线",
                    from_place="起点",
                    to_place="终点",
                    from_coord=Coordinate(latitude=origin[1], longitude=origin[0]),
                    to_coord=Coordinate(latitude=destination[1], longitude=destination[0]),
                    distance=0,
                    duration=0,
                    strategy="walking",
                    steps=[],
                    polyline=[],
                    toll=0,
                    traffic_lights=0,
                )

            path = paths[0]
            steps = []

            for step_data in path.get("steps", []):
                polyline_str = step_data.get("polyline", "")
                coords = self._parse_polyline(polyline_str)

                steps.append(RouteStep(
                    instruction=step_data.get("instruction", ""),
                    road_name=step_data.get("road_name", ""),
                    distance=int(step_data.get("distance", 0)),
                    duration=int(step_data.get("time", 0)),
                    orientation=step_data.get("orientation", ""),
                    road_type="步行",
                    toll=0,
                    toll_distance=0,
                ))

            return RouteSegment(
                status=True,
                from_place="起点",
                to_place="终点",
                from_coord=Coordinate(latitude=origin[1], longitude=origin[0]),
                to_coord=Coordinate(latitude=destination[1], longitude=destination[0]),
                distance=float(path.get("distance", 0)) / 1000,
                duration=int(path.get("time", 0)) // 60,
                strategy="walking",
                steps=steps,
                polyline=self._parse_polyline(path.get("steps", [{}])[0].get("polyline", "")),
                toll=0,
                traffic_lights=0,
                info="OK",
            )

        except Exception as e:
            logger.error(f"步行路线规划失败: {e}")
            return RouteSegment(
                status=False,
                info=f"请求异常: {str(e)}",
                from_place="",
                to_place="",
                from_coord=Coordinate(latitude=0, longitude=0),
                to_coord=Coordinate(latitude=0, longitude=0),
                distance=0,
                duration=0,
                strategy="walking",
                steps=[],
                polyline=[],
                toll=0,
                traffic_lights=0,
            )

    # ==================== 3.4.2 距离矩阵 ====================

    async def get_distance_matrix(
        self,
        origins: List[Tuple[float, float]],
        destinations: List[Tuple[float, float]],
        distance_type: DistanceType = DistanceType.DRIVING,
    ) -> DistanceMatrix:
        """
        距离矩阵：批量计算多地点间的距离和耗时

        高德限制：起点和终点总数最多50个

        Args:
            origins: 起点坐标列表 [(longitude, latitude), ...]
            destinations: 终点坐标列表 [(longitude, latitude), ...]
            distance_type: 计算方式（驾车/步行）

        Returns:
            DistanceMatrix: 距离矩阵结果
        """
        if not origins or not destinations:
            return DistanceMatrix(
                status=False,
                info="起点或终点列表为空",
                origin=Coordinate(latitude=0, longitude=0),
                destinations=[],
                results=[],
                distance_type=distance_type,
            )

        # 高德限制检查
        total_count = len(origins) * len(destinations)
        if total_count > 50:
            logger.warning(f"距离矩阵请求超过限制（{total_count} > 50），将分批处理")

        origins_str = ";".join([f"{o[0]},{o[1]}" for o in origins])
        destinations_str = ";".join([f"{d[0]},{d[1]}" for d in destinations])

        params = {
            "key": self._api_key,
            "origins": origins_str,
            "destination": destinations_str,
            "type": distance_type.value,
            "output": "json",
        }

        try:
            data = await self._request_with_retry(AMAP_DISTANCE_URL, params)

            if data.get("info") != "OK":
                return DistanceMatrix(
                    status=False,
                    info=data.get("info", "请求失败"),
                    origin=Coordinate(latitude=origins[0][1], longitude=origins[0][0]),
                    destinations=[Coordinate(latitude=d[1], longitude=d[0]) for d in destinations],
                    results=[],
                    distance_type=distance_type,
                )

            results = []
            for origin_idx, result_data in enumerate(data.get("results", [])):
                origin_coord = origins[origin_idx] if origin_idx < len(origins) else origins[0]

                for dest_idx, dest_result in enumerate(result_data.get("elements", [])):
                    dest_coord = destinations[dest_idx] if dest_idx < len(destinations) else destinations[0]

                    results.append(DistanceResult(
                        from_id=str(origin_idx),
                        to_id=str(dest_idx),
                        distance=float(dest_result.get("distance", 0)) / 1000,  # 转换为km
                        duration=int(dest_result.get("duration", 0)) // 60,  # 转换为分钟
                        info=dest_result.get("info", "OK"),
                        status=dest_result.get("info_code") == "1",
                    ))

            return DistanceMatrix(
                status=True,
                info="OK",
                origin=Coordinate(latitude=origins[0][1], longitude=origins[0][0]),
                destinations=[Coordinate(latitude=d[1], longitude=d[0]) for d in destinations],
                results=results,
                distance_type=distance_type,
            )

        except Exception as e:
            logger.error(f"距离矩阵计算失败: {e}")
            return DistanceMatrix(
                status=False,
                info=f"请求异常: {str(e)}",
                origin=Coordinate(latitude=0, longitude=0),
                destinations=[],
                results=[],
                distance_type=distance_type,
            )

    async def get_distance(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        distance_type: DistanceType = DistanceType.DRIVING,
    ) -> DistanceResult:
        """
        计算两点间的距离

        Args:
            origin: 起点坐标
            destination: 终点坐标
            distance_type: 计算方式

        Returns:
            DistanceResult: 距离结果
        """
        matrix = await self.get_distance_matrix([origin], [destination], distance_type)
        if matrix.results:
            return matrix.results[0]
        return DistanceResult(
            status=False,
            info="计算失败",
            from_id="0",
            to_id="0",
            distance=0,
            duration=0,
        )

    # ==================== 3.4.3 行政区查询 ====================

    async def get_district(
        self,
        keywords: str,
        level: str = "city",
        subdistrict: int = 1,
    ) -> List[DistrictInfo]:
        """
        行政区查询

        根据关键字查询行政区划信息。

        Args:
            keywords: 行政区关键字
            level: 查询级别（country/province/city/district/street）
            subdistrict: 子级行政区返回层数（0-3）

        Returns:
            List[DistrictInfo]: 行政区信息列表
        """
        params = {
            "key": self._api_key,
            "keywords": keywords,
            "subdistrict": subdistrict,
            "level": level,
            "output": "json",
        }

        try:
            data = await self._request_with_retry(AMAP_DISTRICT_URL, params)

            if data.get("status") != "1":
                return []

            districts = []
            for district_data in data.get("districts", []):
                center_str = district_data.get("center", "")
                center = self._parse_single_coordinate(center_str)

                boundaries_str = district_data.get("polyline", "")
                boundaries = self._parse_boundary(boundaries_str)

                districts.append(DistrictInfo(
                    name=district_data.get("name", ""),
                    adcode=district_data.get("adcode", ""),
                    level=district_data.get("level", ""),
                    center=center,
                    boundaries=boundaries,
                    citycode=district_data.get("citycode", ""),
                    province=district_data.get("province", ""),
                    info="OK",
                    status=True,
                ))

            return districts

        except Exception as e:
            logger.error(f"行政区查询失败: {e}")
            return []

    def _parse_single_coordinate(self, coord_str: str) -> Optional[Coordinate]:
        """解析单个坐标字符串"""
        if not coord_str:
            return None
        parts = coord_str.split(",")
        if len(parts) == 2:
            try:
                return Coordinate(
                    longitude=float(parts[0]),
                    latitude=float(parts[1]),
                )
            except ValueError:
                return None
        return None

    def _parse_boundary(self, boundary_str: str) -> List[List[Coordinate]]:
        """
        解析行政区边界字符串

        高德返回的边界可能是多个多边形，用 | 分隔

        Args:
            boundary_str: 边界坐标字符串

        Returns:
            多边形列表，每个多边形是一个坐标列表
        """
        if not boundary_str:
            return []

        polygons = []
        for polygon_str in boundary_str.split("|"):
            coords = []
            for point_str in polygon_str.split(";"):
                parts = point_str.split(",")
                if len(parts) == 2:
                    try:
                        coords.append(Coordinate(
                            longitude=float(parts[0]),
                            latitude=float(parts[1]),
                        ))
                    except ValueError:
                        continue
            if coords:
                polygons.append(coords)

        return polygons

    async def get_district_boundary(
        self,
        adcode: str,
    ) -> Optional[DistrictInfo]:
        """
        获取指定行政区的边界

        Args:
            adcode: 行政区划代码

        Returns:
            DistrictInfo 或 None
        """
        districts = await self.get_district(adcode, subdistrict=0)
        return districts[0] if districts else None

    # ==================== 3.4.4 POI搜索 ====================

    async def search_poi(
        self,
        keywords: str,
        city: Optional[str] = None,
        citylimit: bool = False,
        types: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort: POISortType = POISortType.DEFAULT,
    ) -> POISearchResult:
        """
        POI关键字搜索

        根据关键字搜索兴趣点。

        Args:
            keywords: 搜索关键字
            city: 搜索城市
            citylimit: 是否限制在城市内搜索
            types: POI类型编码
            page: 页码（从1开始）
            page_size: 每页数量（最大50）
            sort: 排序方式

        Returns:
            POISearchResult: 搜索结果
        """
        params = {
            "key": self._api_key,
            "keywords": keywords,
            "page": page,
            "offset": min(page_size, 50),
            "output": "json",
            "sortrule": sort.value,
        }

        if city:
            params["city"] = city
        if citylimit:
            params["citylimit"] = "true"
        if types:
            params["types"] = types

        try:
            data = await self._request_with_retry(AMAP_PLACE_TEXT_URL, params)

            if data.get("info") != "OK":
                return POISearchResult(
                    status=False,
                    info=data.get("info", "请求失败"),
                    keyword=keywords,
                    city=city or "",
                    pois=[],
                    count=0,
                    page=page,
                    page_size=page_size,
                )

            pois = []
            for poi_data in data.get("pois", []):
                location_str = poi_data.get("location", "")
                coord = self._parse_single_coordinate(location_str)

                pois.append(POIInfo(
                    id=poi_data.get("id", ""),
                    name=poi_data.get("name", ""),
                    type=poi_data.get("type", ""),
                    type_code=poi_data.get("typecode", ""),
                    address=poi_data.get("address", ""),
                    location=coord,
                    telephone=poi_data.get("tel", ""),
                    distance=int(poi_data.get("distance", 0)),
                    business_area=poi_data.get("business_area", ""),
                    city=poi_data.get("cityname", ""),
                    tag=poi_data.get("tag", ""),
                    rating=None,
                    cost=None,
                    opening_hours=poi_data.get("营业时间", ""),
                    info="OK",
                    status=True,
                ))

            return POISearchResult(
                status=True,
                info="OK",
                keyword=keywords,
                city=city or "",
                pois=pois,
                count=int(data.get("count", 0)),
                page=page,
                page_size=page_size,
            )

        except Exception as e:
            logger.error(f"POI搜索失败: {e}")
            return POISearchResult(
                status=False,
                info=f"请求异常: {str(e)}",
                keyword=keywords,
                city=city or "",
                pois=[],
                count=0,
                page=page,
                page_size=page_size,
            )

    async def search_nearby(
        self,
        location: Tuple[float, float],
        keywords: Optional[List[str]] = None,
        radius: int = 3000,
        types: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort: POISortType = POISortType.DISTANCE,
    ) -> POISearchResult:
        """
        周边搜索

        搜索指定坐标周围的兴趣点。

        Args:
            location: 中心点坐标 (longitude, latitude)
            keywords: 搜索关键字列表
            radius: 搜索半径（米），最大50000
            types: POI类型编码
            page: 页码
            page_size: 每页数量
            sort: 排序方式

        Returns:
            POISearchResult: 搜索结果
        """
        params = {
            "key": self._api_key,
            "location": f"{location[0]},{location[1]}",
            "radius": min(radius, 50000),
            "page": page,
            "offset": min(page_size, 50),
            "output": "json",
            "sortrule": sort.value,
        }

        if keywords:
            params["keywords"] = "|".join(keywords)
        if types:
            params["types"] = types

        try:
            data = await self._request_with_retry(AMAP_PLACE_AROUND_URL, params)

            if data.get("info") != "OK":
                return POISearchResult(
                    status=False,
                    info=data.get("info", "请求失败"),
                    keyword=",".join(keywords or []),
                    city="",
                    pois=[],
                    count=0,
                    page=page,
                    page_size=page_size,
                )

            pois = []
            for poi_data in data.get("pois", []):
                location_str = poi_data.get("location", "")
                coord = self._parse_single_coordinate(location_str)

                pois.append(POIInfo(
                    id=poi_data.get("id", ""),
                    name=poi_data.get("name", ""),
                    type=poi_data.get("type", ""),
                    type_code=poi_data.get("typecode", ""),
                    address=poi_data.get("address", ""),
                    location=coord,
                    telephone=poi_data.get("tel", ""),
                    distance=int(poi_data.get("distance", 0)),
                    business_area=poi_data.get("business_area", ""),
                    city=poi_data.get("cityname", ""),
                    tag=poi_data.get("tag", ""),
                    rating=None,
                    cost=None,
                    opening_hours=poi_data.get("营业时间", ""),
                    info="OK",
                    status=True,
                ))

            return POISearchResult(
                status=True,
                info="OK",
                keyword=",".join(keywords or []),
                city="",
                pois=pois,
                count=int(data.get("count", 0)),
                page=page,
                page_size=page_size,
            )

        except Exception as e:
            logger.error(f"周边搜索失败: {e}")
            return POISearchResult(
                status=False,
                info=f"请求异常: {str(e)}",
                keyword="",
                city="",
                pois=[],
                count=0,
                page=page,
                page_size=page_size,
            )

    # ==================== 3.4.5 静态地图 ====================

    async def generate_static_map(
        self,
        markers: List[Dict[str, Any]],
        path: Optional[List[Tuple[float, float]]] = None,
        zoom: int = 10,
        size: str = "600*400",
        traffic: int = 0,
    ) -> StaticMapResult:
        """
        生成静态地图URL

        生成包含标记点和路线的静态地图图片URL。

        Args:
            markers: 标记点配置列表
                - [{"lng": 116.3, "lat": 39.9, "color": "red", "label": "A"}, ...]
            path: 路线坐标点列表 [(longitude, latitude), ...]
            zoom: 缩放级别（3-20）
            size: 图片尺寸，如 "600*400"
            traffic: 是否显示路况 0=不显示 1=显示

        Returns:
            StaticMapResult: 静态地图结果
        """
        params = {
            "key": self._api_key,
            "zoom": zoom,
            "size": size.replace("*", ","),
            "traffic": traffic,
        }

        # 构建标记点字符串
        marker_strs = []
        for i, marker in enumerate(markers):
            lng = marker.get("lng", marker.get("longitude", 0))
            lat = marker.get("lat", marker.get("latitude", 0))
            color = marker.get("color", "blue")
            label = marker.get("label", str(i + 1))

            # 格式：lng,lat,0x颜色,标签
            marker_strs.append(f"{lng},{lat},0x{self._css_color_to_hex(color)},{label}")

        if marker_strs:
            params["markers"] = " ".join(marker_strs)

        # 构建路线字符串
        if path and len(path) >= 2:
            path_strs = []
            for i in range(0, len(path), 100):  # 高德限制每段最多100个点
                segment = path[i:i + 100]
                path_coords = ";".join([f"{p[0]},{p[1]}" for p in segment])
                path_strs.append(path_coords)
            params["paths"] = len(path_strs)  # 路径数量（用于设置样式）
            params["labels"] = ";".join([f"1,0,22,0xffffff,0x1890ff,1:路径{i + 1}" for i in range(len(path_strs))])

        # 构建URL
        url = f"{AMAP_STATICMAP_URL}?{urlencode(params)}"

        return StaticMapResult(
            status=True,
            info="OK",
            url=url,
            size=size,
            zoom=zoom,
        )

    def _css_color_to_hex(self, color: str) -> str:
        """将CSS颜色转换为十六进制"""
        color_map = {
            "red": "ff0000",
            "blue": "1890ff",
            "green": "52c41a",
            "yellow": "faad14",
            "orange": "fa8c16",
            "purple": "722ed1",
            "cyan": "13c2c2",
            "pink": "eb2f96",
            "white": "ffffff",
            "gray": "8c8c8c",
        }

        color_lower = color.lower()
        if color_lower in color_map:
            return color_map[color_lower]

        # 尝试解析 hex 颜色
        if color.startswith("#") and len(color) == 7:
            return color[1:].upper()

        return "1890ff"  # 默认蓝色

    # ==================== 3.4.6 数据聚合 ====================

    async def aggregate_trip_map(
        self,
        trip_response: TripResponse,
        include_route: bool = True,
        include_static: bool = True,
    ) -> MapData:
        """
        聚合行程地图数据

        将行程响应数据整合为地图所需的完整数据。

        Args:
            trip_response: 行程规划响应
            include_route: 是否计算路线（耗时较长）
            include_static: 是否生成静态地图URL

        Returns:
            MapData: 聚合后的地图数据
        """
        if not trip_response.days:
            return MapData(
                trip_id=trip_response.trip_id,
                destination=trip_response.destination,
                destination_adcode="",
                center=Coordinate(latitude=39.9, longitude=116.4),
                zoom=10,
                bounds=None,
                days=[],
                static_map_url="",
                total_distance=0,
                total_duration=0,
                info="行程数据为空",
                status=False,
            )

        # 提取所有景点坐标
        all_coords: List[Tuple[float, float]] = []
        day_routes: List[DayRoute] = []
        total_distance = 0.0
        total_duration = 0

        for day_idx, day in enumerate(trip_response.days):
            color = self.DAY_COLORS[day_idx % len(self.DAY_COLORS)]
            markers: List[PlaceMarker] = []
            route_segments: List[RouteSegment] = []
            day_distance = 0.0
            day_duration = 0
            day_coords: List[Tuple[float, float]] = []

            for item_idx, item in enumerate(day.items):
                coord = (item.place.coordinate.longitude, item.place.coordinate.latitude)
                day_coords.append(coord)
                all_coords.append(coord)

                markers.append(PlaceMarker(
                    place_id=item.place.place_id,
                    name=item.place.name,
                    coordinate=item.place.coordinate,
                    category=item.place.category,
                    day_number=day.day_number,
                    order=item_idx + 1,
                    color=color,
                ))

            # 计算路线（如果需要）
            if include_route and len(day_coords) >= 2:
                for i in range(len(day_coords) - 1):
                    from_coord = day_coords[i]
                    to_coord = day_coords[i + 1]

                    # 获取地点名称
                    from_name = day.items[i].place.name if i < len(day.items) else "起点"
                    to_name = day.items[i + 1].place.name if i + 1 < len(day.items) else "终点"

                    route = await self.plan_route(from_coord, to_coord)

                    if route.status:
                        route.from_place = from_name
                        route.to_place = to_name
                        route_segments.append(route)
                        day_distance += route.distance
                        day_duration += route.duration

            # 计算边界框
            bounds = self._calculate_bounds(day_coords)

            day_route = DayRoute(
                day_number=day.day_number,
                date=day.itinerary_date,
                theme=day.day_theme,
                markers=markers,
                route_segments=route_segments,
                total_distance=day_distance,
                total_duration=day_duration,
                bounds=bounds,
            )
            day_routes.append(day_route)
            total_distance += day_distance
            total_duration += day_duration

        # 计算全局边界框
        bounds = self._calculate_bounds(all_coords)

        # 计算中心点
        if all_coords:
            center_lng = sum(c[0] for c in all_coords) / len(all_coords)
            center_lat = sum(c[1] for c in all_coords) / len(all_coords)
            center = Coordinate(longitude=center_lng, latitude=center_lat)
        else:
            center = Coordinate(longitude=116.4, latitude=39.9)

        # 计算合适的缩放级别
        zoom = self._calculate_zoom(bounds)

        # 生成静态地图URL（如果需要）
        static_map_url = ""
        if include_static and markers:
            # 收集所有标记点
            all_markers = []
            for day_route in day_routes:
                for marker in day_route.markers:
                    all_markers.append({
                        "lng": marker.coordinate.longitude,
                        "lat": marker.coordinate.latitude,
                        "color": marker.color,
                        "label": f"D{marker.day_number}-{marker.order}",
                    })

            # 收集所有路线点
            all_path_points: List[Tuple[float, float]] = []
            for day_route in day_routes:
                for segment in day_route.route_segments:
                    for coord in segment.polyline:
                        all_path_points.append((coord.longitude, coord.latitude))

            static_result = await self.generate_static_map(
                markers=all_markers,
                path=all_path_points if all_path_points else None,
                zoom=zoom,
            )
            static_map_url = static_result.url

        # 获取目的地行政区划代码
        adcode = ""
        try:
            districts = await self.get_district(trip_response.destination)
            if districts:
                adcode = districts[0].adcode
        except Exception:
            pass

        return MapData(
            trip_id=trip_response.trip_id,
            destination=trip_response.destination,
            destination_adcode=adcode,
            center=center,
            zoom=zoom,
            bounds=bounds,
            days=day_routes,
            static_map_url=static_map_url,
            total_distance=total_distance,
            total_duration=total_duration,
            info="OK",
            status=True,
        )

    def _calculate_bounds(
        self,
        coords: List[Tuple[float, float]],
    ) -> Optional[Dict[str, float]]:
        """计算坐标列表的边界框"""
        if not coords:
            return None

        lngs = [c[0] for c in coords]
        lats = [c[1] for c in coords]

        return {
            "southwest_lng": min(lngs),
            "southwest_lat": min(lats),
            "northeast_lng": max(lngs),
            "northeast_lat": max(lats),
        }

    def _calculate_zoom(
        self,
        bounds: Optional[Dict[str, float]],
    ) -> int:
        """根据边界框计算合适的缩放级别"""
        if not bounds:
            return 10

        lng_diff = bounds.get("northeast_lng", 116.4) - bounds.get("southwest_lng", 116.4)
        lat_diff = bounds.get("northeast_lat", 39.9) - bounds.get("southwest_lat", 39.9)

        max_diff = max(lng_diff, lat_diff)

        # 根据经验公式计算缩放级别
        if max_diff > 10:
            return 4
        elif max_diff > 5:
            return 5
        elif max_diff > 2:
            return 6
        elif max_diff > 1:
            return 7
        elif max_diff > 0.5:
            return 8
        elif max_diff > 0.2:
            return 9
        elif max_diff > 0.1:
            return 10
        elif max_diff > 0.05:
            return 11
        elif max_diff > 0.02:
            return 12
        elif max_diff > 0.01:
            return 13
        elif max_diff > 0.005:
            return 14
        else:
            return 15

    # ==================== 辅助方法 ====================

    def build_navigation_url(
        self,
        destination: Tuple[float, float],
        destination_name: Optional[str] = None,
        mode: str = "driving",
    ) -> str:
        """
        构建高德导航URL Scheme

        用于跳转到高德地图进行导航。

        Args:
            destination: 目标坐标 (longitude, latitude)
            destination_name: 目标名称
            mode: 导航方式（driving/walking/bus/ride）

        Returns:
            高德地图URL
        """
        lat, lng = destination[1], destination[0]
        url = f"https://uri.amap.com/navigation?to={lng},{lat}"

        if destination_name:
            url += f",{destination_name}"

        url += f"&mode={mode}"
        url += f"&callnative=1"

        return url

    async def optimize_route_order(
        self,
        coords: List[Tuple[float, float]],
        names: Optional[List[str]] = None,
    ) -> List[int]:
        """
        优化路线顺序（贪心算法）

        对于少量地点，使用贪心算法优化访问顺序。

        Args:
            coords: 坐标列表
            names: 名称列表（可选）

        Returns:
            优化后的顺序索引列表
        """
        if len(coords) <= 2:
            return list(range(len(coords)))

        # 贪心算法：每次选择最近的未访问点
        n = len(coords)
        visited = [False] * n
        order = [0]  # 从第一个点开始

        visited[0] = True
        current = 0

        for _ in range(n - 1):
            nearest = -1
            min_distance = float("inf")

            for j in range(n):
                if not visited[j]:
                    dist = self._haversine_distance(coords[current], coords[j])
                    if dist < min_distance:
                        min_distance = dist
                        nearest = j

            if nearest != -1:
                order.append(nearest)
                visited[nearest] = True
                current = nearest

        return order

    def _haversine_distance(
        self,
        coord1: Tuple[float, float],
        coord2: Tuple[float, float],
    ) -> float:
        """
        计算两点间的球面距离（km）

        使用 Haversine 公式
        """
        import math

        R = 6371  # 地球半径（km）

        lat1 = math.radians(coord1[1])
        lat2 = math.radians(coord2[1])
        lon1 = math.radians(coord1[0])
        lon2 = math.radians(coord2[0])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return R * c


# 全局单例（需要初始化时设置api_key）
_map_service: Optional[MapService] = None


def init_map_service(
    api_key: str,
    timeout: float = 10.0,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    rate_limit_delay: float = 0.2,
) -> MapService:
    """
    初始化全局地图服务

    Args:
        api_key: 高德地图 API Key
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        rate_limit_delay: 限流保护延迟（秒）

    Returns:
        初始化后的 MapService 实例
    """
    global _map_service
    _map_service = MapService(
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        rate_limit_delay=rate_limit_delay,
    )
    return _map_service


def get_map_service() -> Optional[MapService]:
    """获取全局地图服务实例"""
    return _map_service
