"""
智旅云图 - API 路由集成测试（Phase 7.1-7.4）

使用 FastAPI TestClient + mock 服务层，不打真实 LLM / 高德 / SQLite。
覆盖：健康检查、行程生成/编辑/历史/删除、Markdown/PDF 导出、天气查询。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    TripHistory,
    TripRequest,
    TripHistorySummary,
    TripResponse,
    WeatherInfo,
)
from app.services.trip_service import TripNotFoundError

DEVICE_ID = "dev-test-client"


def _sample_trip() -> TripResponse:
    """构造最小完整 TripResponse"""
    return TripResponse(
        trip_id="TRP-API-001",
        destination="北京",
        trip_name="北京测试行程",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        total_days=3,
        days=[
            ItineraryDay(
                day_number=1,
                itinerary_date=date(2026, 9, 10),
                items=[
                    ItineraryItem(
                        start_time="09:00",
                        end_time="11:00",
                        place=PlaceInfo(
                            place_id="p1",
                            name="故宫",
                            address="东城区景山前街4号",
                            coordinate=Coordinate(latitude=39.9163, longitude=116.3972),
                            category="景点",
                            ticket_price=60.0,
                        ),
                        activity="游览",
                        ticket_price=60.0,
                    )
                ],
                total_places=1,
            )
        ],
        budget=BudgetInfo(
            total_budget=2000.0,
            daily_avg_budget=666.67,
            budget_per_person=1000.0,
        ),
        trip_highlights=["文化体验"],
    )


def _future_trip_request() -> Dict[str, Any]:
    """构造合法的生成行程请求体（日期在未来）"""
    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=2)
    return {
        "destination": "北京",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "travelers": 2,
        "max_places_per_day": 4,
    }


@pytest.fixture
def client():
    """创建 TestClient，并隔离数据库初始化副作用"""
    from app.api.main import app

    with patch("app.api.main.storage_service.init_database", return_value=True), \
         patch("app.api.main.storage_service.health_check", return_value={"database": "connected"}):
        # 默认携带设备标识头：模拟浏览器指纹隔离下的正常请求
        with TestClient(app, headers={"X-Device-Id": DEVICE_ID}) as c:
            yield c


@pytest.fixture
def client_no_device():
    """不带设备标识的客户端，用于验证缺失 X-Device-Id 时返回 400。"""
    from app.api.main import app

    with patch("app.api.main.storage_service.init_database", return_value=True), \
         patch("app.api.main.storage_service.health_check", return_value={"database": "connected"}):
        with TestClient(app) as c:
            yield c


class TestSystemEndpoints:
    """系统端点（7.4.4）"""

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert "version" in body

    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["dependencies"]["database"] == "connected"


class TestTripApi:
    """行程 API（7.1）"""

    def test_generate_trip_success(self, client):
        """POST /trip/generate 正常生成"""
        mock_trip = _sample_trip()
        with patch("app.api.routes.trip.trip_service.generate_trip", return_value=mock_trip) as mock_gen:
            resp = client.post("/trip/generate", json=_future_trip_request())
        assert resp.status_code == 200
        body = resp.json()
        assert body["trip_id"] == "TRP-API-001"
        assert body["destination"] == "北京"
        assert len(body["days"]) == 1
        mock_gen.assert_called_once()
        assert mock_gen.call_args[0][0].destination == "北京"

    def test_generate_trip_invalid_date(self, client):
        """过去日期被 Pydantic 校验拒绝 → 422"""
        req = _future_trip_request()
        req["start_date"] = "2020-01-01"
        resp = client.post("/trip/generate", json=req)
        assert resp.status_code == 422

    def test_generate_trip_unsupported_city(self, client):
        """城市不支持 → 400（领域异常处理器）"""
        from app.services.trip_service import CityNotSupportedError

        with patch(
            "app.api.routes.trip.trip_service.generate_trip",
            side_effect=CityNotSupportedError("暂不支持该目的地"),
        ):
            resp = client.post("/trip/generate", json=_future_trip_request())
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "CITY_NOT_SUPPORTED"

    def test_edit_trip_success(self, client):
        """POST /trip/edit 编辑行程"""
        mock_trip = _sample_trip()
        payload = {"trip_id": "TRP-API-001", "day_number": 1, "instruction": "把故宫放到下午"}
        with patch("app.api.routes.trip.trip_service.edit_trip_day", return_value=mock_trip) as mock_edit:
            resp = client.post("/trip/edit", json=payload)
        assert resp.status_code == 200
        assert resp.json()["trip_id"] == "TRP-API-001"
        mock_edit.assert_called_once()
        assert mock_edit.call_args.kwargs["user_id"] == DEVICE_ID

    def test_edit_trip_not_found(self, client):
        """行程不存在 → 404"""
        payload = {"trip_id": "NOPE", "day_number": 1, "instruction": "调整"}
        with patch(
            "app.api.routes.trip.trip_service.edit_trip_day",
            side_effect=TripNotFoundError("NOPE"),
        ):
            resp = client.post("/trip/edit", json=payload)
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"

    def test_list_history(self, client):
        """GET /trip/history 分页历史"""
        items = [
            TripHistorySummary(
                id="TRP-API-001",
                destination="北京",
                start_date=date(2026, 9, 10),
                end_date=date(2026, 9, 12),
                total_days=3,
                created_at=datetime(2026, 9, 1, 10, 0),
                updated_at=datetime(2026, 9, 1, 10, 0),
            )
        ]
        with patch("app.api.routes.trip.trip_service.list_trips", return_value=(items, 1)) as mock_list:
            resp = client.get("/trip/history", params={"limit": 20, "offset": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["destination"] == "北京"
        mock_list.assert_called_once()
        assert mock_list.call_args.kwargs["user_id"] == DEVICE_ID

    def test_list_history_missing_device_id(self, client_no_device):
        """GET /trip/history 缺失设备标识 → 400"""
        resp = client_no_device.get("/trip/history", params={"limit": 20, "offset": 0})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "HTTP_ERROR"

    def test_get_trip_detail_success(self, client):
        """GET /trip/{trip_id} 返回完整行程详情"""
        history = TripHistory(
            history_id="TRP-API-001",
            request=TripRequest(**_future_trip_request()),
            response=_sample_trip(),
        )
        with patch("app.api.routes.trip.trip_service.get_trip", return_value=history) as mock_get:
            resp = client.get("/trip/TRP-API-001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trip_id"] == "TRP-API-001"
        assert body["destination"] == "北京"
        assert len(body["days"]) == 1
        mock_get.assert_called_once_with("TRP-API-001", user_id=DEVICE_ID)

    def test_get_trip_detail_not_found(self, client):
        """行程不存在 → 404"""
        with patch("app.api.routes.trip.trip_service.get_trip", return_value=None):
            resp = client.get("/trip/TRP-API-404")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"

    def test_delete_trip_success(self, client):
        """DELETE /trip/history/{id} → 204"""
        with patch("app.api.routes.trip.trip_service.delete_trip", return_value=True) as mock_del:
            resp = client.delete("/trip/history/TRP-API-001")
        assert resp.status_code == 204
        mock_del.assert_called_once_with("TRP-API-001", user_id=DEVICE_ID)

    def test_delete_trip_not_found(self, client):
        """删除不存在的行程 → 404"""
        with patch("app.api.routes.trip.trip_service.delete_trip", return_value=False) as mock_del:
            resp = client.delete("/trip/history/TRP-API-001")
        assert resp.status_code == 404
        mock_del.assert_called_once_with("TRP-API-001", user_id=DEVICE_ID)

    def test_batch_delete_trips_success(self, client):
        """POST /trip/history/batch-delete 批量删除"""
        with patch("app.api.routes.trip.trip_service.delete_trips", return_value=2) as mock_del:
            resp = client.post(
                "/trip/history/batch-delete",
                json={"trip_ids": ["TRP-API-001", "TRP-API-002"]},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["affected"] == 2
        assert body["total"] == 2
        mock_del.assert_called_once_with(["TRP-API-001", "TRP-API-002"], user_id=DEVICE_ID)

    def test_batch_delete_trips_empty_ids(self, client):
        """批量删除空 ID 列表 → 422"""
        resp = client.post("/trip/history/batch-delete", json={"trip_ids": []})
        assert resp.status_code == 422

    def test_batch_favorite_trips_success(self, client):
        """POST /trip/history/batch-favorite 批量收藏"""
        with patch("app.api.routes.trip.trip_service.set_favorites", return_value=3) as mock_fav:
            resp = client.post(
                "/trip/history/batch-favorite",
                json={"trip_ids": ["TRP-API-001", "TRP-API-002", "TRP-API-003"], "is_favorite": True},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["affected"] == 3
        assert body["total"] == 3
        mock_fav.assert_called_once_with(
            ["TRP-API-001", "TRP-API-002", "TRP-API-003"],
            True,
            user_id=DEVICE_ID,
        )

    def test_batch_favorite_trips_empty_ids(self, client):
        """批量收藏空 ID 列表 → 422"""
        resp = client.post(
            "/trip/history/batch-favorite",
            json={"trip_ids": [], "is_favorite": True},
        )
        assert resp.status_code == 422


class TestExportApi:
    """导出 API（7.2）"""

    def _patch_trip_data(self):
        """mock storage_service.get_trip 返回合法行程字典"""
        trip_dict = {"response_data": _sample_trip().model_dump(mode="json")}
        return patch("app.api.routes.export.storage_service.get_trip", return_value=trip_dict)

    def test_export_markdown_success(self, client):
        """GET /export/markdown/{trip_id} 返回 Markdown"""
        with self._patch_trip_data(), \
             patch(
                 "app.api.routes.export.export_service.export_to_markdown",
                 new_callable=AsyncMock,
                 return_value="# 北京测试行程\n",
             ):
            resp = client.get("/export/markdown/TRP-API-001")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert resp.text == "# 北京测试行程\n"
        assert "attachment" in resp.headers["content-disposition"]

    def test_export_pdf_success(self, client):
        """GET /export/pdf/{trip_id} 返回 PDF 字节"""
        with self._patch_trip_data(), \
             patch(
                 "app.api.routes.export.export_service.export_to_pdf",
                 new_callable=AsyncMock,
                 return_value=b"%PDF-1.4 mock",
             ):
            resp = client.get("/export/pdf/TRP-API-001")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-1.4 mock"

    def test_export_trip_not_found(self, client):
        """行程不存在 → 404"""
        with patch("app.api.routes.export.storage_service.get_trip", return_value=None):
            resp = client.get("/export/markdown/NOPE")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TRIP_NOT_FOUND"


class TestWeatherApi:
    """天气 API（7.3）"""

    def _mock_weather_svc(self):
        """构造 mock 天气服务并注入路由模块"""
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

    def test_get_weather_both(self, client):
        """GET /weather/{city}?mode=both 返回实时 + 预报"""
        svc = self._mock_weather_svc()
        with patch("app.api.routes.weather._weather_svc", svc):
            resp = client.get("/weather/北京", params={"days": 3, "mode": "both"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["city"] == "北京"
        assert body["adcode"] == "110000"
        assert body["live"]["weather_type"] == "晴"
        assert len(body["forecast"]) == 3

    def test_get_weather_live_only(self, client):
        """mode=live 只返回实时"""
        svc = self._mock_weather_svc()
        with patch("app.api.routes.weather._weather_svc", svc):
            resp = client.get("/weather/北京", params={"mode": "live"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["live"] is not None
        assert body["forecast"] == []
        svc.get_forecast.assert_not_called()

    def test_get_weather_invalid_days(self, client):
        """days 超出 1-4 → 422"""
        svc = self._mock_weather_svc()
        with patch("app.api.routes.weather._weather_svc", svc):
            resp = client.get("/weather/北京", params={"days": 99})
        assert resp.status_code == 422

    def test_get_weather_service_unavailable(self, client):
        """服务不可用 → 503"""
        with patch("app.api.routes.weather._weather_svc", None), \
             patch("app.api.routes.weather.get_weather_service", return_value=None), \
             patch("app.api.routes.weather.init_weather_service", side_effect=RuntimeError("no key")):
            resp = client.get("/weather/北京")
        assert resp.status_code == 503
        assert resp.json()["error_code"] == "HTTP_ERROR"

