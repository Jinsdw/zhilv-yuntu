"""
智旅云图 - 行程编排服务测试（Phase 6.1.1-6.1.5）

全部 mock：agent / amap_geo / place_service / weather / storage / cache。
不打真实高德/智谱/SQLite。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
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


# ============================================================================
# Fixtures
# ============================================================================

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


def _geocode_result(name: str = "测试", lat: float = 30.67, lng: float = 104.06) -> GeocodeResult:
    return GeocodeResult(
        status=True,
        formatted_address=f"{name}地址",
        province="四川省",
        city="成都市",
        district="锦江区",
        street="测试路",
        street_number="1号",
        adcode="510104",
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
) -> TripService:
    """构造一个全依赖 mock 的 TripService。"""
    return TripService(
        agent=agent or MagicMock(),
        amap_geo=amap_geo,
        place_service=place_service or MagicMock(),
        weather=weather,
        storage=storage or MagicMock(),
        cache=cache or MagicMock(),
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
# 6.1.5 行程编辑 + 规则降级
# ============================================================================

class TestEditTripDay:
    """edit_trip_day + 降级策略"""

    def test_trip_not_found_raises(self):
        """行程不存在应抛 TripNotFoundError。"""
        storage = MagicMock()
        storage.get_trip_as_history.return_value = None
        svc = _build_service(storage=storage)
        with pytest.raises(TripNotFoundError):
            svc.edit_trip_day("missing-id", day_number=1, instruction="换成博物馆")

    def test_agent_edit_success_persists(self):
        """Agent 编辑成功应调用 update_trip 持久化。"""
        request = _future_request(destination="成都")
        base = _placeholder_trip(request)
        history = MagicMock()
        history.response = base
        storage = MagicMock()
        storage.get_trip_as_history.return_value = history

        edited = base.model_copy(update={"trip_name": "已编辑"})
        agent = MagicMock()
        agent.edit_day.return_value = edited

        svc = _build_service(agent=agent, storage=storage)
        svc._amap_geo = None  # 跳过单日地图补全

        result = svc.edit_trip_day("trip-1", day_number=1, instruction="改成文化游")
        assert result.trip_name == "已编辑"
        assert "edited_at" in result.metadata
        storage.update_trip.assert_called_once()

    def test_agent_failure_returns_original_with_edit_failed(self):
        """Agent.edit_day 异常时应返回原 trip + edit_failed=True。"""
        request = _future_request(destination="成都")
        base = _placeholder_trip(request)
        history = MagicMock()
        history.response = base
        storage = MagicMock()
        storage.get_trip_as_history.return_value = history

        agent = MagicMock()
        agent.edit_day.side_effect = RuntimeError("LLM down")

        svc = _build_service(agent=agent, storage=storage)
        result = svc.edit_trip_day("trip-1", day_number=1, instruction="改成文化游")

        assert result.metadata.get("edit_failed") is True
        assert "LLM down" in result.metadata.get("edit_error", "")
        storage.update_trip.assert_not_called()

    def test_persistence_failure_does_not_block(self):
        """update_trip 失败应记入 warnings 但不抛异常。"""
        request = _future_request(destination="成都")
        base = _placeholder_trip(request)
        history = MagicMock()
        history.response = base
        storage = MagicMock()
        storage.get_trip_as_history.return_value = history
        storage.update_trip.side_effect = RuntimeError("db locked")

        edited = base.model_copy(update={"trip_name": "已编辑"})
        agent = MagicMock()
        agent.edit_day.return_value = edited

        svc = _build_service(agent=agent, storage=storage)
        svc._amap_geo = None

        result = svc.edit_trip_day("trip-1", day_number=1, instruction="改成文化游")
        assert any("持久化失败" in w for w in result.metadata.get("edit_warnings", []))

    def test_invalid_day_number_keeps_trip_unchanged(self):
        """day_number 越界时 _enrich_single_day_map 应原样返回。"""
        request = _future_request(destination="成都")
        base = _placeholder_trip(request, days=2)
        history = MagicMock()
        history.response = base
        storage = MagicMock()
        storage.get_trip_as_history.return_value = history

        edited = base  # 不修改
        agent = MagicMock()
        agent.edit_day.return_value = edited

        amap = MagicMock()
        amap.geocode = AsyncMock(return_value=_geocode_result())

        svc = _build_service(agent=agent, amap_geo=amap, storage=storage)
        # day_number=99 越界
        result = svc.edit_trip_day("trip-1", day_number=99, instruction="改成文化游")
        # geocode 不应被调用（day_number 越界直接返回）
        amap.geocode.assert_not_called()


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
        storage.get_trip_as_history.assert_called_once_with("trip-1")

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
        storage.delete_trip.assert_called_once_with("trip-1")


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
