"""12.2 方案 B：SSE 流式生成接口测试（mock 服务层，不打真实 LLM / 高德）

覆盖：事件顺序（poi/draft 先于 final）、final 含完整行程、error 帧（C 级/服务错误）、
缓存命中快速路径、事件 sink 注入。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    TripResponse,
)
from app.services.trip_service import CityNotSupportedError

DEVICE_ID = "dev-stream-test"


def _future_trip_request() -> Dict[str, Any]:
    """构造合法的行程请求体（日期在未来）"""
    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=2)
    return {
        "destination": "北京",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "travelers": 2,
        "max_places_per_day": 4,
    }


def _sample_trip() -> TripResponse:
    """构造最小完整 TripResponse"""
    start = date.today() + timedelta(days=14)
    return TripResponse(
        trip_id="TRP-STREAM-001",
        destination="北京",
        trip_name="北京流式测试行程",
        start_date=start,
        end_date=start + timedelta(days=1),
        total_days=1,
        days=[
            ItineraryDay(
                day_number=1,
                itinerary_date=start,
                day_theme="文化之旅",
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
                        ),
                        activity="游览",
                    )
                ],
                total_places=1,
            )
        ],
        budget=BudgetInfo(
            total_budget=2000.0,
            daily_avg_budget=1000.0,
            budget_per_person=1000.0,
        ),
        trip_highlights=["文化体验"],
    )


@pytest.fixture
def client():
    """创建 TestClient，并隔离数据库初始化副作用"""
    from app.api.main import app

    with patch("app.api.main.storage_service.init_database", return_value=True), \
         patch("app.api.main.storage_service.health_check", return_value={"database": "connected"}):
        with TestClient(app, headers={"X-Device-Id": DEVICE_ID}) as c:
            yield c


class TestGenerateStream:
    """12.2.3 POST /trip/generate/stream"""

    @staticmethod
    def _frames(text: str) -> list[tuple[str, dict]]:
        """解析 SSE 文本为 (event, data) 帧列表"""
        frames: list[tuple[str, dict]] = []
        for block in text.split("\n\n"):
            event: str | None = None
            data_lines: list[str] = []
            for line in block.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if event and data_lines:
                frames.append((event, json.loads("\n".join(data_lines))))
        return frames

    def test_stream_emits_poi_before_final(self, client):
        """事件顺序：status/poi/draft 先于 final；final 含完整行程"""
        def fake_generate(request, *, user_id=None, use_cache=True, on_event=None):
            assert on_event is not None  # 事件 sink 已注入
            on_event({"type": "status", "stage": "poi_pool", "message": "构建候选池", "progress": 15})
            on_event({
                "type": "poi",
                "category": "scenic",
                "items": [{"name": "故宫", "category": "景点", "photos": ["https://x"], "rating": 4.8, "score": 9.2}],
            })
            on_event({
                "type": "draft",
                "days": [{"day_number": 1, "theme": "文化之旅", "places": ["故宫"]}],
                "highlights": ["文化体验"],
            })
            return _sample_trip()

        with patch("app.api.routes.trip.trip_service.generate_trip", new=fake_generate):
            resp = client.post("/trip/generate/stream", json=_future_trip_request())
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        frames = self._frames(resp.text)
        events = [e for e, _ in frames]
        assert "poi" in events and "draft" in events and "final" in events
        assert events.index("poi") < events.index("final")
        assert events.index("draft") < events.index("final")
        final_data = next(d for e, d in frames if e == "final")
        assert final_data["trip"]["trip_id"] == "TRP-STREAM-001"

    def test_stream_city_not_supported_error_frame(self, client):
        """C 级目的地 → error 帧（CITY_NOT_SUPPORTED），HTTP 仍 200"""
        def fake_error(request, **kwargs):
            raise CityNotSupportedError("暂不支持该目的地")

        with patch("app.api.routes.trip.trip_service.generate_trip", new=fake_error):
            resp = client.post("/trip/generate/stream", json=_future_trip_request())
        assert resp.status_code == 200
        frames = self._frames(resp.text)
        error_frame = next(d for e, d in frames if e == "error")
        assert error_frame["error_code"] == "CITY_NOT_SUPPORTED"
        assert "暂不支持" in error_frame["message"]

    def test_stream_service_error_frame(self, client):
        """服务异常 → error 帧（TRIP_SERVICE_ERROR）"""
        def fake_fail(request, **kwargs):
            raise RuntimeError("LLM 超时")

        with patch("app.api.routes.trip.trip_service.generate_trip", new=fake_fail):
            resp = client.post("/trip/generate/stream", json=_future_trip_request())
        assert resp.status_code == 200
        frames = self._frames(resp.text)
        error_frame = next(d for e, d in frames if e == "error")
        assert error_frame["error_code"] == "TRIP_SERVICE_ERROR"
        assert "LLM 超时" in error_frame["message"]

    def test_stream_cache_hit_quick_path(self, client):
        """缓存命中：status(cache_hit) 后直接 final"""
        def fake_cache(request, **kwargs):
            kwargs["on_event"]({
                "type": "status",
                "stage": "cache_hit",
                "message": "命中缓存",
                "progress": 100,
            })
            return _sample_trip()

        with patch("app.api.routes.trip.trip_service.generate_trip", new=fake_cache):
            resp = client.post("/trip/generate/stream", json=_future_trip_request())
        frames = self._frames(resp.text)
        statuses = [d for e, d in frames if e == "status"]
        assert any(d["stage"] == "cache_hit" for d in statuses)
        assert any(e == "final" for e, _ in frames)

    def test_stream_invalid_date(self, client):
        """过去日期被 Pydantic 校验拒绝 → 422"""
        req = _future_trip_request()
        req["start_date"] = "2020-01-01"
        resp = client.post("/trip/generate/stream", json=req)
        assert resp.status_code == 422
