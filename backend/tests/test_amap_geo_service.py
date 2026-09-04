"""
智旅云图 - 高德地理编码服务测试（3.3.x / 3.4）

全部 mock _request_with_retry，不打真实高德 API。
覆盖 AmapGeoService 的参数构建、地理/逆地理编码、批量、POI 搜索与图片、智能回退等。
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.amap_geo_service import (
    AMAP_GEOCODE_URL,
    AMAP_PLACE_DETAIL_URL_V3,
    AMAP_PLACE_DETAIL_URL_V5,
    AMAP_PLACE_TEXT_URL,
    AMAP_REGEO_URL,
    AmapGeoService,
    CityMatchType,
    GeocodeResult,
    RegeoResult,
    get_amap_geo_service,
    init_amap_geo_service,
)


def _geocode_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德地理编码 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "geocodes": [
            {
                "formatted_address": "北京市朝阳区阜通东大街6号",
                "province": "北京市",
                "city": "北京市",
                "district": "朝阳区",
                "street": "阜通东大街",
                "number": "6号",
                "adcode": "110105",
                "citycode": "010",
                "location": "116.474488,39.99557",
                "level": "门牌号",
            }
        ],
    }
    data.update(kwargs)
    return data


def _regeo_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德逆地理编码 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "regeocode": {
            "formatted_address": "北京市朝阳区阜通东大街6号",
            "addressComponent": {
                "country": "中国",
                "province": "北京市",
                "city": "北京市",
                "district": "朝阳区",
                "township": "望京街道",
                "adcode": "110105",
                "citycode": "010",
                "streetNumber": {"street": "阜通东大街", "number": "6号"},
                "businessAreas": [
                    {"name": "望京", "location": "116.47,39.99", "id": "110105"}
                ],
            },
            "pois": [
                {
                    "id": "B000A123",
                    "name": "方恒国际中心",
                    "type": "商务写字楼",
                    "address": "阜通东大街6号",
                    "location": "116.474,39.995",
                    "distance": "50",
                    "businessarea": "望京",
                }
            ],
        },
    }
    data.update(kwargs)
    return data


@pytest.fixture
def service() -> AmapGeoService:
    """创建地理编码服务实例（关闭重试与限流延迟，加速测试）"""
    return AmapGeoService(
        api_key="test-key",
        max_retries=1,
        retry_delay=0,
        rate_limit_delay=0,
    )


class TestParams:
    """参数构建"""

    def test_build_city_params_empty(self, service):
        assert service._build_city_params() == {}
        assert service._build_city_params(None) == {}

    def test_build_city_params_city_name(self, service):
        params = service._build_city_params("北京", CityMatchType.CITY_NAME)
        assert params == {"city": "北京"}

    def test_build_city_params_city_code(self, service):
        params = service._build_city_params("010", CityMatchType.CITY_CODE)
        assert params == {"city": "010"}

    def test_build_city_params_adcode(self, service):
        params = service._build_city_params("110000", CityMatchType.ADCODE)
        assert params == {"city": "110000"}

    def test_geocode_params(self, service):
        params = service.geocode_params("天安门", "北京")
        assert params["key"] == "test-key"
        assert params["address"] == "天安门"
        assert params["city"] == "北京"
        assert params["output"] == "json"

    def test_geocode_params_no_city(self, service):
        params = service.geocode_params("天安门")
        assert "city" not in params

    def test_regeo_params(self, service):
        params = service.regeo_params(116.4, 39.9)
        assert params["location"] == "116.4,39.9"
        assert params["radius"] == 1000
        assert params["extensions"] == "base"
        assert params["output"] == "json"

    def test_regeo_params_radius_capped(self, service):
        params = service.regeo_params(116.4, 39.9, radius=5000)
        assert params["radius"] == 3000

    def test_regeo_params_with_poitype(self, service):
        params = service.regeo_params(116.4, 39.9, poitype="餐饮服务")
        assert params["poitype"] == "餐饮服务"


@pytest.mark.asyncio
class TestGeocode:
    """3.3.x 地理编码"""

    async def test_success(self, service):
        """正常地理编码"""
        service._request_with_retry = AsyncMock(return_value=_geocode_api_response())
        result = await service.geocode("北京市朝阳区阜通东大街6号", "北京")
        assert result.status is True
        assert result.longitude == 116.474488
        assert result.latitude == 39.99557
        assert result.province == "北京市"
        assert result.adcode == "110105"
        assert result.citycode == "010"
        assert result.match_type == "city_name"
        assert result.is_valid() is True
        service._request_with_retry.assert_called_once_with(
            AMAP_GEOCODE_URL,
            {
                "key": "test-key",
                "address": "北京市朝阳区阜通东大街6号",
                "output": "json",
                "city": "北京",
            },
        )

    async def test_api_failure(self, service):
        """高德返回失败状态"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_USER_KEY"}
        )
        result = await service.geocode("天安门")
        assert result.status is False
        assert "INVALID_USER_KEY" in result.info
        assert result.is_valid() is False

    async def test_empty_geocodes(self, service):
        """geocodes 为空"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "1", "info": "OK", "geocodes": []}
        )
        result = await service.geocode("不存在的地址")
        assert result.status is False
        assert "未找到匹配的地址" in result.info

    async def test_malformed_location(self, service):
        """location 字段异常时不崩溃，坐标为 None"""
        service._request_with_retry = AsyncMock(
            return_value=_geocode_api_response(
                geocodes=[{"location": "not-a-location", "province": "北京市"}]
            )
        )
        result = await service.geocode("异常地址")
        assert result.status is True
        assert result.longitude is None
        assert result.latitude is None

    async def test_exception_returns_failure(self, service):
        """请求异常时返回失败结果"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        result = await service.geocode("天安门")
        assert result.status is False
        assert "boom" in result.info

    async def test_timeout_returns_failure(self, service):
        """超时返回失败结果"""
        import httpx

        service._request_with_retry = AsyncMock(side_effect=httpx.TimeoutException("t"))
        result = await service.geocode("天安门")
        assert result.status is False
        assert "请求超时" in result.info

    async def test_http_error_returns_failure(self, service):
        """HTTP 错误返回失败结果"""
        import httpx

        resp = httpx.Response(500, request=httpx.Request("GET", AMAP_GEOCODE_URL))
        service._request_with_retry = AsyncMock(side_effect=httpx.HTTPStatusError("e", request=resp.request, response=resp))
        result = await service.geocode("天安门")
        assert result.status is False
        assert "500" in result.info


@pytest.mark.asyncio
class TestBatchGeocode:
    """批量地理编码"""

    async def test_success(self, service):
        """正常批量"""
        service._request_with_retry = AsyncMock(return_value=_geocode_api_response())
        results = await service.batch_geocode(
            [
                {"address": "天安门", "city": "北京"},
                {"address": "故宫", "city": "北京", "city_match_type": "city_code"},
            ]
        )
        assert len(results) == 2
        assert all(r.status for r in results)

    async def test_empty_address(self, service):
        """空地址直接失败"""
        service.geocode = AsyncMock()
        results = await service.batch_geocode([{"address": ""}])
        assert len(results) == 1
        assert results[0].status is False
        assert "地址为空" in results[0].info
        service.geocode.assert_not_called()


@pytest.mark.asyncio
class TestRegeo:
    """3.3.x 逆地理编码"""

    async def test_success_base(self, service):
        """正常逆地理编码（base）"""
        service._request_with_retry = AsyncMock(return_value=_regeo_api_response())
        result = await service.regeo(116.474488, 39.99557)
        assert result.status is True
        assert result.country == "中国"
        assert result.city == "北京市"
        assert result.district == "朝阳区"
        assert result.township == "望京街道"
        assert result.adcode == "110105"
        assert result.longitude == 116.474488
        assert result.latitude == 39.99557
        assert result.business_areas == [
            {"name": "望京", "location": "116.47,39.99", "id": "110105"}
        ]
        # base 模式不解析 POI
        assert result.pois == []

    async def test_success_all_extracts_pois(self, service):
        """extensions=all 时解析附近 POI"""
        service._request_with_retry = AsyncMock(return_value=_regeo_api_response())
        result = await service.regeo(116.474488, 39.99557, extensions="all")
        assert result.status is True
        assert len(result.pois) == 1
        assert result.pois[0]["name"] == "方恒国际中心"
        assert result.pois[0]["id"] == "B000A123"

    async def test_api_failure(self, service):
        """高德返回失败状态"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "QUOTA_EXHAUSTED"}
        )
        result = await service.regeo(116.4, 39.9)
        assert result.status is False
        assert "QUOTA_EXHAUSTED" in result.info

    async def test_exception_returns_failure(self, service):
        """请求异常时返回失败结果"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        result = await service.regeo(116.4, 39.9)
        assert result.status is False
        assert "boom" in result.info


@pytest.mark.asyncio
class TestBatchRegeo:
    """批量逆地理编码"""

    async def test_success(self, service):
        """正常批量"""
        service._request_with_retry = AsyncMock(return_value=_regeo_api_response())
        results = await service.batch_regeo(
            [{"longitude": 116.4, "latitude": 39.9, "radius": 500}]
        )
        assert len(results) == 1
        assert results[0].status is True

    async def test_missing_coords(self, service):
        """坐标缺失直接失败"""
        service.regeo = AsyncMock()
        results = await service.batch_regeo([{"longitude": 116.4}])
        assert len(results) == 1
        assert results[0].status is False
        assert "坐标参数不完整" in results[0].info
        service.regeo.assert_not_called()


@pytest.mark.asyncio
class TestParseLocation:
    """文本地点解析"""

    async def test_success(self, service):
        """解析成功返回结果"""
        service.geocode = AsyncMock(return_value=GeocodeResult(
            status=True, longitude=116.4, latitude=39.9, info="OK"
        ))
        result = await service.parse_location("天安门", "北京")
        assert result is not None
        assert result.longitude == 116.4

    async def test_failure_returns_none(self, service):
        """解析失败返回 None"""
        service.geocode = AsyncMock(return_value=GeocodeResult(status=False, info="x"))
        result = await service.parse_location("不存在")
        assert result is None


@pytest.mark.asyncio
class TestSearchPois:
    """POI 关键字搜索"""

    async def test_success(self, service):
        """正常搜索"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "1", "pois": [{"id": "B001", "name": "故宫"}]}
        )
        pois = await service.search_pois("故宫", "北京", limit=5)
        assert len(pois) == 1
        assert pois[0]["id"] == "B001"
        _, params = service._request_with_retry.call_args.args
        assert params["keywords"] == "故宫"
        assert params["city"] == "北京"
        assert params["offset"] == 5

    async def test_limit_clamped(self, service):
        """limit 超出范围时被钳制"""
        service._request_with_retry = AsyncMock(return_value={"status": "1", "pois": []})
        await service.search_pois("故宫", limit=100)
        _, params = service._request_with_retry.call_args.args
        assert params["offset"] == 25

    async def test_empty_keyword(self, service):
        """空关键词直接返回空列表"""
        service._request_with_retry = AsyncMock()
        assert await service.search_pois("   ") == []
        service._request_with_retry.assert_not_called()

    async def test_api_failure(self, service):
        """接口失败返回空列表"""
        service._request_with_retry = AsyncMock(
            return_value={"status": "0", "info": "INVALID_KEY"}
        )
        assert await service.search_pois("故宫") == []

    async def test_exception_returns_empty(self, service):
        """异常返回空列表"""
        service._request_with_retry = AsyncMock(side_effect=RuntimeError("boom"))
        assert await service.search_pois("故宫") == []


@pytest.mark.asyncio
class TestGetPoiDetail:
    """POI 详情（v3 优先，v5 回退）"""

    def _detail_v3(self) -> Dict[str, Any]:
        return {
            "status": "1",
            "pois": [{"id": "B001", "photos": [{"url": "https://img.example.com/1.jpg"}]}],
        }

    def _detail_v3_no_photos(self) -> Dict[str, Any]:
        return {"status": "1", "pois": [{"id": "B001", "photos": []}]}

    def _detail_v5(self) -> Dict[str, Any]:
        return {"status": "1", "pois": [{"id": "B001", "photos": [{"url": "https://img.example.com/v5.jpg"}]}]}

    async def test_empty_id(self, service):
        """空 poi_id 返回 None"""
        service._request_with_retry = AsyncMock()
        assert await service.get_poi_detail("") is None
        service._request_with_retry.assert_not_called()

    async def test_v3_success(self, service):
        """v3 有图直接返回"""
        service._request_with_retry = AsyncMock(return_value=self._detail_v3())
        detail = await service.get_poi_detail("B001")
        assert detail is not None
        assert detail["id"] == "B001"

    async def test_v3_no_photos_falls_back_to_v5(self, service):
        """v3 无图回退 v5"""
        service._request_with_retry = AsyncMock(
            side_effect=[self._detail_v3_no_photos(), self._detail_v5()]
        )
        detail = await service.get_poi_detail("B001")
        assert detail is not None
        assert detail["photos"][0]["url"] == "https://img.example.com/v5.jpg"
        urls = [c.args[0] for c in service._request_with_retry.call_args_list]
        assert urls == [AMAP_PLACE_DETAIL_URL_V3, AMAP_PLACE_DETAIL_URL_V5]

    async def test_v3_failure_falls_back_to_v5(self, service):
        """v3 抛异常回退 v5"""
        service._request_with_retry = AsyncMock(
            side_effect=[RuntimeError("v3 down"), self._detail_v5()]
        )
        detail = await service.get_poi_detail("B001")
        assert detail is not None
        assert detail["photos"][0]["url"] == "https://img.example.com/v5.jpg"

    async def test_both_fail_return_none(self, service):
        """v3 无图且 v5 失败返回 None"""
        service._request_with_retry = AsyncMock(
            side_effect=[self._detail_v3_no_photos(), RuntimeError("v5 down")]
        )
        assert await service.get_poi_detail("B001") is None


class TestExtractPhotoUrls:
    """POI 图片 URL 提取（静态方法）"""

    def test_extract(self):
        urls = AmapGeoService.extract_photo_urls(
            {"photos": [{"url": "https://a.com/1.jpg"}, {"url": "http://b.com/2.jpg"}]}
        )
        assert urls == ["https://a.com/1.jpg", "http://b.com/2.jpg"]

    def test_deduplicate(self):
        urls = AmapGeoService.extract_photo_urls(
            {"photos": [{"url": "https://a.com/1.jpg"}, {"url": "https://a.com/1.jpg"}]}
        )
        assert urls == ["https://a.com/1.jpg"]

    def test_limit(self):
        urls = AmapGeoService.extract_photo_urls(
            {"photos": [{"url": f"https://a.com/{i}.jpg"} for i in range(5)]},
            limit=2,
        )
        assert len(urls) == 2

    def test_invalid_urls_skipped(self):
        urls = AmapGeoService.extract_photo_urls(
            {"photos": [{"url": "ftp://a.com/1.jpg"}, {"preurl": "https://b.com/2.jpg"}, "not-dict"]}
        )
        assert urls == ["https://b.com/2.jpg"]

    def test_empty(self):
        assert AmapGeoService.extract_photo_urls({}) == []


@pytest.mark.asyncio
class TestGetPlacePhotos:
    """按地点名称获取图片"""

    async def test_success(self, service):
        """正常获取图片"""
        service.search_pois = AsyncMock(
            return_value=[
                {"id": "B001", "name": "故宫"},
                {"id": "B002", "name": "故宫博物院"},
            ]
        )
        service.get_poi_detail = AsyncMock(
            return_value={"id": "B001", "photos": [{"url": "https://img.example.com/a.jpg"}]}
        )
        urls = await service.get_place_photos("故宫", "北京")
        assert urls == ["https://img.example.com/a.jpg"]
        # 关键词匹配优先选择名称更接近的 POI
        assert service.get_poi_detail.await_args.args == ("B001",)

    async def test_no_pois(self, service):
        """无 POI 返回空列表"""
        service.search_pois = AsyncMock(return_value=[])
        assert await service.get_place_photos("故宫") == []

    async def test_no_detail(self, service):
        """详情缺失返回空列表"""
        service.search_pois = AsyncMock(return_value=[{"id": "B001", "name": "故宫"}])
        service.get_poi_detail = AsyncMock(return_value=None)
        assert await service.get_place_photos("故宫") == []


@pytest.mark.asyncio
class TestSmartGeocode:
    """智能地理编码回退"""

    async def test_city_name_success(self, service):
        """城市名直接成功"""
        service.geocode = AsyncMock(return_value=GeocodeResult(status=True, longitude=116.4, latitude=39.9))
        result = await service.smart_geocode("天安门", "北京")
        assert result.status is True
        service.geocode.assert_called_once_with("天安门", "北京", CityMatchType.CITY_NAME)

    async def test_falls_back_to_adcode(self, service):
        """城市名失败且为 6 位数字时尝试 adcode"""
        service.geocode = AsyncMock(
            side_effect=[
                GeocodeResult(status=False, info="x"),
                GeocodeResult(status=True, longitude=116.4, latitude=39.9),
            ]
        )
        result = await service.smart_geocode("天安门", "110000")
        assert result.status is True
        calls = service.geocode.call_args_list
        assert calls[0].args[2] == CityMatchType.CITY_NAME
        assert calls[1].args[2] == CityMatchType.ADCODE

    async def test_falls_back_to_city_code(self, service):
        """城市名/adcode 失败且为短数字时尝试 citycode"""
        service.geocode = AsyncMock(
            side_effect=[
                GeocodeResult(status=False, info="x"),
                GeocodeResult(status=True, longitude=116.4, latitude=39.9),
            ]
        )
        result = await service.smart_geocode("天安门", "010")
        assert result.status is True
        calls = service.geocode.call_args_list
        assert calls[0].args[2] == CityMatchType.CITY_NAME
        assert calls[1].args[2] == CityMatchType.CITY_CODE

    async def test_falls_back_to_national(self, service):
        """全部失败时回退全国搜索"""
        service.geocode = AsyncMock(
            return_value=GeocodeResult(status=False, info="x")
        )
        result = await service.smart_geocode("天安门", "北京")
        assert result.status is False
        # 全国搜索不带城市参数
        assert service.geocode.call_args.args == ("天安门",)

    async def test_no_preferred_city(self, service):
        """未指定城市直接全国搜索"""
        service.geocode = AsyncMock(return_value=GeocodeResult(status=False, info="x"))
        await service.smart_geocode("天安门")
        service.geocode.assert_called_once_with("天安门")


class TestParseCoordinates:
    """坐标字符串解析"""

    def test_valid(self, service):
        assert service.parse_coordinates("116.397499,39.908722") == (116.397499, 39.908722)

    def test_invalid_format(self, service):
        assert service.parse_coordinates("116.397499") is None
        assert service.parse_coordinates("a,b") is None

    def test_empty(self, service):
        assert service.parse_coordinates("") is None


@pytest.mark.asyncio
class TestExtractCityFromAddress:
    """从地址提取城市"""

    async def test_success(self, service):
        service.geocode = AsyncMock(
            return_value=GeocodeResult(status=True, city="北京市", longitude=116.4, latitude=39.9)
        )
        assert await service.extract_city_from_address("北京市朝阳区") == "北京市"

    async def test_failure_returns_none(self, service):
        service.geocode = AsyncMock(return_value=GeocodeResult(status=False, info="x"))
        assert await service.extract_city_from_address("不存在") is None


@pytest.mark.asyncio
class TestVerifyCoordinates:
    """坐标境内校验"""

    async def test_out_of_china_range(self, service):
        """明显超出中国范围直接失败，不请求网络"""
        service.regeo = AsyncMock()
        assert await service.verify_coordinates(200.0, 200.0) is False
        service.regeo.assert_not_called()

    async def test_in_china(self, service):
        service.regeo = AsyncMock(
            return_value=RegeoResult(status=True, country="中国")
        )
        assert await service.verify_coordinates(116.4, 39.9) is True

    async def test_not_china(self, service):
        service.regeo = AsyncMock(
            return_value=RegeoResult(status=True, country="日本")
        )
        assert await service.verify_coordinates(116.4, 39.9) is False


class TestRequestWithRetry:
    """重试机制"""

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        import httpx

        svc = AmapGeoService(api_key="k", max_retries=3, retry_delay=0, rate_limit_delay=0)
        attempts = {"n": 0}

        async def fake_request(url, params):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise httpx.TimeoutException("transient")
            return {"status": "1"}

        svc._rate_limited_request = fake_request
        result = await svc._request_with_retry("url", {})
        assert result == {"status": "1"}
        assert attempts["n"] == 3

    @pytest.mark.asyncio
    async def test_retries_exhausted_raises(self):
        svc = AmapGeoService(api_key="k", max_retries=2, retry_delay=0, rate_limit_delay=0)

        async def fake_request(url, params):
            raise RuntimeError("always fails")

        svc._rate_limited_request = fake_request
        with pytest.raises(RuntimeError, match="always fails"):
            await svc._request_with_retry("url", {})


class TestSingleton:
    """全局单例"""

    def test_init_and_get(self):
        svc = init_amap_geo_service("new-key", max_retries=1)
        assert svc is get_amap_geo_service()
        assert svc._api_key == "new-key"
        # 重置，避免影响其他测试
        import app.services.amap_geo_service as mod

        mod.amap_geo = None
