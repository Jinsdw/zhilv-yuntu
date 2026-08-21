"""
智旅云图 - 动态 POI 候选池服务测试（5.3.1–5.3.5）

全部 mock map_service，不打真实高德。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.schemas import (
    BudgetLevel,
    Coordinate,
    TravelStyle,
    TripRequest,
)
from app.services.cache_service import CacheConfig, CacheNamespace, CacheService
from app.services.map_service import DistrictInfo, POIInfo, POISearchResult
from app.services.place_candidate_service import (
    CandidateFetchError,
    CandidatePlace,
    CandidatePool,
    PlaceCandidateConfig,
    PlaceCandidateService,
    SearchMode,
    build_query_plan,
    extract_seed_names_from_hints,
    filter_and_rank,
    poi_to_candidate,
)


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
        preferred_keywords=["宽窄巷子", "博物馆"],
        excluded_keywords=["酒吧"],
        max_places_per_day=4,
    )
    defaults.update(kwargs)
    return TripRequest(**defaults)


def _poi(
    pid: str,
    name: str,
    *,
    typ: str = "风景名胜;风景名胜",
    type_code: str = "110000",
    address: str = "测试路1号",
    lat: float = 30.67,
    lng: float = 104.06,
    area: str = "锦江区",
    tag: str = "热门",
    rating: Optional[float] = 4.5,
) -> POIInfo:
    return POIInfo(
        id=pid,
        name=name,
        type=typ,
        type_code=type_code,
        address=address,
        location=Coordinate(latitude=lat, longitude=lng),
        telephone="",
        distance=500,
        business_area=area,
        city="成都",
        tag=tag,
        rating=rating,
        cost=None,
        opening_hours="09:00-18:00",
        info="OK",
        status=True,
    )


def _ok_result(pois: list[POIInfo], keyword: str = "x") -> POISearchResult:
    return POISearchResult(
        keyword=keyword,
        city="成都",
        pois=pois,
        count=len(pois),
        page=1,
        page_size=20,
        info="OK",
        status=True,
    )


# ---------------------------------------------------------------------------
# 5.3.2 策略
# ---------------------------------------------------------------------------

class TestQueryPlan:
    def test_build_query_plan_includes_preferred_and_style(self):
        req = _future_request()
        plan = build_query_plan(req, max_places=30)
        assert plan.city == "成都"
        assert plan.target_size <= 30
        assert "宽窄巷子" in plan.preferred_keywords
        assert "酒吧" in plan.excluded_keywords
        labels = [t.label for t in plan.tasks]
        assert any(l.startswith("preferred:") for l in labels)
        assert any(l.startswith("style_") for l in labels)
        assert any(t.mode == SearchMode.TYPES for t in plan.tasks)

    def test_excluded_preferred_not_added_as_task(self):
        req = _future_request(
            preferred_keywords=["酒吧街"],
            excluded_keywords=["酒吧"],
        )
        plan = build_query_plan(req)
        assert not any(
            t.keywords and "酒吧" in t.keywords
            for t in plan.tasks
            if t.label.startswith("preferred:")
        )

    def test_extract_seed_names_from_rag_hints(self):
        hints = [
            "推荐：武侯祠，必打卡。",
            "- **杜甫草堂** 很值得",
            "《金沙遗址》博物馆",
        ]
        seeds = extract_seed_names_from_hints(hints)
        assert any("武侯祠" in s for s in seeds)
        assert any("杜甫草堂" in s for s in seeds)

    def test_foodie_adds_food_types(self):
        req = _future_request(travel_style=TravelStyle.FOODIE, preferred_keywords=[])
        plan = build_query_plan(req)
        assert any(t.label == "food:types" for t in plan.tasks)


# ---------------------------------------------------------------------------
# 5.3.4 过滤打分
# ---------------------------------------------------------------------------

class TestFilterAndRank:
    def _plan(self, **kw):
        req = _future_request(**kw)
        return build_query_plan(req)

    def test_exclude_keywords(self):
        plan = self._plan(excluded_keywords=["酒吧"])
        places = [
            CandidatePlace(place_id="1", name="宽窄巷子", address="a", score=0),
            CandidatePlace(place_id="2", name="九眼桥酒吧", address="b", score=0),
        ]
        ranked, _ = filter_and_rank(places, plan, max_places=10)
        names = [p.name for p in ranked]
        assert "宽窄巷子" in names
        assert "九眼桥酒吧" not in names

    def test_dedup_keeps_higher_score(self):
        plan = self._plan(preferred_keywords=["宽窄巷子"])
        a = CandidatePlace(
            place_id="1",
            name="宽窄巷子",
            address="旧",
            coordinate=None,
            score=0,
        )
        b = CandidatePlace(
            place_id="2",
            name="宽窄巷子",
            address="新",
            coordinate=Coordinate(latitude=30.6, longitude=104.0),
            tags=["宽窄巷子"],
            rating=4.8,
            score=0,
        )
        ranked, _ = filter_and_rank([a, b], plan, max_places=10)
        assert len(ranked) == 1
        assert ranked[0].place_id == "2"
        assert ranked[0].coordinate is not None

    def test_non_travel_filtered(self):
        plan = self._plan()
        places = [
            CandidatePlace(place_id="1", name="某某科技有限公司", address="x"),
            CandidatePlace(place_id="2", name="武侯祠", address="y", tags=["古迹"]),
        ]
        ranked, _ = filter_and_rank(places, plan, max_places=10)
        assert [p.name for p in ranked] == ["武侯祠"]

    def test_max_places_and_diversity(self):
        plan = self._plan(preferred_keywords=[])
        places = []
        for i in range(20):
            places.append(
                CandidatePlace(
                    place_id=str(i),
                    name=f"景点{i}",
                    address=f"地址{i}",
                    business_area="同区" if i < 15 else f"区{i}",
                    coordinate=Coordinate(latitude=30.0 + i * 0.01, longitude=104.0),
                    rating=4.0,
                )
            )
        ranked, warnings = filter_and_rank(places, plan, max_places=8, bucket_cap=3)
        assert len(ranked) == 8
        assert any("裁剪" in w for w in warnings)

    def test_poi_to_candidate(self):
        c = poi_to_candidate(_poi("amap-1", "杜甫草堂", typ="风景名胜;文物古迹"))
        assert c is not None
        assert c.place_id == "amap-1"
        assert c.name == "杜甫草堂"
        assert c.coordinate is not None


# ---------------------------------------------------------------------------
# 5.3.3 / 5.3.5 服务
# ---------------------------------------------------------------------------

class TestPlaceCandidateService:
    @pytest.fixture
    def cache(self):
        return CacheService(config=CacheConfig(prefix="test_place"))

    @pytest.fixture
    def map_mock(self):
        m = MagicMock()
        m.search_poi = AsyncMock(
            return_value=_ok_result(
                [
                    _poi("p1", "武侯祠", area="武侯区", tag="古迹,博物馆"),
                    _poi("p2", "杜甫草堂", area="青羊区", tag="古迹"),
                    _poi("p3", "某酒吧", area="锦江区", tag="夜生活"),
                ]
            )
        )
        m.search_nearby = AsyncMock(
            return_value=_ok_result(
                [_poi("p4", "人民公园", area="青羊区", tag="公园", typ="风景名胜;公园")],
                keyword="景点",
            )
        )
        m.get_district = AsyncMock(
            return_value=[
                DistrictInfo(
                    name="成都市",
                    adcode="510100",
                    level="city",
                    center=Coordinate(latitude=30.67, longitude=104.06),
                    boundaries=[],
                    citycode="028",
                    province="四川省",
                    info="OK",
                    status=True,
                )
            ]
        )
        return m

    @pytest.fixture
    def service(self, map_mock, cache):
        return PlaceCandidateService(
            map_service=map_mock,
            cache=cache,
            config=PlaceCandidateConfig(
                max_places=20,
                per_task_limit=10,
                use_cache=True,
                rate_limit_delay=0.0,
                max_concurrency=4,
            ),
        )

    @pytest.mark.asyncio
    async def test_build_pool_filters_excluded(self, service, map_mock):
        req = _future_request(excluded_keywords=["酒吧"])
        pool = await service.build_pool(req, include_nearby=True)
        assert isinstance(pool, CandidatePool)
        names = [p.name for p in pool.places]
        assert "武侯祠" in names or "杜甫草堂" in names
        assert all("酒吧" not in n for n in names)
        assert map_mock.search_poi.await_count >= 1
        items = pool.to_prompt_items()
        assert items
        assert "place_id" in items[0] and "name" in items[0]

    @pytest.mark.asyncio
    async def test_cache_hit_on_second_fetch(self, service, map_mock):
        req = _future_request()
        plan = service.build_query_plan(req)
        task = plan.tasks[0]
        await service._execute_task(plan.city, task, city_center=None)
        first_calls = map_mock.search_poi.await_count
        pois, hit, err = await service._execute_task(plan.city, task, city_center=None)
        assert err is None
        assert hit is True
        assert pois
        assert map_mock.search_poi.await_count == first_calls

    @pytest.mark.asyncio
    async def test_empty_pool_on_total_fetch_failure(self, service, map_mock):
        map_mock.search_poi = AsyncMock(
            return_value=POISearchResult(
                keyword="x",
                city="成都",
                pois=[],
                count=0,
                page=1,
                page_size=20,
                info="FAIL",
                status=False,
            )
        )
        map_mock.search_nearby = AsyncMock(
            return_value=POISearchResult(
                keyword="x",
                city="",
                pois=[],
                count=0,
                page=1,
                page_size=20,
                info="FAIL",
                status=False,
            )
        )
        map_mock.get_district = AsyncMock(return_value=[])
        req = _future_request(preferred_keywords=["不存在的点"])
        pool = await service.build_pool(req, include_nearby=False)
        assert pool.places == []
        assert pool.warnings

    @pytest.mark.asyncio
    async def test_fetch_raw_raises_when_all_fail(self, service, map_mock):
        map_mock.search_poi = AsyncMock(side_effect=RuntimeError("network"))
        map_mock.get_district = AsyncMock(return_value=[])
        req = _future_request()
        plan = service.build_query_plan(req)
        with pytest.raises(CandidateFetchError):
            await service.fetch_raw(plan, include_nearby=False)

    @pytest.mark.asyncio
    async def test_resolve_name(self, service, map_mock):
        map_mock.search_poi = AsyncMock(
            return_value=_ok_result([_poi("x1", "宽窄巷子")], keyword="宽窄巷子")
        )
        place = await service.resolve_name("成都", "宽窄巷子")
        assert place is not None
        assert place.name == "宽窄巷子"
        assert place.place_id == "x1"

    @pytest.mark.asyncio
    async def test_resolve_name_empty_input(self, service):
        assert await service.resolve_name("", "x") is None
        assert await service.resolve_name("成都", "") is None

    def test_to_prompt_items_static(self):
        pool = CandidatePool(
            city="成都",
            places=[
                CandidatePlace(place_id="1", name="武侯祠", category="景点", score=9.1),
            ],
        )
        items = PlaceCandidateService.to_prompt_items(pool)
        assert items == [
            {
                "place_id": "1",
                "name": "武侯祠",
                "category": "景点",
                "address": "",
                "district": None,
                "tags": [],
                "score": 9.1,
            }
        ]

    def test_cache_namespace_place_exists(self):
        assert CacheNamespace.PLACE == "place"
