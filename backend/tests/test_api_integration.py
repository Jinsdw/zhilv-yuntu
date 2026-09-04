"""
智旅云图 - API 集成测试（Phase 9.1.3）

与 test_api_routes.py（mock 服务层）不同，本文件跑真实链路：
    - 真实 FastAPI 应用 + lifespan（真实初始化临时 SQLite 表）
    - 真实 TripService 编排（generate / edit 全流程）
    - 真实存储（临时 SQLite 文件）
仅 mock 外部网络依赖：Agent(LLM) / 高德地图 / 天气 / LLM 建议 / 缓存。

覆盖：健康检查、行程生成→落库→历史→导出→编辑→删除、错误路径（422/400/404/503）、CORS。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    RestaurantInfo,
    HotelInfo,
    TripRequest,
    TripResponse,
    WeatherInfo,
)
from app.services.amap_geo_service import GeocodeResult


# ============================================================================
# 辅助构造
# ============================================================================

def _future_trip_request(days: int = 3, destination: str = "北京") -> Dict[str, Any]:
    """构造合法的生成行程请求体（日期在未来，避免 Pydantic 校验拒绝）"""
    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=days - 1)
    return {
        "destination": destination,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "travelers": 2,
        "budget_level": "standard",
        "travel_style": "cultural",
        "max_places_per_day": 4,
    }


def _placeholder_trip(request: TripRequest, *, days: int = 3) -> TripResponse:
    """构造 Agent 返回的“坐标占位”草案 TripResponse（坐标 0,0 触发地图补全）。"""
    itinerary_days: List[ItineraryDay] = []
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
            )
        ]
        itinerary_days.append(
            ItineraryDay(
                day_number=i + 1,
                itinerary_date=request.start_date + timedelta(days=i),
                items=items,
                total_places=1,
                total_duration=120,
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
        trip_id="",  # 留空，由真实存储 create_trip 生成
        destination=request.destination,
        trip_name=f"{request.destination}测试行程",
        start_date=request.start_date,
        end_date=request.end_date,
        total_days=days,
        days=itinerary_days,
        budget=BudgetInfo(
            total_budget=1000.0,
            daily_avg_budget=333.33,
            budget_per_person=500.0,
            accommodation_budget=400.0,
            food_budget=300.0,
            transportation_budget=120.0,
            ticket_budget=0.0,
            other_budget=180.0,
        ),
        trip_highlights=["文化体验"],
        metadata={"needs_enrichment": True},
    )


def _geocode_result(name: str = "测试", lat: float = 39.9, lng: float = 116.4) -> GeocodeResult:
    return GeocodeResult(
        status=True,
        formatted_address=f"{name}地址",
        province="北京市",
        city="北京市",
        district="东城区",
        street="测试路",
        street_number="1号",
        adcode="110101",
        citycode="010",
        longitude=lng,
        latitude=lat,
        level="POI",
        info="OK",
        match_type="city_name",
    )


def _weather_info(d: date, weather: str = "晴") -> WeatherInfo:
    return WeatherInfo(
        forecast_date=d,
        temp_high=28,
        temp_low=20,
        temp_avg=24,
        weather_type=weather,
        humidity=50,
        wind_speed=3.0,
        wind_direction="东北风",
    )


# ============================================================================
# Fixture：真实应用 + 临时 SQLite + mock 外部依赖
# ============================================================================

@pytest.fixture
def app_env(tmp_path):
    """
    组装集成测试环境：
      - 临时 SQLite（真实 StorageService + 建表）
      - 真实 TripService 单例，仅替换外部依赖（agent/amap/weather/llm/cache）
      - 路由与 lifespan 指向同一临时存储
    返回 (TestClient, agent_mock, temp_storage)。
    """
    from app.api.main import app
    from app.services.storage_service import StorageService
    from app.services.trip_service import trip_service

    temp_storage = StorageService(database_url=f"sqlite:///{tmp_path / 'trips_test.db'}")
    assert temp_storage.init_database()

    agent = MagicMock()
    agent.plan.side_effect = lambda request, **kw: _placeholder_trip(request)
    agent.edit_day.side_effect = _fake_edit_day

    amap = MagicMock()
    amap.geocode = AsyncMock(return_value=_geocode_result())
    amap.get_place_photos = AsyncMock(return_value=["https://img.example.com/p1.jpg"])

    weather = MagicMock()
    weather.get_trip_weather = AsyncMock(side_effect=_fake_trip_weather)
    weather.get_live_weather = AsyncMock(return_value=_weather_info(date.today()))
    weather.get_forecast = AsyncMock(
        return_value=[_weather_info(date.today() + timedelta(days=i)) for i in range(3)]
    )
    weather.get_city_adcode = AsyncMock(return_value="110000")

    llm = MagicMock()
    llm.invoke.return_value.content = '{"suggestions": ["带伞", "防晒"]}'

    cache = MagicMock()
    cache.get.return_value = None

    patches = [
        patch("app.api.main.storage_service", temp_storage),
        patch("app.api.routes.export.storage_service", temp_storage),
        patch.object(trip_service, "_storage", temp_storage),
        patch.object(trip_service, "_agent", agent),
        patch.object(trip_service, "_amap_geo", amap),
        patch.object(trip_service, "_weather", weather),
        patch.object(trip_service, "_llm", llm),
        patch.object(trip_service, "_cache", cache),
    ]
    for p in patches:
        p.start()
    try:
        with TestClient(app) as client:
            yield client, agent, temp_storage
    finally:
        for p in reversed(patches):
            p.stop()


def _fake_edit_day(trip: TripResponse, day_number: int, instruction: str, **kwargs) -> TripResponse:
    """返回编辑后的行程：修改 Day1 景点名称 + 主题，验证真实持久化。"""
    edited = trip.model_copy(deep=True)
    if edited.days and day_number >= 1 and day_number <= len(edited.days):
        day = edited.days[day_number - 1]
        edited_days = list(edited.days)
        edited_days[day_number - 1] = day.model_copy(
            update={
                "day_theme": "深度文化游",
                "items": [
                    item.model_copy(
                        update={
                            "place": item.place.model_copy(
                                update={"name": "编辑后景点", "place_id": "edited-1"}
                            ),
                            "activity": "深度游览",
                        }
                    )
                    for item in day.items
                ],
            }
        )
        edited = edited.model_copy(update={"days": edited_days})
    edited = edited.model_copy(
        update={"metadata": {**(edited.metadata or {}), "edited_marker": "yes"}}
    )
    return edited


def _fake_trip_weather(
    cities: List[str], start_date: date, days: int
) -> Dict[str, List[WeatherInfo]]:
    return {
        city: [_weather_info(start_date + timedelta(days=i)) for i in range(days)]
        for city in cities
    }


# ============================================================================
# 系统端点：健康检查（真实数据库）
# ============================================================================

class TestSystemEndpointsIntegration:
    """系统端点集成测试（9.1.3）"""

    def test_root(self, app_env):
        client, _, _ = app_env
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["name"] == "智旅云图"

    def test_health_ok_with_real_db(self, app_env):
        client, _, _ = app_env
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["dependencies"]["database"] == "connected"

    def test_health_unhealthy_when_db_down(self, app_env):
        client, _, temp_storage = app_env
        with patch.object(temp_storage, "health_check", return_value={"database": "disconnected"}):
            resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"


# ============================================================================
# 行程 API：真实编排 + 真实落库
# ============================================================================

class TestTripApiIntegration:
    """行程 API 集成测试（真实 TripService 编排 + 真实 SQLite）"""

    def test_generate_trip_full_flow_persists(self, app_env):
        """生成行程 → 真实 Agent 调用 → 地图/天气补全 → 真实落库 → 历史可见"""
        client, agent, temp_storage = app_env
        payload = _future_trip_request()

        resp = client.post("/trip/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["trip_id"].startswith("TRP-")
        assert body["destination"] == "北京"
        assert len(body["days"]) == 3

        # Agent 被真实编排调用（说明未走缓存短路）
        agent.plan.assert_called_once()

        # 地图补全已生效（占位坐标被替换）
        first_place = body["days"][0]["items"][0]["place"]
        assert first_place["coordinate"]["latitude"] != 0.0
        assert first_place["address"] != "待地图服务补全"

        # 天气补全已生效
        assert body["days"][0]["weather"]["weather_type"] == "晴"

        # 真实落库：从临时 SQLite 直接读取
        history = temp_storage.get_trip_as_history(body["trip_id"])
        assert history is not None
        assert history.response.destination == "北京"

        # 历史接口可见
        hist_resp = client.get("/trip/history")
        assert hist_resp.status_code == 200
        hist_body = hist_resp.json()
        assert hist_body["total"] >= 1
        assert any(item["id"] == body["trip_id"] for item in hist_body["items"])

    def test_generate_trip_invalid_date_422(self, app_env):
        """过去日期被 Pydantic 校验拒绝 → 422（真实校验器）"""
        client, _, _ = app_env
        payload = _future_trip_request()
        payload["start_date"] = "2020-01-01"
        resp = client.post("/trip/generate", json=payload)
        assert resp.status_code == 422

    def test_generate_trip_unsupported_city_400(self, app_env):
        """C 级目的地（Agent 抛 CityNotSupportedError）→ 400 领域异常处理器"""
        from app.services.trip_service import CityNotSupportedError

        client, agent, _ = app_env
        agent.plan.side_effect = CityNotSupportedError("暂不支持该目的地")
        resp = client.post("/trip/generate", json=_future_trip_request())
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "CITY_NOT_SUPPORTED"

    def test_generate_trip_service_error_500(self, app_env):
        """编排服务通用错误 → 500 兜底处理器"""
        from app.services.trip_service import TripServiceError

        client, agent, _ = app_env
        agent.plan.side_effect = TripServiceError("编排失败")
        resp = client.post("/trip/generate", json=_future_trip_request())
        assert resp.status_code == 500
        assert resp.json()["error_code"] == "TRIP_SERVICE_ERROR"

    def test_edit_trip_full_flow_persists(self, app_env):
        """生成 → 编辑单日 → 真实读库 → 真实更新落库"""
        client, _, temp_storage = app_env
        trip_id = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]

        resp = client.post(
            "/trip/edit",
            json={"trip_id": trip_id, "day_number": 1, "instruction": "把故宫放到下午"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["trip_id"] == trip_id
        assert body["days"][0]["day_theme"] == "深度文化游"
        assert body["days"][0]["items"][0]["place"]["name"] == "编辑后景点"
        assert body["metadata"].get("edited_marker") == "yes"

        # 真实持久化：从临时 SQLite 读回
        history = temp_storage.get_trip_as_history(trip_id)
        assert history is not None
        assert history.response.days[0].day_theme == "深度文化游"

    def test_edit_trip_not_found_404(self, app_env):
        """编辑不存在的行程 → 404（真实存储查无 → 领域异常）"""
        client, _, _ = app_env
        resp = client.post(
            "/trip/edit",
            json={"trip_id": "NOPE", "day_number": 1, "instruction": "调整"},
        )
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"

    def test_history_filters_and_pagination(self, app_env):
        """历史列表真实过滤（目的地）+ 分页参数校验"""
        client, _, _ = app_env
        client.post("/trip/generate", json=_future_trip_request(destination="北京"))

        resp = client.get("/trip/history", params={"destination": "北京", "limit": 5, "offset": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["destination"] == "北京" for item in body["items"])

        resp = client.get("/trip/history", params={"limit": 0})
        assert resp.status_code == 422

    def test_get_trip_detail_full_flow(self, app_env):
        """生成行程 → GET /trip/{id} 返回真实落库的完整详情"""
        client, _, _ = app_env
        trip_id = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]

        resp = client.get(f"/trip/{trip_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trip_id"] == trip_id
        assert body["destination"] == "北京"
        assert len(body["days"]) == 3
        # 详情与落库数据一致（含地图补全后的真实坐标）
        first_place = body["days"][0]["items"][0]["place"]
        assert first_place["coordinate"]["latitude"] != 0.0
        assert first_place["address"] != "待地图服务补全"

    def test_get_trip_detail_not_found_404(self, app_env):
        """查询不存在的行程 → 404"""
        client, _, _ = app_env
        resp = client.get("/trip/TRP-NOT-EXIST")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"

    def test_batch_delete_trips_full_flow(self, app_env):
        """生成两条行程 → 批量删除 → 历史不可见"""
        client, _, temp_storage = app_env
        id1 = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]
        id2 = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]

        resp = client.post("/trip/history/batch-delete", json={"trip_ids": [id1, id2]})
        assert resp.status_code == 200
        assert resp.json()["affected"] == 2
        assert temp_storage.get_trip_as_history(id1) is None
        assert temp_storage.get_trip_as_history(id2) is None

    def test_batch_favorite_trips_full_flow(self, app_env):
        """生成两条行程 → 批量收藏 → 仅看收藏可见；再批量取消 → 不可见"""
        client, _, _ = app_env
        id1 = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]
        id2 = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]

        resp = client.post(
            "/trip/history/batch-favorite",
            json={"trip_ids": [id1, id2], "is_favorite": True},
        )
        assert resp.status_code == 200
        assert resp.json()["affected"] == 2

        fav_resp = client.get("/trip/history", params={"is_favorite": True})
        assert fav_resp.status_code == 200
        fav_ids = [item["id"] for item in fav_resp.json()["items"]]
        assert id1 in fav_ids
        assert id2 in fav_ids

        resp = client.post(
            "/trip/history/batch-favorite",
            json={"trip_ids": [id1, id2], "is_favorite": False},
        )
        assert resp.status_code == 200
        assert resp.json()["affected"] == 2

        fav_resp = client.get("/trip/history", params={"is_favorite": True})
        fav_ids = [item["id"] for item in fav_resp.json()["items"]]
        assert id1 not in fav_ids
        assert id2 not in fav_ids

    def test_delete_trip_full_flow(self, app_env):
        """生成 → 删除 → 204 → 历史不可见 → 再删 404"""
        client, _, temp_storage = app_env
        trip_id = client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]

        resp = client.delete(f"/trip/history/{trip_id}")
        assert resp.status_code == 204

        assert temp_storage.get_trip_as_history(trip_id) is None

        resp = client.delete(f"/trip/history/{trip_id}")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"


# ============================================================================
# 导出 API：真实存储读取
# ============================================================================

class TestExportApiIntegration:
    """导出 API 集成测试（真实存储读取 + 真实 Markdown 渲染）"""

    def _create_trip(self, client) -> str:
        return client.post("/trip/generate", json=_future_trip_request()).json()["trip_id"]

    def test_export_markdown_real_render(self, app_env):
        """Markdown 真实渲染：标题/目的地/每日行程来自真实存储数据"""
        client, _, _ = app_env
        trip_id = self._create_trip(client)

        resp = client.get(f"/export/markdown/{trip_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "attachment" in resp.headers["content-disposition"]
        text = resp.text
        assert "北京测试行程" in text
        assert "**目的地**: 北京" in text
        assert "Day 1" in text

    def test_export_pdf_success(self, app_env):
        """
        PDF 路由真实链路（存储读取 + 响应头）。
        渲染函数 mock：本机缺 WeasyPrint/GTK 原生库（Windows 环境限制），
        真实渲染路径由 test_export_service.py 的依赖缺失用例覆盖。
        """
        client, _, _ = app_env
        trip_id = self._create_trip(client)

        with patch(
            "app.api.routes.export.export_service.export_to_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-1.4 mock",
        ):
            resp = client.get(f"/export/pdf/{trip_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-1.4 mock"
        assert "attachment" in resp.headers["content-disposition"]

    def test_export_not_found_404(self, app_env):
        """导出不存在的行程 → 404（真实存储查无）"""
        client, _, _ = app_env
        resp = client.get("/export/markdown/NOPE")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"


# ============================================================================
# 天气 API：真实路由 + mock 天气服务
# ============================================================================

class TestWeatherApiIntegration:
    """天气 API 集成测试（真实路由，mock 网络服务）"""

    def _mock_weather_svc(self) -> MagicMock:
        svc = MagicMock()
        svc.get_live_weather = AsyncMock(
            return_value=WeatherInfo(
                forecast_date=date.today(),
                temp_high=28,
                temp_low=20,
                temp_avg=24,
                weather_type="晴",
            )
        )
        svc.get_forecast = AsyncMock(
            return_value=[
                WeatherInfo(
                    forecast_date=date.today() + timedelta(days=i),
                    temp_high=28,
                    temp_low=20,
                    weather_type="晴",
                )
                for i in range(3)
            ]
        )
        svc.get_city_adcode = AsyncMock(return_value="110000")
        return svc

    def test_get_weather_both(self, app_env):
        client, _, _ = app_env
        svc = self._mock_weather_svc()
        with patch("app.api.routes.weather._weather_svc", svc):
            resp = client.get("/weather/北京", params={"days": 3, "mode": "both"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["city"] == "北京"
        assert body["adcode"] == "110000"
        assert body["live"]["weather_type"] == "晴"
        assert len(body["forecast"]) == 3

    def test_get_weather_live_only(self, app_env):
        client, _, _ = app_env
        svc = self._mock_weather_svc()
        with patch("app.api.routes.weather._weather_svc", svc):
            resp = client.get("/weather/北京", params={"mode": "live"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["live"] is not None
        assert body["forecast"] == []
        svc.get_forecast.assert_not_called()

    def test_get_weather_invalid_days_422(self, app_env):
        client, _, _ = app_env
        svc = self._mock_weather_svc()
        with patch("app.api.routes.weather._weather_svc", svc):
            resp = client.get("/weather/北京", params={"days": 99})
        assert resp.status_code == 422

    def test_get_weather_service_unavailable_503(self, app_env):
        client, _, _ = app_env
        with patch("app.api.routes.weather._weather_svc", None), \
             patch("app.api.routes.weather.get_weather_service", return_value=None), \
             patch("app.api.routes.weather.init_weather_service", side_effect=RuntimeError("no key")):
            resp = client.get("/weather/北京")
        assert resp.status_code == 503
        assert resp.json()["error_code"] == "HTTP_ERROR"


# ============================================================================
# 基础设施：CORS / OpenAPI
# ============================================================================

class TestInfraIntegration:
    """中间件与文档端点集成测试"""

    def test_cors_preflight(self, app_env):
        client, _, _ = app_env
        resp = client.options(
            "/trip/generate",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_unknown_route_404_unified_body(self, app_env):
        client, _, _ = app_env
        resp = client.get("/no-such-route")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "HTTP_ERROR"

    def test_openapi_contains_all_routes(self, app_env):
        client, _, _ = app_env
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json()["paths"]
        for path in ("/trip/generate", "/trip/edit", "/trip/history", "/weather/{city}", "/health"):
            assert path in paths
