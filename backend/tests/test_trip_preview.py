"""12.1 方案 A：行程预览接口测试（mock 服务层，不打真实高德/LLM）

覆盖：A 级（preset）与 B 级（dynamic）出图、有图优先排序、空池/失败降级、
候选数量上限、路由返回与 C 级错误透传。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.schemas import PreviewCandidate, TripPreviewResponse
from app.services.place_candidate_service import CandidatePlace, CandidatePool
from app.services.trip_service import CityNotSupportedError, TripService

DEVICE_ID = "dev-preview-test"


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


def _place(
    place_id: str,
    name: str,
    category: str,
    *,
    district: str = "",
    rating: float = 4.0,
    photos: list[str] | None = None,
    score: float = 6.0,
) -> CandidatePlace:
    return CandidatePlace(
        place_id=place_id,
        name=name,
        category=category,
        address=f"{district}示例地址",
        district=district or None,
        rating=rating,
        photos=photos or [],
        score=score,
    )


def _pool(city: str = "北京", *, with_photos: bool = True) -> CandidatePool:
    """三池各 1 个候选（带图可选）"""
    photos = ["https://restapi.amap.com/v3/place/staticmap?x=1"] if with_photos else []
    scenic = _place("s1", "故宫", "景点", district="东城区", rating=4.8, photos=photos, score=9.2)
    food = _place("f1", "四季民福", "餐厅", district="东城区", rating=4.5, photos=photos, score=8.0)
    hotel = _place("h1", "王府井大酒店", "酒店", district="东城区", rating=4.2, photos=photos, score=7.1)
    return CandidatePool(
        city=city,
        places=[scenic, food, hotel],
        scenic_places=[scenic],
        food_places=[food],
        hotel_places=[hotel],
    )


def _service_with_pool(pool: Optional[CandidatePool] = None, side_effect: Any = None) -> TripService:
    place_service = MagicMock()
    if side_effect is not None:
        place_service.build_pool_sync.side_effect = side_effect
    elif pool is not None:
        place_service.build_pool_sync.return_value = pool
    return TripService(place_service=place_service)


class TestBuildPreview:
    """12.1.2 build_preview 服务层"""

    def _request(self, destination: str = "北京"):
        from app.models.schemas import TripRequest

        body = _future_trip_request()
        body["destination"] = destination
        return TripRequest(**body)

    def test_preset_city_returns_poi_candidates(self):
        """A 级城市（北京）：归一化 + 候选出图 + preset 标记"""
        resp = _service_with_pool(_pool(city="北京")).build_preview(self._request("北京"))
        assert resp.destination == "北京"
        assert resp.city_level == "preset"
        assert resp.source == "poi_pool"
        assert resp.total == 3
        assert all(c.photos for c in resp.candidates)
        assert resp.estimate_seconds >= 0

    def test_dynamic_city_returns_poi_candidates(self):
        """B 级城市（广州）：dynamic 标记 + 出图"""
        resp = _service_with_pool(_pool(city="广州")).build_preview(self._request("广州"))
        assert resp.city_level == "dynamic"
        assert resp.total == 3
        assert resp.candidates[0].photos

    def test_normalized_destination_used(self):
        """'北京市' 归一化为 '北京'（复用 _normalize_destination）"""
        resp = _service_with_pool(_pool(city="北京")).build_preview(self._request("北京市"))
        assert resp.destination == "北京"
        assert resp.city_level == "preset"

    def test_photos_first_ordering(self):
        """有图候选优先于无图候选（图片墙先满）"""
        pool = _pool(city="北京")
        pool.scenic_places[0].photos = []          # 高分景点无图
        pool.food_places[0].score = 1.0            # 低分餐厅有图
        pool.hotel_places[0].photos = []           # 酒店也无图，排除干扰
        resp = _service_with_pool(pool).build_preview(self._request())
        assert resp.candidates[0].name == "四季民福"  # 有图优先
        assert resp.candidates[0].photos

    def test_candidate_limits(self):
        """候选数量上限：景点 8 / 餐厅 4 / 酒店 3"""
        pool = _pool(city="北京")
        pool.scenic_places = [_place(f"s{i}", f"景点{i}", "景点", photos=["https://x"], score=9.0) for i in range(10)]
        pool.food_places = [_place(f"f{i}", f"餐厅{i}", "餐厅", photos=["https://x"], score=8.0) for i in range(6)]
        pool.hotel_places = [_place(f"h{i}", f"酒店{i}", "酒店", photos=["https://x"], score=7.0) for i in range(5)]
        resp = _service_with_pool(pool).build_preview(self._request())
        assert resp.total == 8 + 4 + 3
        assert [c.category for c in resp.candidates].count("景点") == 8
        assert [c.category for c in resp.candidates].count("餐厅") == 4
        assert [c.category for c in resp.candidates].count("酒店") == 3

    def test_empty_pool_fallback(self):
        """候选池为空 → 空 candidates + source=fallback + 警告（不抛错）"""
        pool = CandidatePool(city="北京", warnings=["地图未返回任何 POI"])
        resp = _service_with_pool(pool).build_preview(self._request())
        assert resp.total == 0
        assert resp.source == "fallback"
        assert resp.warnings

    def test_pool_failure_fallback(self):
        """候选池拉取异常 → 空 candidates + source=fallback（不阻断）"""
        resp = _service_with_pool(
            side_effect=RuntimeError("amap down")
        ).build_preview(self._request())
        assert resp.total == 0
        assert resp.source == "fallback"
        assert any("候选池构建失败" in w for w in resp.warnings)


@pytest.fixture
def client():
    """创建 TestClient，并隔离数据库初始化副作用"""
    from app.api.main import app

    with patch("app.api.main.storage_service.init_database", return_value=True), \
         patch("app.api.main.storage_service.health_check", return_value={"database": "connected"}):
        with TestClient(app, headers={"X-Device-Id": DEVICE_ID}) as c:
            yield c


class TestPreviewApi:
    """12.1.4 POST /trip/preview 路由"""

    def test_preview_success(self, client):
        """正常返回候选图片池"""
        preview = TripPreviewResponse(
            destination="北京",
            city_level="preset",
            candidates=[
                PreviewCandidate(name="故宫", category="景点", district="东城区", photos=["https://x"], score=9.2),
            ],
            total=1,
            estimate_seconds=1.23,
            source="poi_pool",
            warnings=[],
        )
        with patch("app.api.routes.trip.trip_service.build_preview", return_value=preview) as mock_preview:
            resp = client.post("/trip/preview", json=_future_trip_request())
        assert resp.status_code == 200
        body = resp.json()
        assert body["city_level"] == "preset"
        assert body["total"] == 1
        assert body["candidates"][0]["name"] == "故宫"
        mock_preview.assert_called_once()
        assert mock_preview.call_args[0][0].destination == "北京"

    def test_preview_unsupported_city(self, client):
        """C 级目的地异常透传 → 400 CITY_NOT_SUPPORTED"""
        with patch(
            "app.api.routes.trip.trip_service.build_preview",
            side_effect=CityNotSupportedError("暂不支持该目的地"),
        ):
            resp = client.post("/trip/preview", json=_future_trip_request())
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "CITY_NOT_SUPPORTED"

    def test_preview_invalid_date(self, client):
        """过去日期被 Pydantic 校验拒绝 → 422"""
        req = _future_trip_request()
        req["start_date"] = "2020-01-01"
        resp = client.post("/trip/preview", json=req)
        assert resp.status_code == 422
