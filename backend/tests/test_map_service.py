"""
智旅云图 - 地图服务测试（3.4.1-3.4.6）

全部 mock _request_with_retry，不打真实高德 API。
覆盖路径规划、距离矩阵、行政区查询、POI 搜索、静态地图与行程聚合。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    TripResponse,
)
from app.services.map_service import (
    AMAP_DISTANCE_URL,
    AMAP_DISTRICT_URL,
    AMAP_DIRECTION_DRIVING_URL,
    AMAP_DIRECTION_WALKING_URL,
    AMAP_PLACE_AROUND_URL,
    AMAP_PLACE_TEXT_URL,
    AMAP_STATICMAP_URL,
    DayRoute,
    DistanceMatrix,
    DistanceResult,
    DistanceType,
    DistrictInfo,
    MapBounds,
    MapData,
    MapService,
    POIInfo,
    POISearchResult,
    POISortType,
    RouteSegment,
    RouteStrategy,
    RouteStep,
    StaticMapResult,
    get_map_service,
    init_map_service,
)


def _driving_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德驾车路径规划 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "route": {
            "paths": [
                {
                    "distance": "15000",
                    "time": "1800",
                    "toll": "5",
                    "traffic_lights": "3",
                    "steps": [
                        {
                            "instruction": "沿长安街行驶",
                            "road_name": "长安街",
                            "distance": "1500",
                            "time": "120",
                            "orientation": "东",
                            "road_type": "主干道",
                            "toll": "0",
                            "toll_distance": "0",
                            "polyline": "116.3,39.9;116.35,39.92",
                        },
                        {
                            "instruction": "右转进入王府井大街",
                            "road_name": "王府井大街",
                            "distance": "500",
                            "time": "60",
                            "orientation": "南",
                            "road_type": "次干道",
                            "toll": "0",
                            "toll_distance": "0",
                            "polyline": "116.35,39.92;116.4,39.9",
                        },
                    ],
                }
            ]
        },
    }
    data.update(kwargs)
    return data


def _walking_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德步行路径规划 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "route": {
            "paths": [
                {
                    "distance": "3000",
                    "time": "1800",
                    "steps": [
                        {
                            "instruction": "向东步行",
                            "road_name": "",
                            "distance": "3000",
                            "time": "1800",
                            "orientation": "东",
                            "polyline": "116.3,39.9;116.4,39.92",
                        }
                    ],
                }
            ]
        },
    }
    data.update(kwargs)
    return data


def _distance_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德距离矩阵 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "results": [
            {
                "elements": [
                    {"distance": "1500", "duration": "180", "info": "OK", "info_code": "1"},
                    {"distance": "0", "duration": "0", "info": "NO_ROUTE", "info_code": "2"},
                ]
            }
        ],
    }
    data.update(kwargs)
    return data


def _district_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德行政区查询 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "districts": [
            {
                "name": "北京市",
                "adcode": "110000",
                "level": "city",
                "center": "116.407526,39.90403",
                "polyline": "116.3,39.8;116.5,39.9",
                "citycode": "010",
                "province": "北京市",
            }
        ],
    }
    data.update(kwargs)
    return data


def _poi_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德 POI 搜索 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "count": "1",
        "pois": [
            {
                "id": "B001",
                "name": "故宫博物院",
                "type": "风景名胜",
                "typecode": "120000",
                "address": "北京市东城区景山前街4号",
                "location": "116.397028,39.918058",
                "tel": "010-85007421",
                "distance": "120",
                "business_area": "王府井",
                "cityname": "北京市",
                "tag": "景点",
                "biz_ext": {"rating": "4.8", "cost": "60"},
                "adcode": "110101",
                "adname": "东城区",
                "photos": [{"url": "https://img.example.com/1.jpg"}],
                "opening_time": "08:30-17:00",
            }
        ],
    }
    data.update(kwargs)
    return data


@pytest.fixture
def service() -> MapService:
    """创建地图服务实例（关闭重试与限流延迟，加速测试）"""
    return MapService(
        api_key="test-key",
        max_retries=1,
        retry_delay=0,
        rate_limit_delay=0,
    )


def _sample_trip(*, days: int = 1, items_per_day: int = 2) -> TripResponse:
    """构造最小完整 TripResponse 用于聚合测试"""
    itinerary_days = []
    for d in range(days):
        items = []
        for i in range(items_per_day):
            items.append(
                ItineraryItem(
                    start_time="09:00",
                    end_time="11:00",
                    place=PlaceInfo(
                        place_id=f"p{d+1}-{i+1}",
                        name=f"第{d+1}天景点{i+1}",
                        address="测试地址",
                        coordinate=Coordinate(
                            longitude=116.3 + i * 0.1,
                            latitude=39.9 + i * 0.1,
                        ),
                        category="景点",
                    ),
                    activity="游览",
                )
            )
        itinerary_days.append(
            ItineraryDay(
                day_number=d + 1,
                itinerary_date=date(2026, 9, 1) + timedelta(days=d),
                items=items,
                total_places=len(items),
                total_duration=240,
            )
        )
    return TripResponse(
        trip_id="TRP-MAP-001",
        destination="北京",
        trip_name="北京测试行程",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1) + timedelta(days=days - 1),
        total_days=days,
        days=itinerary_days,
        budget=BudgetInfo(
            total_budget=1000.0,
            daily_avg_budget=1000.0,
            budget_per_person=500.0,
        ),
    )


class TestParsePolyline:
    """坐标字符串解析"""

    def test_valid(self, service):
        coords = service._parse_polyline("116.3,39.9;116.4,40.0")
        assert len(coords) == 2
        assert coords[0].longitude == 116.3
        assert coords[0].latitude == 39.9

    def test_invalid_points_skipped(self, service):
        coords = service._parse_polyline("116.3,39.9;bad,point")
        assert len(coords) == 1

    def test_empty(self, service):
        assert service._parse_polyline("") == []


@pytest.mark.asyncio
class TestPlanRoute:
    """3.4.1 驾车路径规划"""

    async def test_success(self, service):
        """正常路径规划"""
        service._request_with_retry = AsyncMock(return_value=_driving_api_response())
        route = await service.plan_route((116.3, 39.9), (116.4, 39.9))
        assert route.status is True
        assert route.distance == pytest.approx(15.0)
        assert route.duration == 30
        assert route.strategy == RouteStrategy.RECOMMENDED.value
        assert len(route.steps) == 2
        assert len(route.polyline) == 4
        assert route.toll == 5.0
        assert route.traffic_lights == 3
        assert route.info == "OK"
        # 校验请求参数
        url, params = service._request_with_retry.call_args.args
        assert url == AMAP_DIRECTION_DRIVING_URL
        assert params["origin"] == "116.3,39.9"
        assert params["destination"] == "116.4,39.9"
        assert params["strategy"] == "0"

    async def test_with_waypoints(self, service):
        """带途经点"""
        service._request_with_retry = AsyncMock(return_value=_driving_api_response())
        await service.plan_route(
            (116.3, 39.9),
            (116.4, 39.9),
            waypoints=[(116.35, 39.92)],
        )
        _, params = service._request_with_retry.call_args.args
        assert params["waypoints"] == "116.35,39.92"

    async def test_api_failure(self, service):
        """接口返回失败"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        route = await service.plan_route((116.3, 39.9), (116.4, 39.9))
        assert route.status is False
        assert "INVALID_KEY" in route.info

    async def test_no_paths(self, service):
        """无可用路线"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "1", "info": "OK", "route": {"paths": []}}
        )
        route = await service.plan_route((116.3, 39.9), (116.4, 39.9))
        assert route.status is False
        assert "未找到路线" in route.info

    async def test_exception_returns_failure(self, service):
        """异常时返回失败结果"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        route = await service.plan_route((116.3, 39.9), (116.4, 39.9))
        assert route.status is False
        assert "boom" in route.info


@pytest.mark.asyncio
class TestPlanWalkingRoute:
    """3.4.1 步行路径规划"""

    async def test_success(self, service):
        """正常步行路线"""
        service._request_with_retry = AsyncMock(return_value=_walking_api_response())
        route = await service.plan_walking_route((116.3, 39.9), (116.4, 39.92))
        assert route.status is True
        assert route.distance == pytest.approx(3.0)
        assert route.duration == 30
        assert route.strategy == "walking"
        assert len(route.steps) == 1
        assert route.steps[0].road_type == "步行"

    async def test_api_failure(self, service):
        """接口返回失败"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        route = await service.plan_walking_route((116.3, 39.9), (116.4, 39.92))
        assert route.status is False

    async def test_exception_returns_failure(self, service):
        """异常时返回失败结果"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        route = await service.plan_walking_route((116.3, 39.9), (116.4, 39.92))
        assert route.status is False
        assert "boom" in route.info


@pytest.mark.asyncio
class TestGetDistanceMatrix:
    """3.4.2 距离矩阵"""

    async def test_success(self, service):
        """正常距离矩阵"""
        service._request_with_retry = AsyncMock(return_value=_distance_api_response())
        matrix = await service.get_distance_matrix(
            [(116.3, 39.9)],
            [(116.35, 39.95), (116.4, 39.9)],
        )
        assert matrix.status is True
        assert len(matrix.results) == 2
        assert matrix.results[0].distance == pytest.approx(1.5)
        assert matrix.results[0].duration == 3
        assert matrix.results[0].status is True
        assert matrix.results[1].status is False
        assert matrix.distance_type == DistanceType.DRIVING
        # 校验请求参数
        url, params = service._request_with_retry.call_args.args
        assert url == AMAP_DISTANCE_URL
        assert params["origins"] == "116.3,39.9"
        assert params["destination"] == "116.35,39.95;116.4,39.9"
        assert params["type"] == "1"

    async def test_empty_inputs(self, service):
        """空输入直接返回失败"""
        service._request_with_retry = AsyncMock()
        matrix = await service.get_distance_matrix([], [(116.4, 39.9)])
        assert matrix.status is False
        assert "为空" in matrix.info
        service._request_with_retry.assert_not_called()

    async def test_api_failure(self, service):
        """接口返回失败"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        matrix = await service.get_distance_matrix(
            [(116.3, 39.9)], [(116.4, 39.9)]
        )
        assert matrix.status is False
        assert "INVALID_KEY" in matrix.info

    async def test_exception_returns_failure(self, service):
        """异常时返回失败结果"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        matrix = await service.get_distance_matrix(
            [(116.3, 39.9)], [(116.4, 39.9)]
        )
        assert matrix.status is False
        assert "boom" in matrix.info

    async def test_get_distance_success(self, service):
        """单点距离查询"""
        service._request_with_retry = AsyncMock(return_value=_distance_api_response())
        result = await service.get_distance((116.3, 39.9), (116.35, 39.95))
        assert isinstance(result, DistanceResult)
        assert result.distance == pytest.approx(1.5)
        assert result.status is True

    async def test_get_distance_failure(self, service):
        """单点距离查询失败"""
        service.get_distance_matrix = AsyncMock(
            return_value=DistanceMatrix(
                status=False,
                info="failed",
                origin=Coordinate(longitude=0, latitude=0),
                destinations=[],
                results=[],
                distance_type=DistanceType.DRIVING,
            )
        )
        result = await service.get_distance((116.3, 39.9), (116.4, 39.9))
        assert result.status is False
        assert result.distance == 0


@pytest.mark.asyncio
class TestGetDistrict:
    """3.4.3 行政区查询"""

    async def test_success(self, service):
        """正常行政区查询"""
        service._request_with_retry = AsyncMock(return_value=_district_api_response())
        districts = await service.get_district("北京")
        assert len(districts) == 1
        district = districts[0]
        assert district.name == "北京市"
        assert district.adcode == "110000"
        assert district.center is not None
        assert district.center.longitude == pytest.approx(116.407526)
        assert len(district.boundaries) == 1

    async def test_api_failure(self, service):
        """接口返回失败时返回空列表"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        assert await service.get_district("北京") == []

    async def test_exception_returns_empty(self, service):
        """异常时返回空列表"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        assert await service.get_district("北京") == []

    async def test_get_district_boundary(self, service):
        """行政区边界查询"""
        service.get_district = AsyncMock(
            return_value=[DistrictInfo(
                name="北京市",
                adcode="110000",
                level="city",
                center=Coordinate(longitude=116.4, latitude=39.9),
                boundaries=[],
                citycode="010",
                province="北京市",
                info="OK",
                status=True,
            )]
        )
        result = await service.get_district_boundary("110000")
        assert result is not None
        assert result.adcode == "110000"
        service.get_district.assert_called_once_with("110000", subdistrict=0)

    async def test_get_district_boundary_none(self, service):
        """边界查询无结果返回 None"""
        service.get_district = AsyncMock(return_value=[])
        assert await service.get_district_boundary("110000") is None


class TestHelpers:
    """内部辅助方法"""

    def test_parse_single_coordinate(self, service):
        coord = service._parse_single_coordinate("116.4,39.9")
        assert coord is not None
        assert coord.longitude == 116.4
        assert service._parse_single_coordinate("") is None
        assert service._parse_single_coordinate("bad,data") is None
        assert service._parse_single_coordinate("116.4") is None

    def test_safe_int(self, service):
        assert MapService._safe_int("123") == 123
        assert MapService._safe_int([]) == 0
        assert MapService._safe_int(None) == 0
        assert MapService._safe_int("abc") == 0
        assert MapService._safe_int(42) == 42

    def test_safe_float(self, service):
        assert MapService._safe_float("4.8") == 4.8
        assert MapService._safe_float([]) is None
        assert MapService._safe_float(0) is None
        assert MapService._safe_float("abc") is None

    def test_extract_photo_urls(self, service):
        urls = MapService._extract_photo_urls(
            {"photos": [{"url": "https://a.com/1.jpg"}, {"preurl": "https://b.com/2.jpg"}]}
        )
        assert urls == ["https://a.com/1.jpg", "https://b.com/2.jpg"]

    def test_extract_photo_urls_limit(self, service):
        urls = MapService._extract_photo_urls(
            {"photos": [{"url": f"https://a.com/{i}.jpg"} for i in range(5)]},
            limit=2,
        )
        assert len(urls) == 2

    def test_parse_boundary(self, service):
        polygons = service._parse_boundary("116.3,39.8;116.5,39.9|116.6,40.0")
        assert len(polygons) == 2
        assert len(polygons[0]) == 2
        assert polygons[1][0].longitude == 116.6

    def test_parse_boundary_empty(self, service):
        assert service._parse_boundary("") == []

    def test_css_color_to_hex(self, service):
        assert service._css_color_to_hex("red") == "ff0000"
        assert service._css_color_to_hex("blue") == "1890ff"
        assert service._css_color_to_hex("#abcdef") == "ABCDEF"
        assert service._css_color_to_hex("unknown") == "1890ff"

    def test_calculate_bounds(self, service):
        bounds = service._calculate_bounds([(116.3, 39.8), (116.6, 40.0)])
        assert bounds == {
            "southwest_lng": 116.3,
            "southwest_lat": 39.8,
            "northeast_lng": 116.6,
            "northeast_lat": 40.0,
        }
        assert service._calculate_bounds([]) is None

    def test_calculate_zoom(self, service):
        assert service._calculate_zoom(None) == 10
        assert service._calculate_zoom(
            {"southwest_lng": 0, "southwest_lat": 0, "northeast_lng": 20, "northeast_lat": 20}
        ) == 4
        assert service._calculate_zoom(
            {"southwest_lng": 0, "southwest_lat": 0, "northeast_lng": 0.001, "northeast_lat": 0.001}
        ) == 15

    def test_haversine_distance(self, service):
        # 约 111km / 经度（赤道附近简化），116.0 -> 117.0 经度
        dist = service._haversine_distance((116.0, 39.9), (117.0, 39.9))
        assert 80 < dist < 120

    def test_build_navigation_url(self, service):
        url = service.build_navigation_url((116.4, 39.9), "天安门", mode="driving")
        assert url.startswith("https://uri.amap.com/navigation?to=116.4,39.9")
        assert "mode=driving" in url
        assert "callnative=1" in url

    @pytest.mark.asyncio
    async def test_optimize_route_order(self, service):
        """贪心路线顺序优化"""
        order = await service.optimize_route_order(
            [(116.0, 39.9), (116.01, 39.9), (116.02, 39.9)]
        )
        assert order == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_optimize_route_order_short(self, service):
        """少于 3 个点时保持原序"""
        assert await service.optimize_route_order([(116.0, 39.9)]) == [0]
        assert await service.optimize_route_order(
            [(116.0, 39.9), (116.1, 39.9)]
        ) == [0, 1]


@pytest.mark.asyncio
class TestSearchPoi:
    """3.4.4 POI 关键字搜索"""

    async def test_success(self, service):
        """正常搜索"""
        service._request_with_retry = AsyncMock(return_value=_poi_api_response())
        result = await service.search_poi("故宫", city="北京")
        assert result.status is True
        assert result.count == 1
        assert len(result.pois) == 1
        poi = result.pois[0]
        assert poi.id == "B001"
        assert poi.name == "故宫博物院"
        assert poi.location is not None
        assert poi.location.longitude == pytest.approx(116.397028)
        assert poi.rating == 4.8
        assert poi.cost == 60.0
        assert poi.photos == ["https://img.example.com/1.jpg"]
        assert poi.opening_hours == "08:30-17:00"

    async def test_params(self, service):
        """参数传递校验"""
        service._request_with_retry = AsyncMock(return_value=_poi_api_response())
        await service.search_poi(
            "故宫",
            city="北京",
            citylimit=True,
            types="风景名胜",
            page=2,
            page_size=50,
            sort=POISortType.DISTANCE,
        )
        url, params = service._request_with_retry.call_args.args
        assert url == AMAP_PLACE_TEXT_URL
        assert params["citylimit"] == "true"
        assert params["types"] == "风景名胜"
        assert params["page"] == 2
        assert params["offset"] == 50
        assert params["sortrule"] == "1"

    async def test_api_failure(self, service):
        """接口返回失败"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        result = await service.search_poi("故宫")
        assert result.status is False
        assert result.pois == []

    async def test_exception_returns_failure(self, service):
        """异常时返回失败结果"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        result = await service.search_poi("故宫")
        assert result.status is False
        assert "boom" in result.info


@pytest.mark.asyncio
class TestSearchNearby:
    """3.4.4 周边搜索"""

    async def test_success(self, service):
        """正常周边搜索"""
        service._request_with_retry = AsyncMock(return_value=_poi_api_response())
        result = await service.search_nearby(
            (116.4, 39.9),
            keywords=["故宫", "博物馆"],
            radius=3000,
        )
        assert result.status is True
        assert len(result.pois) == 1
        url, params = service._request_with_retry.call_args.args
        assert url == AMAP_PLACE_AROUND_URL
        assert params["location"] == "116.4,39.9"
        assert params["radius"] == 3000
        assert params["keywords"] == "故宫|博物馆"

    async def test_radius_capped(self, service):
        """半径上限 50000"""
        service._request_with_retry = AsyncMock(return_value=_poi_api_response())
        await service.search_nearby((116.4, 39.9), radius=99999)
        _, params = service._request_with_retry.call_args.args
        assert params["radius"] == 50000

    async def test_api_failure(self, service):
        """接口返回失败"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        result = await service.search_nearby((116.4, 39.9))
        assert result.status is False


@pytest.mark.asyncio
class TestGenerateStaticMap:
    """3.4.5 静态地图"""

    async def test_markers(self, service):
        """带标记点"""
        result = await service.generate_static_map(
            markers=[
                {"lng": 116.3, "lat": 39.9, "color": "red", "label": "A"},
                {"lng": 116.4, "lat": 39.92, "color": "blue", "label": "B"},
            ]
        )
        assert result.status is True
        assert result.url.startswith(AMAP_STATICMAP_URL)
        assert "markers=116.3%2C39.9%2C0xff0000%2CA" in result.url or "markers=116.3,39.9,0xff0000,A" in result.url
        assert result.size == "600*400"
        assert result.zoom == 10

    async def test_path_segmented(self, service):
        """超过 100 个点时分段"""
        path = [(116.0 + i * 0.001, 39.9) for i in range(250)]
        result = await service.generate_static_map(markers=[], path=path)
        assert result.status is True
        assert "paths=" in result.url
        assert "labels=" in result.url

    async def test_no_markers_no_path(self, service):
        """无标记点无路线"""
        result = await service.generate_static_map(markers=[])
        assert result.status is True
        assert "markers" not in result.url
        assert "paths" not in result.url


@pytest.mark.asyncio
class TestAggregateTripMap:
    """3.4.6 行程地图聚合"""

    async def test_empty_days(self, service):
        """空行程返回失败"""
        trip = _sample_trip(days=1)
        trip.days = []
        result = await service.aggregate_trip_map(trip)
        assert result.status is False
        assert "行程数据为空" in result.info
        assert result.days == []

    async def test_success(self, service):
        """正常聚合（mock 路线规划与静态地图）"""
        service.plan_route = AsyncMock(
            return_value=RouteSegment(
                from_place="起点",
                to_place="终点",
                from_coord=Coordinate(longitude=116.3, latitude=39.9),
                to_coord=Coordinate(longitude=116.4, latitude=39.9),
                distance=11.0,
                duration=20,
                strategy="0",
                steps=[],
                polyline=[
                    Coordinate(longitude=116.3, latitude=39.9),
                    Coordinate(longitude=116.4, latitude=39.9),
                ],
                toll=0,
                traffic_lights=0,
                info="OK",
                status=True,
            )
        )
        service.generate_static_map = AsyncMock(
            return_value=StaticMapResult(
                url="https://static.example.com/map.png",
                size="600*400",
                zoom=10,
                info="OK",
                status=True,
            )
        )
        service.get_district = AsyncMock(return_value=[
            DistrictInfo(
                name="北京市",
                adcode="110000",
                level="city",
                center=Coordinate(longitude=116.4, latitude=39.9),
                boundaries=[],
                citycode="010",
                province="北京市",
                info="OK",
                status=True,
            )
        ])

        trip = _sample_trip(days=2, items_per_day=2)
        result = await service.aggregate_trip_map(trip)
        assert result.status is True
        assert result.destination == "北京"
        assert result.destination_adcode == "110000"
        assert len(result.days) == 2
        # 每天 2 个景点 → 1 段路线
        assert len(result.days[0].route_segments) == 1
        assert result.days[0].total_distance == pytest.approx(11.0)
        assert result.static_map_url == "https://static.example.com/map.png"
        # 标记点颜色按天轮换
        assert result.days[0].markers[0].color == "#1890ff"
        assert result.days[1].markers[0].color == "#52c41a"
        service.plan_route.assert_called()
        service.generate_static_map.assert_called_once()

    async def test_no_route_no_static(self, service):
        """关闭路线与静态地图时跳过相关调用"""
        service.plan_route = AsyncMock()
        service.generate_static_map = AsyncMock()
        service.get_district = AsyncMock(return_value=[])

        trip = _sample_trip(days=1, items_per_day=2)
        result = await service.aggregate_trip_map(
            trip,
            include_route=False,
            include_static=False,
        )
        assert result.status is True
        assert result.static_map_url == ""
        assert result.days[0].route_segments == []
        service.plan_route.assert_not_called()
        service.generate_static_map.assert_not_called()


class TestMapDataToDict:
    """MapData 序列化"""

    def test_to_dict(self, service):
        data = MapData(
            trip_id="t1",
            destination="北京",
            destination_adcode="110000",
            center=Coordinate(longitude=116.4, latitude=39.9),
            zoom=10,
            bounds=MapBounds(
                southwest=Coordinate(longitude=116.3, latitude=39.8),
                northeast=Coordinate(longitude=116.5, latitude=40.0),
            ),
            days=[
                DayRoute(
                    day_number=1,
                    date=date(2026, 9, 1),
                    theme="文化之旅",
                    markers=[],
                    route_segments=[],
                    total_distance=0,
                    total_duration=0,
                    bounds=None,
                )
            ],
            static_map_url="",
            total_distance=0,
            total_duration=0,
            info="OK",
            status=True,
        )
        d = data.to_dict()
        assert d["trip_id"] == "t1"
        assert d["center"]["longitude"] == 116.4
        assert d["bounds"]["southwest"]["latitude"] == 39.8
        assert d["days"][0]["date"] == "2026-09-01"


class TestSingleton:
    """全局单例"""

    def test_init_and_get(self):
        svc = init_map_service("new-key", max_retries=1)
        assert svc is get_map_service()
        assert svc._api_key == "new-key"
        # 重置，避免影响其他测试
        import app.services.map_service as mod

        mod._map_service = None
