"""
山海拾光（智旅云图） - 行程编排服务测试（Phase 6.1.1-6.1.5）

全部 mock：agent / amap_geo / place_service / weather / storage / cache。
不打真实高德/智谱/SQLite。
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import (
    BudgetInfo,
    BudgetLevel,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    RestaurantInfo,
    HotelInfo,
    TravelStyle,
    TripRequest,
    TripResponse,
    WeatherInfo,
)
from app.services.amap_geo_service import GeocodeResult
from app.services.cache_service import CacheNamespace
from app.services.place_candidate_service import CandidatePool, CandidatePlace
from app.services.trip_service import (
    PRESET_CITIES,
    TripNotFoundError,
    TripService,
    TripServiceError,
    _normalize_destination,
    is_preset_city,
)

# app.services.__init__ 会把 trip_service 单例导出到包属性，
# 直接 import app.services.trip_service 会拿到单例；用 importlib 取真实模块以便 monkeypatch。
trip_service_mod = importlib.import_module("app.services.trip_service")


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def _batch_mode_default(monkeypatch):
    """既有 batch 编排测试默认 TRIP_GEN_MODE=batch；daily 专项测试自行覆盖。"""
    from app.config import settings

    monkeypatch.setattr(settings, "TRIP_GEN_MODE", "batch")
    yield


def _future_request(**kwargs: Any) -> TripRequest:
    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=kwargs.pop("days", 3) - 1)
    defaults = dict(
        destination="成都",
        start_date=start,
        end_date=end,
        travelers=2,
        budget_level=BudgetLevel.STANDARD,
        travel_style=TravelStyle.CULTURAL,
        max_places_per_day=4,
    )
    defaults.update(kwargs)
    return TripRequest(**defaults)


def _placeholder_trip(request: TripRequest, *, days: int = 2) -> TripResponse:
    """构造一个 Agent 返回的"坐标占位"草案 TripResponse。"""
    itinerary_days = []
    for i in range(days):
        items = [
            ItineraryItem(
                start_time="09:00",
                end_time="11:00",
                place=PlaceInfo(
                    place_id=f"p-day{i+1}-1",
                    name=f"第{i+1}天景点A",
                    address="待地图服务补全",
                    coordinate=Coordinate(latitude=0.0, longitude=0.0),
                    category="景点",
                    ticket_price=80.0,
                ),
                activity="游览",
                ticket_price=80.0,
            ),
            ItineraryItem(
                start_time="14:00",
                end_time="16:00",
                place=PlaceInfo(
                    place_id=f"p-day{i+1}-2",
                    name=f"第{i+1}天景点B",
                    address="待地图服务补全",
                    coordinate=Coordinate(latitude=0.0, longitude=0.0),
                    category="景点",
                    ticket_price=50.0,
                ),
                activity="游览",
                ticket_price=50.0,
            ),
        ]
        itinerary_days.append(
            ItineraryDay(
                day_number=i + 1,
                itinerary_date=request.start_date + timedelta(days=i),
                items=items,
                total_places=len(items),
                total_duration=240,
                daily_cost=0.0,
                cost_breakdown={
                    "accommodation": 200.0,
                    "food": 300.0,
                    "ticket": 0.0,
                    "transportation": 60.0,
                },
                lunch=RestaurantInfo(
                    place_id="meal-1",
                    name="测试餐厅",
                    coordinate=Coordinate(latitude=0.0, longitude=0.0),
                    address="待地图服务补全",
                    cuisine_type="川菜",
                    price_range="80元",
                    avg_price=80.0,
                ),
                hotel=HotelInfo(
                    place_id="hotel-1",
                    name="测试酒店",
                    coordinate=Coordinate(latitude=0.0, longitude=0.0),
                    address="待地图服务补全",
                    hotel_type="舒适型",
                    price=300.0,
                    price_range="300元/晚",
                ),
            )
        )
    return TripResponse(
        trip_id="test-trip-id",
        destination=request.destination,
        trip_name=f"{request.destination}测试行程",
        start_date=request.start_date,
        end_date=request.end_date,
        total_days=days,
        days=itinerary_days,
        budget=BudgetInfo(
            total_budget=1000.0,
            daily_avg_budget=500.0,
            budget_per_person=500.0,
            accommodation_budget=400.0,
            food_budget=300.0,
            transportation_budget=120.0,
            ticket_budget=0.0,
            other_budget=180.0,
        ),
        metadata={"needs_enrichment": True},
    )


def _geocode_result(
    name: str = "测试",
    lat: float = 30.67,
    lng: float = 104.06,
    adcode: str = "510104",
) -> GeocodeResult:
    return GeocodeResult(
        status=True,
        formatted_address=f"{name}地址",
        province="四川省",
        city="成都市",
        district="锦江区",
        street="测试路",
        street_number="1号",
        adcode=adcode,
        citycode="028",
        longitude=lng,
        latitude=lat,
        level="POI",
        info="OK",
        match_type="city_name",
    )


def _weather_info(d: date, weather: str = "晴") -> WeatherInfo:
    return WeatherInfo(
        forecast_date=d,
        temp_high=25,
        temp_low=15,
        temp_avg=20,
        weather_type=weather,
        humidity=50,
        wind_speed=3.0,
        wind_direction="东北风",
    )


def _build_service(
    *,
    agent: Any = None,
    amap_geo: Any = None,
    place_service: Any = None,
    weather: Any = None,
    storage: Any = None,
    cache: Any = None,
    llm: Any = None,
) -> TripService:
    """构造一个全依赖 mock 的 TripService。"""
    return TripService(
        agent=agent or MagicMock(),
        amap_geo=amap_geo,
        place_service=place_service or MagicMock(),
        weather=weather,
        storage=storage or MagicMock(),
        cache=cache or MagicMock(),
        llm=llm or MagicMock(),
    )


# ============================================================================
# 6.1.1 常量与城市分级
# ============================================================================

class TestCityClassification:
    """PRESET_CITIES / is_preset_city / _normalize_destination"""

    def test_preset_cities_contains_six_cities(self):
        assert PRESET_CITIES == frozenset(
            {"北京", "大理", "成都", "西安", "厦门", "三亚"}
        )

    @pytest.mark.parametrize("city", ["北京", "大理", "成都", "西安", "厦门", "三亚"])
    def test_is_preset_city_true_for_preset(self, city):
        assert is_preset_city(city) is True

    @pytest.mark.parametrize("city", ["杭州", "上海", "丽江", "青岛"])
    def test_is_preset_city_false_for_dynamic(self, city):
        assert is_preset_city(city) is False

    @pytest.mark.parametrize("alias,expected", [
        ("北京市", "北京"),
        ("大理州", "大理"),
        ("大理白族自治州", "大理"),
        ("成都市", "成都"),
        ("西安市", "西安"),
        ("厦门市", "厦门"),
        ("三亚市", "三亚"),
    ])
    def test_normalize_alias_to_standard(self, alias, expected):
        assert _normalize_destination(alias) == expected

    def test_normalize_passthrough_for_unknown(self):
        assert _normalize_destination("杭州") == "杭州"

    def test_normalize_handles_prefix(self):
        # "北京市朝阳区" → "北京"
        assert _normalize_destination("北京市朝阳区") == "北京"

    def test_normalize_empty(self):
        assert _normalize_destination("") == ""

    def test_normalize_strips_whitespace(self):
        assert _normalize_destination("  北京  ") == "北京"


# ============================================================================
# 6.1.2 + 6.1.3 主编排流程
# ============================================================================

class TestGenerateTripPresetCity:
    """沉淀城市路径：Agent 走 RAG 工具"""

    def test_preset_city_calls_agent_with_use_tools_true(self):
        """沉淀城市应让 Agent 走 RAG 工具调用模式。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        # mock 其他依赖：返回成功结果，让流程跑完
        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result())
        weather_svc = MagicMock()
        weather_svc.get_trip_weather = AsyncMock(
            return_value={"成都": [_weather_info(request.start_date + timedelta(days=i)) for i in range(2)]}
        )
        storage = MagicMock()
        storage.create_trip.return_value = "db-trip-1"
        cache = MagicMock()
        cache.get.return_value = None

        svc = _build_service(
            agent=agent, amap_geo=amap, weather=weather_svc,
            storage=storage, cache=cache,
        )

        result = svc.generate_trip(request, use_cache=True)

        agent.plan.assert_called_once()
        _, kwargs = agent.plan.call_args
        assert kwargs.get("use_tools") is True
        assert result.trip_id == "db-trip-1"
        assert result.metadata["preset_city"] is True
        assert result.metadata["needs_enrichment"] is False
        storage.create_trip.assert_called_once()

    def test_cache_hit_returns_cached_trip_without_agent_call(self):
        """缓存命中应直接返回，不调用 Agent。"""
        request = _future_request(destination="成都")
        cached_trip = _placeholder_trip(request)
        cache = MagicMock()
        cache.get.return_value = cached_trip.model_dump(mode="json")
        agent = MagicMock()

        svc = _build_service(agent=agent, cache=cache)
        result = svc.generate_trip(request, use_cache=True)

        agent.plan.assert_not_called()
        assert result.metadata.get("cache_hit") is True
        assert result.trip_id == cached_trip.trip_id

    def test_use_cache_false_skips_cache(self):
        """use_cache=False 时不读缓存。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder
        cache = MagicMock()
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(
            agent=agent, cache=cache, storage=storage,
            amap_geo=MagicMock(),
        )
        svc._amap_geo = None  # 跳过地图补全
        # 跳过天气补全
        svc._get_weather_service = lambda: None

        svc.generate_trip(request, use_cache=False)
        cache.get.assert_not_called()


class TestGenerateTripDynamicCity:
    """动态城市路径：先拉 POI 候选池"""

    def test_dynamic_city_builds_pool_then_calls_agent(self):
        """动态城市应先调 build_pool_sync，再用 candidate_places 调 Agent。"""
        request = _future_request(destination="杭州")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        pool = MagicMock(spec=CandidatePool)
        pool.to_prompt_items.return_value = [{"name": "西湖", "place_id": "x1"}]
        place_svc = MagicMock()
        place_svc.build_pool_sync.return_value = pool

        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"
        cache = MagicMock()
        cache.get.return_value = None

        svc = _build_service(
            agent=agent, place_service=place_svc,
            storage=storage, cache=cache,
        )
        svc._amap_geo = None
        svc._get_weather_service = lambda: None

        svc.generate_trip(request, use_cache=True)

        place_svc.build_pool_sync.assert_called_once_with(request)
        agent.plan.assert_called_once()
        _, kwargs = agent.plan.call_args
        assert kwargs.get("use_tools") is False
        assert kwargs.get("candidate_places") == [{"name": "西湖", "place_id": "x1"}]

    def test_dynamic_city_empty_pool_falls_back_to_rag(self):
        """POI 候选池为空时应降级回 RAG 路径（use_tools=True）。"""
        request = _future_request(destination="丽江")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        pool = MagicMock(spec=CandidatePool)
        pool.to_prompt_items.return_value = []
        place_svc = MagicMock()
        place_svc.build_pool_sync.return_value = pool

        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"
        cache = MagicMock()
        cache.get.return_value = None

        svc = _build_service(
            agent=agent, place_service=place_svc,
            storage=storage, cache=cache,
        )
        svc._amap_geo = None
        svc._get_weather_service = lambda: None

        svc.generate_trip(request)

        _, kwargs = agent.plan.call_args
        assert kwargs.get("use_tools") is True

    def test_dynamic_city_pool_failure_falls_back_to_rag(self):
        """POI 候选池异常时应降级回 RAG 路径。"""
        request = _future_request(destination="青岛")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        place_svc = MagicMock()
        place_svc.build_pool_sync.side_effect = RuntimeError("network down")

        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"
        cache = MagicMock()
        cache.get.return_value = None

        svc = _build_service(
            agent=agent, place_service=place_svc,
            storage=storage, cache=cache,
        )
        svc._amap_geo = None
        svc._get_weather_service = lambda: None

        svc.generate_trip(request)

        _, kwargs = agent.plan.call_args
        assert kwargs.get("use_tools") is True


class TestEnrichMap:
    """地图补全（geocode only）"""

    def test_geocode_fills_coordinate_and_address(self):
        """占位坐标应被 geocode 结果覆盖。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result(lat=30.67, lng=104.06))
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        first_place = result.days[0].items[0].place
        assert first_place.coordinate.latitude == 30.67
        assert first_place.coordinate.longitude == 104.06
        assert first_place.address != "待地图服务补全"
        assert first_place.district == "锦江区"

    def test_geocode_failure_records_warning_and_keeps_placeholder(self):
        """geocode 失败应记入 warnings 并保留占位。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(side_effect=RuntimeError("amap 500"))
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        first_place = result.days[0].items[0].place
        assert first_place.coordinate.latitude == 0.0  # 仍是占位
        assert "geocode 调用失败" in result.metadata["enrich_warnings"][0]

    def test_geocode_no_result_records_warning(self):
        """geocode 返回无效结果应记入 warnings。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(
            return_value=GeocodeResult(status=False, info="未找到")
        )
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        assert any("geocode 无结果" in w for w in result.metadata["enrich_warnings"])

    def test_geocode_foreign_coord_rejected(self):
        """geocode 返回国外坐标应被坐标校验拦截，保留占位并记 warning。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(
            return_value=_geocode_result(lat=40.758, lng=-73.985, adcode="360111")
        )
        amap.get_city_adcode = AsyncMock(return_value="510100")
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        first_place = result.days[0].items[0].place
        assert first_place.coordinate.latitude == 0.0  # 仍是占位
        assert any("坐标校验未通过" in w for w in result.metadata["enrich_warnings"])

    def test_geocode_wrong_city_adcode_rejected(self):
        """geocode 命中异地城市（adcode 不匹配）应被校验拦截。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(
            return_value=_geocode_result(lat=30.25, lng=120.15, adcode="330106")
        )
        amap.get_city_adcode = AsyncMock(return_value="510100")
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        first_place = result.days[0].items[0].place
        assert first_place.coordinate.latitude == 0.0
        assert any("坐标校验未通过" in w for w in result.metadata["enrich_warnings"])

    def test_geocode_ok_with_city_adcode_match(self):
        """adcode 归属匹配时校验通过，坐标正常回填。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result(adcode="510104"))
        amap.get_city_adcode = AsyncMock(return_value="510100")
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        first_place = result.days[0].items[0].place
        assert first_place.coordinate.latitude == 30.67
        assert first_place.coordinate.longitude == 104.06
        assert not any("坐标校验" in w for w in result.metadata.get("enrich_warnings", []))

    def test_amap_geo_unavailable_records_warning(self):
        """amap_geo 服务不可用应记 warning 且不抛异常。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, storage=storage, cache=cache)
        svc._amap_geo = None
        svc._get_amap_geo = lambda: None
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        assert "amap_geo 服务不可用" in result.metadata["enrich_warnings"][0]

    def test_place_photos_are_filled_from_amap(self):
        """地点无图时应从高德 POI 详情补 cover_image/images。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result())
        amap.get_place_photos = AsyncMock(return_value=[
            "https://example.com/place-1.jpg",
            "https://example.com/place-2.jpg",
        ])
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        first_place = result.days[0].items[0].place
        assert first_place.cover_image == "https://example.com/place-1.jpg"
        assert first_place.images == [
            "https://example.com/place-1.jpg",
            "https://example.com/place-2.jpg",
        ]

    def test_hotel_photos_are_filled_from_amap(self):
        """每日住宿酒店无图时应从高德 POI 详情补图片。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result())
        amap.get_place_photos = AsyncMock(return_value=["https://example.com/hotel.jpg"])
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        hotel = result.days[0].hotel
        assert hotel is not None
        assert hotel.cover_image == "https://example.com/hotel.jpg"
        assert hotel.images == ["https://example.com/hotel.jpg"]


class TestEnrichWeather:
    """天气补全"""

    def test_weather_filled_by_date(self):
        """天气应按 itinerary_date 匹配到 day.weather。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request, days=2)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        forecasts = [
            _weather_info(request.start_date, "晴"),
            _weather_info(request.start_date + timedelta(days=1), "多云"),
        ]
        weather_svc = MagicMock()
        weather_svc.get_trip_weather = AsyncMock(return_value={"成都": forecasts})
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(
            agent=agent, weather=weather_svc, storage=storage, cache=cache,
        )
        svc._amap_geo = None

        result = svc.generate_trip(request)
        assert result.days[0].weather.weather_type == "晴"
        assert result.days[1].weather.weather_type == "多云"

    def test_weather_service_unavailable_records_warning(self):
        """weather_service 不可用应记 warning。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, storage=storage, cache=cache)
        # 显式 mock _get_amap_geo 返回 None（避免触发真实初始化）
        svc._get_amap_geo = lambda: None
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        assert any("weather_service 不可用" in w for w in result.metadata["enrich_warnings"])

    def test_weather_no_forecast_records_warning(self):
        """weather_service 返回空预报应记 warning。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        weather_svc = MagicMock()
        weather_svc.get_trip_weather = AsyncMock(return_value={"成都": []})
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, weather=weather_svc, storage=storage, cache=cache)
        svc._amap_geo = None

        result = svc.generate_trip(request)
        assert any("未获取到" in w for w in result.metadata["enrich_warnings"])

    def test_weather_suggestions_generated_by_llm(self):
        """天气补全后应调用大模型生成两条出行建议。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request, days=2)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        weather_svc = MagicMock()
        weather_svc.get_trip_weather = AsyncMock(
            return_value={
                "成都": [
                    _weather_info(request.start_date, "晴"),
                    _weather_info(request.start_date + timedelta(days=1), "多云"),
                ]
            }
        )
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        llm = MagicMock()
        llm.invoke.return_value.content = '{"suggestions": ["携带雨具", "注意防晒"]}'

        svc = _build_service(
            agent=agent, weather=weather_svc, storage=storage, cache=cache, llm=llm,
        )
        svc._amap_geo = None

        result = svc.generate_trip(request)
        assert result.weather_suggestions == ["携带雨具", "注意防晒"]

    def test_weather_suggestions_llm_failure_records_warning(self):
        """大模型建议生成失败不应阻断主流程，仅记 warning。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request, days=2)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        weather_svc = MagicMock()
        weather_svc.get_trip_weather = AsyncMock(
            return_value={
                "成都": [
                    _weather_info(request.start_date, "晴"),
                    _weather_info(request.start_date + timedelta(days=1), "多云"),
                ]
            }
        )
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("llm down")

        svc = _build_service(
            agent=agent, weather=weather_svc, storage=storage, cache=cache, llm=llm,
        )
        svc._amap_geo = None

        result = svc.generate_trip(request)
        assert result.weather_suggestions == []
        assert any("天气出行建议生成失败" in w for w in result.metadata["enrich_warnings"])


class TestBudgetRecalculation:
    """预算二次校正"""

    def test_budget_recalculated_with_real_ticket_prices(self):
        """补全后的真实门票应触发预算重算。"""
        request = _future_request(destination="成都", days=2)
        placeholder = _placeholder_trip(request, days=2)
        # 草案中 ticket_price=80/50, cost_breakdown.ticket=0 → 应触发校正
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result())
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        # 每天 (80+50)*2 人 = 260，2 天共 520
        assert result.budget.ticket_budget == 520.0
        assert result.days[0].cost_breakdown["ticket"] == 260.0

    def test_budget_recalculated_even_when_map_fails(self):
        """
        地图补全失败时，草案自带的 ticket_price 仍会触发预算重算。
        草案 ticket_price=80/50/天 * 2人 = 260/天，2 天共 520。
        """
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request, days=2)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        amap = MagicMock()
        amap.geocode = AsyncMock(side_effect=RuntimeError("fail"))
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage, cache=cache)
        svc._get_weather_service = lambda: None

        result = svc.generate_trip(request)
        # 每天 (80+50)*2人=260，2 天=520
        assert result.budget.ticket_budget == 520.0
        assert result.days[0].cost_breakdown["ticket"] == 260.0


# ============================================================================
# 6.1.4 Token 统计
# ============================================================================

class TestTokenUsage:
    """token 使用量统计"""

    def test_token_usage_written_to_metadata(self):
        """成功拿到 callback 时 token_usage 应写入 metadata。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder

        # 构造一个 fake callback 上下文管理器
        fake_cb = MagicMock()
        fake_cb.total_tokens = 1500
        fake_cb.prompt_tokens = 1000
        fake_cb.completion_tokens = 500
        fake_cb.total_cost = 0.0125
        fake_cb.successful_requests = 2

        import contextlib

        @contextlib.contextmanager
        def fake_cm():
            yield fake_cb

        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, storage=storage, cache=cache)
        svc._amap_geo = None
        svc._get_weather_service = lambda: None
        svc._make_token_callback = lambda: fake_cm()

        result = svc.generate_trip(request)
        assert result.metadata["token_usage"]["total_tokens"] == 1500
        assert result.metadata["token_usage"]["prompt_tokens"] == 1000
        assert result.metadata["token_usage"]["completion_tokens"] == 500
        assert result.metadata["token_usage"]["successful_requests"] == 2

    def test_token_callback_unavailable_skips_token_usage(self):
        """callback 不可用时应跳过 token 统计（不抛异常）。"""
        request = _future_request(destination="成都")
        placeholder = _placeholder_trip(request)
        agent = MagicMock()
        agent.plan.return_value = placeholder
        cache = MagicMock()
        cache.get.return_value = None
        storage = MagicMock()
        storage.create_trip.return_value = "trip-1"

        svc = _build_service(agent=agent, storage=storage, cache=cache)
        svc._amap_geo = None
        svc._get_weather_service = lambda: None
        svc._make_token_callback = lambda: None

        result = svc.generate_trip(request)
        assert "token_usage" not in result.metadata

    def test_extract_token_usage_handles_none(self):
        assert TripService._extract_token_usage(None) == {}

    def test_extract_token_usage_handles_missing_attrs(self):
        cb = MagicMock(spec=[])  # 空 spec，无任何属性
        usage = TripService._extract_token_usage(cb)
        assert usage["total_tokens"] == 0
        assert usage["total_cost"] == 0.0


# ============================================================================
# 行程 CRUD（薄包装）
# ============================================================================

class TestCRUDWrappers:
    """get_trip / list_trips / delete_trip 薄包装"""

    def test_get_trip_delegates_to_storage(self):
        storage = MagicMock()
        storage.get_trip_as_history.return_value = "history-obj"
        svc = _build_service(storage=storage)
        assert svc.get_trip("trip-1") == "history-obj"
        storage.get_trip_as_history.assert_called_once_with("trip-1", user_id=None)

    def test_list_trips_delegates_to_storage(self):
        storage = MagicMock()
        storage.list_trips.return_value = ([{"id": "1"}], 1)
        svc = _build_service(storage=storage)
        items, total = svc.list_trips(user_id="u1", limit=5)
        assert items == [{"id": "1"}]
        assert total == 1
        storage.list_trips.assert_called_once()

    def test_delete_trip_delegates_to_storage(self):
        storage = MagicMock()
        storage.delete_trip.return_value = True
        svc = _build_service(storage=storage)
        assert svc.delete_trip("trip-1") is True
        storage.delete_trip.assert_called_once_with("trip-1", user_id=None)


# ============================================================================
# 辅助方法
# ============================================================================

class TestHelpers:
    """缓存 key / 异常保护"""

    def test_trip_cache_key_stable(self):
        """相同请求应生成相同缓存 key。"""
        request = _future_request(destination="成都")
        svc = _build_service()
        k1 = svc._trip_cache_key(request, user_id="u1")
        k2 = svc._trip_cache_key(request, user_id="u1")
        assert k1 == k2
        assert k1.startswith("trip:")

    def test_trip_cache_key_differs_by_user(self):
        request = _future_request(destination="成都")
        svc = _build_service()
        k1 = svc._trip_cache_key(request, user_id="u1")
        k2 = svc._trip_cache_key(request, user_id="u2")
        assert k1 != k2

    def test_trip_cache_key_differs_by_destination(self):
        svc = _build_service()
        k1 = svc._trip_cache_key(_future_request(destination="成都"), user_id=None)
        k2 = svc._trip_cache_key(_future_request(destination="北京"), user_id=None)
        assert k1 != k2

    def test_safe_cache_get_swallows_exceptions(self):
        cache = MagicMock()
        cache.get.side_effect = RuntimeError("redis down")
        svc = _build_service(cache=cache)
        assert svc._safe_cache_get("any") is None

    def test_safe_cache_set_swallows_exceptions(self):
        cache = MagicMock()
        cache.set.side_effect = RuntimeError("redis down")
        svc = _build_service(cache=cache)
        request = _future_request(destination="成都")
        trip = _placeholder_trip(request)
        # 不应抛异常
        svc._safe_cache_set("any", trip)

    def test_compose_address_from_geocode(self):
        result = _geocode_result()
        addr = TripService._compose_address(result)
        assert "四川省" in addr
        assert "成都市" in addr
        assert "锦江区" in addr

    def test_compose_address_returns_none_for_empty(self):
        result = GeocodeResult(status=True)
        assert TripService._compose_address(result) is None


# ============================================================================
# 13.3 逐天编排循环（方案B · 真·逐天生成）
# ============================================================================

class _FakePool:
    """B 级候选池替身：实现 to_prompt_sections，供 _prepare_day_state 消费。"""

    def __init__(self, sections=None, scenic_places=None):
        self._sections = sections or {
            "scenic": [], "food": [], "hotel": [], "clusters": {}, "index": {},
        }
        self.scenic_places = scenic_places or []
        self.food_places = []
        self.hotel_places = []
        self.warnings = []

    def to_prompt_sections(self):
        return self._sections


def _empty_pool() -> SimpleNamespace:
    """A 级仅供图路径的空候选池（build_pool_sync 替身）。"""
    return SimpleNamespace(
        scenic_places=[], food_places=[], hotel_places=[], warnings=[]
    )


def _simple_day(request: TripRequest, day_no: int) -> ItineraryDay:
    """run_day_chain 替身返回的单日 ItineraryDay。"""
    return ItineraryDay(
        day_number=day_no,
        itinerary_date=request.start_date + timedelta(days=day_no - 1),
        day_theme=f"主题{day_no}",
        items=[
            ItineraryItem(
                start_time="09:00",
                end_time="11:00",
                place=PlaceInfo(
                    place_id=f"pid{day_no}",
                    name=f"景点{day_no}",
                    address="待地图服务补全",
                    coordinate=Coordinate(latitude=0.0, longitude=0.0),
                    category="景点",
                ),
                activity="游览",
            )
        ],
        total_places=1,
        total_rating=4.5,
    )


def _fake_day_chain(state: dict, *, on_event=None) -> dict:
    """run_day_chain 替身：返回单日产物与跨天记忆 patch。"""
    day_no = state["day_number"]
    request = state["request"]
    return {
        "draft_day": SimpleNamespace(
            day_theme=f"主题{day_no}",
            day_summary=f"第{day_no}天概述",
            items=[SimpleNamespace(name=f"景点{day_no}")],
        ),
        "day": _simple_day(request, day_no),
        "day_warnings": [],
        "fallback_used": False,
        "meta": {"daily_llm_calls": [{"day": day_no, "attempt": 1, "ok": True}]},
        "error": None,
        "memory": {
            "used_place_ids_added": [f"pid{day_no}"],
            "used_names_added": [f"景点{day_no}"],
            "prev_district": "东城区",
            "prev_hotel": "王府井大酒店",
            "day_summary": {
                "day_number": day_no,
                "date": state["day_date"].isoformat(),
                "theme": f"主题{day_no}",
                "places": [f"景点{day_no}"],
                "district": "东城区",
                "hotel": "王府井大酒店",
                "lunch": "全聚德",
                "dinner": "东来顺",
                "cost": 100.0,
            },
        },
    }


def _daily_aggregate(self, request, summaries):
    """_aggregate_trip_summary 替身（避免测试打 LLM）。"""
    return {
        "trip_name": f"{request.destination}3日游",
        "trip_highlights": ["文化之旅"],
        "trip_tips": ["提前预约"],
        "recommended_foods": ["火锅"],
        "recommended_shopping": [],
    }


class TestGenerateDaily:
    """13.3 逐天编排循环：多次 run_day_chain + day 事件 + 跨天记忆 + 全量收尾。"""

    @pytest.fixture(autouse=True)
    def _daily_env(self, monkeypatch):
        """daily 专项环境：TRIP_GEN_MODE=daily + 屏蔽外部网络依赖。"""
        from app.config import settings

        monkeypatch.setattr(settings, "TRIP_GEN_MODE", "daily")
        monkeypatch.setattr(TripService, "_get_amap_geo", lambda self: None)
        monkeypatch.setattr(TripService, "_fetch_forecast_by_date", lambda self, req: None)
        monkeypatch.setattr(
            trip_service_mod,
            "default_rag_tool",
            SimpleNamespace(
                search_for_trip=lambda request: SimpleNamespace(context_text="攻略上下文")
            ),
        )
        monkeypatch.setattr(TripService, "_aggregate_trip_summary", _daily_aggregate)
        yield

    def test_generate_daily_loop_calls_chain_per_day_and_emits_day_events(
        self, monkeypatch
    ):
        """3 天：run_day_chain 调用 3 次；day(draft) → day(enriched) 按天有序；finalize 收尾。"""
        calls: list[int] = []

        def fake_chain(state, *, on_event=None):
            calls.append(state["day_number"])
            return _fake_day_chain(state, on_event=on_event)

        monkeypatch.setattr(trip_service_mod, "run_day_chain", fake_chain)
        storage = MagicMock()
        storage.create_trip.return_value = "TRP-DAILY-001"
        cache = MagicMock()
        cache.get.return_value = None
        svc = _build_service(
            place_service=SimpleNamespace(build_pool_sync=lambda request: _empty_pool()),
            storage=storage,
            cache=cache,
        )
        events: list[dict] = []
        trip = svc.generate_trip(
            _future_request(destination="成都", days=3),
            on_event=events.append,
        )

        assert calls == [1, 2, 3]
        assert trip.total_days == 3
        assert len(trip.days) == 3
        assert trip.metadata["generation_mode"] == "daily"
        assert len(trip.metadata["daily_llm_calls"]) == 3
        assert trip.trip_name == "成都3日游"
        storage.create_trip.assert_called_once()
        cache.set.assert_called_once()

        day_events = [e for e in events if e["type"] == "day"]
        seq = [(e["state"], e["day_number"]) for e in day_events]
        assert seq == [
            ("draft", 1), ("enriched", 1),
            ("draft", 2), ("enriched", 2),
            ("draft", 3), ("enriched", 3),
        ]
        statuses = [e for e in events if e["type"] == "status"]
        assert any(s["stage"] == "finalize" for s in statuses)
        # 逐天模式不推整份 draft 骨架事件
        assert all(e["type"] != "draft" for e in events)

    def test_generate_daily_sync_no_events(self, monkeypatch):
        """非流式：on_event=None 走同一逐天路径，不推事件。"""
        monkeypatch.setattr(trip_service_mod, "run_day_chain", _fake_day_chain)
        svc = _build_service(
            place_service=SimpleNamespace(build_pool_sync=lambda request: _empty_pool()),
            storage=MagicMock(),
            cache=MagicMock(),
        )
        trip = svc.generate_trip(_future_request(destination="成都", days=2))
        assert trip.total_days == 2
        assert len(trip.days) == 2

    def test_generate_daily_cache_hit_skips_loop(self, monkeypatch):
        """缓存命中：直出 + status(cache_hit)，不进入逐天循环。"""

        def _should_not_run(state, *, on_event=None):
            raise AssertionError("缓存命中不应进入逐天循环")

        monkeypatch.setattr(trip_service_mod, "run_day_chain", _should_not_run)
        request = _future_request(destination="成都", days=2)
        cached = _placeholder_trip(request, days=2)
        cache = MagicMock()
        cache.get.return_value = cached.model_dump(mode="json")
        storage = MagicMock()
        svc = _build_service(
            place_service=SimpleNamespace(build_pool_sync=lambda request: _empty_pool()),
            storage=storage,
            cache=cache,
        )
        events: list[dict] = []
        trip = svc.generate_trip(request, on_event=events.append)
        assert trip.trip_id == cached.trip_id
        assert trip.metadata["cache_hit"] is True
        storage.create_trip.assert_not_called()
        statuses = [e for e in events if e["type"] == "status"]
        assert any(s["stage"] == "cache_hit" for s in statuses)

    def test_generate_daily_single_day_fatal_raises(self, monkeypatch):
        """单日兜底仍失败（罕见）：中止整份并抛 TripServiceError，不持久化。"""

        def fatal(state, *, on_event=None):
            if state["day_number"] == 2:
                return {"error": "第2天兜底也失败", "meta": {}}
            return _fake_day_chain(state, on_event=on_event)

        monkeypatch.setattr(trip_service_mod, "run_day_chain", fatal)
        storage = MagicMock()
        svc = _build_service(
            place_service=SimpleNamespace(build_pool_sync=lambda request: _empty_pool()),
            storage=storage,
            cache=MagicMock(),
        )
        with pytest.raises(TripServiceError, match="第2天生成失败"):
            svc.generate_trip(_future_request(destination="成都", days=3))
        storage.create_trip.assert_not_called()

    def test_generate_daily_weather_attached(self, monkeypatch):
        """天气一次性取整段预报后逐天挂载。"""
        monkeypatch.setattr(trip_service_mod, "run_day_chain", _fake_day_chain)
        request = _future_request(destination="成都", days=2)
        by_date = {
            request.start_date: _weather_info(request.start_date),
            request.start_date + timedelta(days=1): _weather_info(
                request.start_date + timedelta(days=1), weather="多云"
            ),
        }
        monkeypatch.setattr(
            TripService, "_fetch_forecast_by_date", lambda self, req: by_date
        )
        svc = _build_service(
            place_service=SimpleNamespace(build_pool_sync=lambda request: _empty_pool()),
            storage=MagicMock(),
            cache=MagicMock(),
        )
        trip = svc.generate_trip(request)
        assert trip.days[0].weather is not None
        assert trip.days[0].weather.weather_type == "晴"
        assert trip.days[1].weather.weather_type == "多云"

    def test_generate_daily_dynamic_city_uses_pool(self, monkeypatch):
        """B 级动态城市：POI 三池驱动，候选池就绪后推 poi 事件。"""
        monkeypatch.setattr(trip_service_mod, "run_day_chain", _fake_day_chain)
        sections = {
            "scenic": [
                {"place_id": "p1", "name": "西湖", "rating": 4.8, "cost": 0, "district": "西湖区"},
                {"place_id": "p2", "name": "灵隐寺", "rating": 4.7, "cost": 30, "district": "西湖区"},
            ],
            "food": [{"place_id": "f1", "name": "楼外楼", "cost": 120, "district": "西湖区"}],
            "hotel": [{"place_id": "h1", "name": "西湖大酒店", "cost": 500, "district": "西湖区"}],
            "clusters": {"西湖区": ["p1", "p2"]},
            "index": {
                "p1": {"place_id": "p1", "name": "西湖", "cost": 0, "district": "西湖区"},
                "p2": {"place_id": "p2", "name": "灵隐寺", "cost": 30, "district": "西湖区"},
                "f1": {"place_id": "f1", "name": "楼外楼", "cost": 120, "district": "西湖区"},
                "h1": {"place_id": "h1", "name": "西湖大酒店", "cost": 500, "district": "西湖区"},
            },
        }
        pool = _FakePool(
            sections,
            scenic_places=[
                SimpleNamespace(
                    name="西湖", category="景点", address="", district="西湖区",
                    rating=4.8, photos=[], score=9.2,
                )
            ],
        )
        svc = _build_service(
            place_service=SimpleNamespace(build_pool_sync=lambda request: pool),
            storage=MagicMock(),
            cache=MagicMock(),
        )
        events: list[dict] = []
        trip = svc.generate_trip(
            _future_request(destination="杭州", days=2),
            on_event=events.append,
        )
        assert trip.total_days == 2
        poi_events = [e for e in events if e["type"] == "poi"]
        assert poi_events

    def test_generate_trip_mode_switch_batch(self, monkeypatch):
        """TRIP_GEN_MODE=batch：回退整份生成路径（agent.plan 一次）。"""
        from app.config import settings

        monkeypatch.setattr(settings, "TRIP_GEN_MODE", "batch")
        agent = MagicMock()
        agent.plan.return_value = _placeholder_trip(
            _future_request(destination="成都", days=2), days=2
        )
        svc = _build_service(
            agent=agent,
            place_service=SimpleNamespace(build_pool_sync=lambda request: _empty_pool()),
            storage=MagicMock(),
            cache=MagicMock(),
        )
        trip = svc.generate_trip(_future_request(destination="成都", days=2))
        assert trip.total_days == 2
        agent.plan.assert_called_once()

    def test_aggregate_local_fills_from_summaries(self):
        """本地聚合兜底：由每日主题/餐饮名拼装整份元信息。"""
        summaries = [
            {"day_number": 1, "theme": "文化之旅", "places": ["故宫", "景山"], "lunch": "全聚德", "dinner": "东来顺", "cost": 100},
            {"day_number": 2, "theme": "自然之旅", "places": ["颐和园"], "lunch": "烤鸭店", "dinner": None, "cost": 120},
        ]
        agg = TripService._aggregate_local(
            _future_request(destination="北京"), summaries
        )
        assert "文化之旅" in agg["trip_highlights"][0]
        assert "全聚德" in agg["recommended_foods"]
        assert agg["trip_name"] == "北京2日游"

    def test_normalize_aggregated_cleans_and_falls_back(self):
        """LLM 聚合结果规范化：裁剪类型/长度，缺失字段回退本地。"""
        data = {
            "trip_name": "  LLM标题  ",
            "trip_highlights": ["亮点A", 123, ""],
            "trip_tips": "not-a-list",
            "recommended_foods": ["美食"],
            "recommended_shopping": None,
        }
        agg = TripService._normalize_aggregated(data, _future_request(), [])
        assert agg["trip_name"] == "LLM标题"
        assert agg["trip_highlights"] == ["亮点A"]
        assert agg["trip_tips"]  # 非列表回退本地默认
        assert agg["recommended_foods"] == ["美食"]
        assert agg["recommended_shopping"] == []
