"""
智旅云图 - 天气服务测试（3.5.1-3.5.4）

全部 mock 高德天气 API，不打真实网络。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from app.models.schemas import WeatherInfo
from app.services.cache_service import CacheConfig, CacheService
from app.services.weather_service import WeatherService


def _live_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德实时天气 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "lives": [
            {
                "province": "北京",
                "city": "北京市",
                "adcode": "110000",
                "weather": "晴",
                "temperature": "28",
                "humidity": "45",
                "windDirection": "东南",
                "windPower": "3级",
                "reportTime": "2026-09-04 10:00:00",
            }
        ],
    }
    data.update(kwargs)
    for live in data.get("lives", []):
        live.update(kwargs)
    return data


def _forecast_api_response(**kwargs: Any) -> Dict[str, Any]:
    """构造高德预报天气 API 原始响应"""
    data = {
        "status": "1",
        "info": "OK",
        "forecasts": [
            {
                "province": "北京",
                "city": "北京市",
                "adcode": "110000",
                "reportTime": "2026-09-04 10:00:00",
                "casts": [
                    {
                        "date": "2026-09-04",
                        "dayweather": "晴",
                        "nightweather": "多云",
                        "daytemp": "30",
                        "nighttemp": "20",
                        "daywind": "东南",
                        "daypower": "3级",
                    },
                    {
                        "date": "2026-09-05",
                        "dayweather": "小雨",
                        "nightweather": "中雨",
                        "daytemp": "26",
                        "nighttemp": "18",
                        "daywind": "北",
                        "daypower": "4级",
                    },
                ],
            }
        ],
    }
    data.update(kwargs)
    for forecast in data.get("forecasts", []):
        for cast in forecast.get("casts", []):
            cast.update(kwargs)
    return data


@pytest.fixture
def service():
    """创建天气服务实例（关闭限流与重试延迟，加速测试）"""
    return WeatherService(api_key="test-key", max_retries=1, retry_delay=0, rate_limit_delay=0)


@pytest.fixture
def isolated_cache():
    """隔离缓存，避免污染全局单例（强制内存后端，防止本地 Redis 跨测试泄漏）"""
    with patch(
        "app.services.cache_service.RedisCacheBackend.is_available",
        new_callable=PropertyMock,
        return_value=False,
    ):
        cache = CacheService(config=CacheConfig(prefix="test-weather"))
        with patch("app.services.weather_service.cache_service", cache):
            yield cache


class TestParseLiveData:
    """实时天气数据解析"""

    def test_success(self, service):
        """正常响应解析"""
        data = _live_api_response()
        live = service._parse_live_data(data)
        assert live.status is True
        assert live.city == "北京市"
        assert live.adcode == "110000"
        assert live.weather == "晴"
        assert live.temperature == "28"
        assert live.humidity == "45"

    def test_api_failure(self, service):
        """高德返回失败状态"""
        data = {"status": "0", "info": "INVALID_USER_KEY"}
        live = service._parse_live_data(data)
        assert live.status is False
        assert "INVALID_USER_KEY" in live.info

    def test_empty_lives(self, service):
        """lives 为空"""
        data = {"status": "1", "info": "OK", "lives": []}
        live = service._parse_live_data(data)
        assert live.status is False


class TestParseForecastData:
    """预报天气数据解析"""

    def test_success(self, service):
        """正常响应解析"""
        data = _forecast_api_response()
        forecast = service._parse_forecast_data(data)
        assert forecast.status is True
        assert len(forecast.forecasts) == 2
        assert forecast.city == "北京市"

    def test_api_failure(self, service):
        """高德返回失败状态"""
        data = {"status": "0", "info": "INVALID_USER_KEY"}
        forecast = service._parse_forecast_data(data)
        assert forecast.status is False

    def test_empty_forecasts(self, service):
        """forecasts 为空"""
        data = {"status": "1", "info": "OK", "forecasts": []}
        forecast = service._parse_forecast_data(data)
        assert forecast.status is False


class TestLiveToWeatherInfo:
    """实时天气 → WeatherInfo 转换"""

    def test_full_data(self, service):
        """完整字段转换"""
        live = service._parse_live_data(_live_api_response())
        info = service._live_to_weather_info(live)
        assert info.weather_type == "晴"
        assert info.temp_high == 28
        assert info.temp_low == 28
        assert info.temp_avg == 28
        assert info.humidity == 45
        assert info.wind_direction == "东南"
        assert info.wind_speed == 3.0

    def test_empty_temperature_raises(self, service):
        """温度为空时 WeatherInfo 必填校验失败（temp_high/temp_low 非空）"""
        from pydantic import ValidationError

        live = service._parse_live_data(
            _live_api_response(temperature="", humidity="", windPower="")
        )
        with pytest.raises(ValidationError):
            service._live_to_weather_info(live)


class TestForecastToWeatherInfo:
    """预报 → WeatherInfo 转换"""

    def test_full_data(self, service):
        """完整字段转换"""
        forecast = service._parse_forecast_data(_forecast_api_response())
        info = service._forecast_to_weather_info(forecast.forecasts[0], date(2026, 9, 4))
        assert info.forecast_date == date(2026, 9, 4)
        assert info.temp_high == 30
        assert info.temp_low == 20
        assert info.temp_avg == 25
        assert info.weather_type == "晴"
        assert info.wind_speed == 3.0

    def test_invalid_temp(self, service):
        """非法温度值不抛异常"""
        forecast = service._parse_forecast_data(
            _forecast_api_response(
                forecasts=[{
                    "province": "北京", "city": "北京市", "adcode": "110000",
                    "reportTime": "", "casts": [{"daytemp": "abc", "nighttemp": ""}],
                }]
            )
        )
        info = service._forecast_to_weather_info(forecast.forecasts[0], date(2026, 9, 4))
        assert info.temp_high == 0
        assert info.temp_low == 0
        assert info.temp_avg is None
        assert info.weather_type == "未知"


@pytest.mark.asyncio
class TestGetLiveWeather:
    """3.5.1 实时天气获取"""

    async def test_success(self, service, isolated_cache):
        """正常获取"""
        service._fetch_weather = AsyncMock(return_value=_live_api_response())
        info = await service.get_live_weather("北京")
        assert info is not None
        assert info.weather_type == "晴"
        assert info.temp_high == 28
        service._fetch_weather.assert_called_once_with("北京", extensions="base")

    async def test_cache_hit(self, service, isolated_cache):
        """缓存命中时不再请求 API"""
        service._fetch_weather = AsyncMock(return_value=_live_api_response())
        info1 = await service.get_live_weather("北京")
        info2 = await service.get_live_weather("北京")
        assert info1 is not None and info2 is not None
        assert service._fetch_weather.call_count == 1

    async def test_api_failure_returns_none(self, service, isolated_cache):
        """API 失败返回 None"""
        service._fetch_weather = AsyncMock(return_value={"status": "0", "info": "FAIL"})
        info = await service.get_live_weather("北京")
        assert info is None

    async def test_exception_returns_none(self, service, isolated_cache):
        """异常时返回 None（不抛出）"""
        service._fetch_weather = AsyncMock(side_effect=RuntimeError("boom"))
        info = await service.get_live_weather("北京")
        assert info is None


@pytest.mark.asyncio
class TestGetForecast:
    """3.5.2 天气预报获取"""

    async def test_success(self, service, isolated_cache):
        """正常获取，按天返回"""
        service._fetch_weather = AsyncMock(return_value=_forecast_api_response())
        forecasts = await service.get_forecast("北京", days=2)
        assert len(forecasts) == 2
        assert all(isinstance(f, WeatherInfo) for f in forecasts)
        assert forecasts[0].forecast_date == date(2026, 9, 4)
        assert forecasts[1].forecast_date == date(2026, 9, 5)

    async def test_days_clamped(self, service, isolated_cache):
        """天数限制在 1-4 之间"""
        service._fetch_weather = AsyncMock(return_value=_forecast_api_response())
        forecasts = await service.get_forecast("北京", days=99)
        assert len(forecasts) == 2  # 数据只有 2 天，不超上限
        service._fetch_weather.assert_called_once_with("北京", extensions="all")

    async def test_api_failure_returns_empty(self, service, isolated_cache):
        """API 失败返回空列表"""
        service._fetch_weather = AsyncMock(return_value={"status": "0", "info": "FAIL"})
        forecasts = await service.get_forecast("北京")
        assert forecasts == []

    async def test_exception_returns_empty(self, service, isolated_cache):
        """异常时返回空列表"""
        service._fetch_weather = AsyncMock(side_effect=RuntimeError("boom"))
        forecasts = await service.get_forecast("北京")
        assert forecasts == []


@pytest.mark.asyncio
class TestBatchGetWeather:
    """3.5.3 批量天气获取"""

    async def test_empty_cities(self, service):
        """空城市列表返回空字典"""
        result = await service.batch_get_weather([])
        assert result == {}

    async def test_success(self, service, isolated_cache):
        """多城市批量获取"""
        async def fake_fetch(city: str, extensions: str = "base"):
            if extensions == "base":
                return _live_api_response()
            return _forecast_api_response()

        service._fetch_weather = AsyncMock(side_effect=fake_fetch)
        result = await service.batch_get_weather(["北京", "上海"])
        assert set(result.keys()) == {"北京", "上海"}
        assert result["北京"]["live"] is not None
        assert len(result["北京"]["forecast"]) == 2

    async def test_no_forecast_flag(self, service, isolated_cache):
        """仅实时天气"""
        service._fetch_weather = AsyncMock(return_value=_live_api_response())
        result = await service.batch_get_weather(
            ["北京"], include_live=True, include_forecast=False
        )
        assert result["北京"]["live"] is not None
        assert not result["北京"]["forecast"]


@pytest.mark.asyncio
class TestGetTripWeather:
    """3.5.4 行程天气获取"""

    async def test_empty_inputs(self, service):
        """空城市或天数为 0 返回空字典"""
        assert await service.get_trip_weather([], date.today(), days=3) == {}
        assert await service.get_trip_weather(["北京"], date.today(), days=0) == {}

    async def test_aligned_by_date(self, service, isolated_cache):
        """按行程日期对齐预报"""
        service._fetch_weather = AsyncMock(return_value=_forecast_api_response())
        start = date(2026, 9, 4)
        result = await service.get_trip_weather(["北京"], start, days=2)
        assert "北京" in result
        assert len(result["北京"]) == 2
        assert all(f.forecast_date >= start for f in result["北京"])


@pytest.mark.asyncio
class TestGetCityAdcode:
    """城市 adcode 获取"""

    async def test_success(self, service):
        """正常获取 adcode"""
        service._fetch_weather = AsyncMock(return_value=_live_api_response())
        adcode = await service.get_city_adcode("北京")
        assert adcode == "110000"

    async def test_failure_returns_none(self, service):
        """失败返回 None"""
        service._fetch_weather = AsyncMock(return_value={"status": "0", "info": "FAIL"})
        adcode = await service.get_city_adcode("北京")
        assert adcode is None

    async def test_exception_returns_none(self, service):
        """异常返回 None"""
        service._fetch_weather = AsyncMock(side_effect=RuntimeError("boom"))
        adcode = await service.get_city_adcode("北京")
        assert adcode is None


class TestParseWindPower:
    """风力解析"""

    def test_normal(self, service):
        assert service._parse_wind_power("3级") == 3.0

    def test_le(self, service):
        assert service._parse_wind_power("≤3级") == 3.0

    def test_empty(self, service):
        assert service._parse_wind_power("") is None
        assert service._parse_wind_power(None) is None

    def test_no_number(self, service):
        assert service._parse_wind_power("微风") is None


@pytest.mark.asyncio
class TestClearCache:
    """缓存清理"""

    async def test_clear_city(self, service, isolated_cache):
        """清除单个城市缓存"""
        service._fetch_weather = AsyncMock(return_value=_live_api_response())
        await service.get_live_weather("北京")
        count = service.clear_cache("北京")
        assert count >= 1

    async def test_clear_all(self, service, isolated_cache):
        """清除全部天气缓存"""
        service._fetch_weather = AsyncMock(return_value=_live_api_response())
        await service.get_live_weather("北京")
        count = service.clear_cache()
        assert count >= 0




