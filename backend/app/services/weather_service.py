"""
高德地图天气服务

基于高德地图 Web API 提供实时天气和天气预报功能。

功能模块：
- 3.5.1 实时天气：获取指定城市的实时天气信息
- 3.5.2 天气预报：获取指定城市未来天气预报
- 3.5.3 批量天气：批量获取多城市天气信息
- 3.5.4 行程天气：获取行程期间各城市的天气预报

优化特性：
- 缓存策略：实时天气 30 分钟，预报天气 6 小时
- 重试机制：指数退避重试
- 限流保护：避免触发高德 API 限流
- 批量处理：支持并发请求
"""

import httpx
import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timedelta

from ..models.schemas import WeatherInfo
from .cache_service import cache_service, CacheStrategy, CacheNamespace

# 配置日志
logger = logging.getLogger(__name__)

# 高德天气 API 基础地址
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"

# 缓存 TTL 设置（秒）
WEATHER_LIVE_TTL = 1800      # 实时天气：30 分钟
WEATHER_FORECAST_TTL = 21600 # 预报天气：6 小时

# 限流设置
RATE_LIMIT_DELAY = 0.2       # 请求间隔（秒）


@dataclass
class WeatherLiveData:
    """实时天气数据（高德 API 原始格式）"""
    status: bool
    info: str = ""
    province: str = ""
    city: str = ""
    adcode: str = ""
    weather: str = ""
    temperature: str = ""
    humidity: str = ""
    wind_direction: str = ""
    wind_power: str = ""
    report_time: str = ""


@dataclass
class WeatherForecastData:
    """天气预报数据（高德 API 原始格式）"""
    status: bool
    info: str = ""
    province: str = ""
    city: str = ""
    adcode: str = ""
    report_time: str = ""
    forecasts: List[Dict[str, Any]] = field(default_factory=list)


class WeatherService:
    """
    高德地图天气服务

    提供实时天气和天气预报查询功能，数据来自高德地图天气 API。

    使用示例：
        service = WeatherService(api_key="your_api_key")
        weather = await service.get_live_weather("北京")
        forecasts = await service.get_forecast("北京", days=3)
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        rate_limit_delay: float = RATE_LIMIT_DELAY,
    ):
        """
        初始化服务

        Args:
            api_key: 高德地图 API Key
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒），使用指数退避
            rate_limit_delay: 限流保护延迟（秒）
        """
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: float = 0

    async def _rate_limited_request(
        self,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        带限流保护的请求方法

        Args:
            url: 请求 URL
            params: 请求参数

        Returns:
            API 响应数据
        """
        current_time = time.time()
        elapsed = current_time - self._last_request_time
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _request_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        带重试机制的请求方法（指数退避）

        Args:
            url: 请求 URL
            params: 请求参数

        Returns:
            API 响应数据

        Raises:
            httpx.HTTPStatusError: HTTP 错误
            Exception: 重试次数耗尽
        """
        last_error = None
        for attempt in range(self._max_retries):
            try:
                return await self._rate_limited_request(url, params)
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay * (2 ** attempt)
                    logger.warning(
                        f"天气 API 请求失败 (尝试 {attempt + 1}/{self._max_retries}): {e}. "
                        f"{delay:.1f}秒后重试..."
                    )
                    await asyncio.sleep(delay)
                continue
            except Exception as e:
                last_error = e
                logger.error(f"天气 API 请求异常: {e}")
                break

        raise last_error or Exception("天气 API 请求失败")

    async def _fetch_weather(
        self,
        city: str,
        extensions: str = "base",
    ) -> Dict[str, Any]:
        """
        调用高德天气 API

        Args:
            city: 城市名或 adcode
            extensions: 天气类型，"base" 返回实时天气，"all" 返回实时天气 + 预报

        Returns:
            API 响应数据
        """
        params = {
            "key": self._api_key,
            "city": city,
            "extensions": extensions,
            "output": "json",
        }
        return await self._request_with_retry(AMAP_WEATHER_URL, params)

    def _parse_live_data(self, data: Dict[str, Any]) -> WeatherLiveData:
        """
        解析实时天气数据

        Args:
            data: API 原始响应

        Returns:
            WeatherLiveData
        """
        if data.get("status") != "1":
            return WeatherLiveData(
                status=False,
                info=data.get("info", "请求失败"),
            )

        live_data = data.get("lives", [])
        if not live_data:
            return WeatherLiveData(
                status=False,
                info="未找到实时天气数据",
            )

        live = live_data[0]
        return WeatherLiveData(
            status=True,
            info="OK",
            province=live.get("province", ""),
            city=live.get("city", ""),
            adcode=live.get("adcode", ""),
            weather=live.get("weather", ""),
            temperature=live.get("temperature", ""),
            humidity=live.get("humidity", ""),
            wind_direction=live.get("windDirection", ""),
            wind_power=live.get("windPower", ""),
            report_time=live.get("reportTime", ""),
        )

    def _parse_forecast_data(self, data: Dict[str, Any]) -> WeatherForecastData:
        """
        解析天气预报数据

        Args:
            data: API 原始响应

        Returns:
            WeatherForecastData
        """
        if data.get("status") != "1":
            return WeatherForecastData(
                status=False,
                info=data.get("info", "请求失败"),
            )

        forecasts = data.get("forecasts", [])
        if not forecasts:
            return WeatherForecastData(
                status=False,
                info="未找到预报数据",
            )

        forecast_data = forecasts[0]
        return WeatherForecastData(
            status=True,
            info="OK",
            province=forecast_data.get("province", ""),
            city=forecast_data.get("city", ""),
            adcode=forecast_data.get("adcode", ""),
            report_time=forecast_data.get("reportTime", ""),
            forecasts=forecast_data.get("casts", []),
        )

    def _live_to_weather_info(
        self,
        live: WeatherLiveData,
        forecast_date: Optional[date_type] = None,
    ) -> WeatherInfo:
        """
        将实时天气数据转换为 WeatherInfo 模型

        Args:
            live: 实时天气数据
            forecast_date: 预报日期（可选）

        Returns:
            WeatherInfo
        """
        temp_str = live.temperature.strip("℃") if live.temperature else None
        temp_avg = int(temp_str) if temp_str and temp_str.isdigit() else None

        return WeatherInfo(
            forecast_date=forecast_date or date_type.today(),
            temp_high=temp_avg,
            temp_low=temp_avg,
            temp_avg=temp_avg,
            weather_type=live.weather,
            humidity=int(live.humidity) if live.humidity.isdigit() else None,
            wind_direction=live.wind_direction,
            wind_speed=self._parse_wind_power(live.wind_power),
        )

    def _forecast_to_weather_info(
        self,
        forecast: Dict[str, Any],
        forecast_date: date_type,
    ) -> WeatherInfo:
        """
        将预报数据转换为 WeatherInfo 模型

        Args:
            forecast: 预报数据字典
            forecast_date: 预报日期

        Returns:
            WeatherInfo
        """
        # 高德天气 API 预报字段为全小写：daytemp/nighttemp/dayweather/nightweather/daywind/daypower
        day_temp_str = forecast.get("daytemp", "")
        night_temp_str = forecast.get("nighttemp", "")

        try:
            temp_high = int(day_temp_str) if day_temp_str else None
        except (ValueError, TypeError):
            temp_high = None

        try:
            temp_low = int(night_temp_str) if night_temp_str else None
        except (ValueError, TypeError):
            temp_low = None

        temp_avg = (
            (temp_high + temp_low) // 2
            if temp_high is not None and temp_low is not None
            else None
        )

        day_weather = forecast.get("dayweather", "")
        night_weather = forecast.get("nightweather", "")
        weather_type = day_weather if day_weather else night_weather

        day_wind_dir = forecast.get("daywind", "")
        day_wind_power = forecast.get("daypower", "")

        # 优先使用 API 返回的真实日期（预报从当天起）
        raw_date = forecast.get("date", "")
        if raw_date:
            try:
                forecast_date = date_type.fromisoformat(str(raw_date))
            except (ValueError, TypeError):
                pass

        return WeatherInfo(
            forecast_date=forecast_date,
            temp_high=temp_high or 0,
            temp_low=temp_low or 0,
            temp_avg=temp_avg,
            weather_type=weather_type or "未知",
            wind_direction=day_wind_dir or None,
            wind_speed=self._parse_wind_power(day_wind_power),
        )

    def _parse_wind_power(self, wind_power: str) -> Optional[float]:
        """
        解析风力等级

        Args:
            wind_power: 风力字符串，如 "3级" 或 "≤3级"

        Returns:
            风力数值或 None
        """
        if not wind_power:
            return None

        import re
        match = re.search(r"\d+", wind_power)
        if match:
            return float(match.group())
        return None

    async def get_live_weather(
        self,
        city: str,
        use_cache: bool = True,
    ) -> Optional[WeatherInfo]:
        """
        3.5.1 获取实时天气

        获取指定城市的实时天气信息，包含温度、湿度、风向、风力等。

        Args:
            city: 城市名（如"北京"）或 adcode（如"110000"）
            use_cache: 是否使用缓存

        Returns:
            WeatherInfo 或 None（请求失败时）
        """
        cache_key = f"live:{city}"

        if use_cache:
            cached = cache_service.get(
                cache_key,
                namespace=CacheNamespace.WEATHER,
            )
            if cached:
                logger.debug(f"实时天气缓存命中: {city}")
                return cached

        try:
            data = await self._fetch_weather(city, extensions="base")
            live = self._parse_live_data(data)

            if not live.status:
                logger.warning(f"实时天气获取失败 [{city}]: {live.info}")
                return None

            weather_info = self._live_to_weather_info(live)

            if use_cache:
                cache_service.set(
                    cache_key,
                    weather_info.model_dump(),
                    namespace=CacheNamespace.WEATHER,
                    strategy=CacheStrategy.MEDIUM_TERM,
                )

            logger.info(
                f"实时天气获取成功 [{city}]: {live.weather} {live.temperature}℃"
            )
            return weather_info

        except Exception as e:
            logger.error(f"实时天气获取异常 [{city}]: {e}")
            return None

    async def get_forecast(
        self,
        city: str,
        days: int = 3,
        use_cache: bool = True,
    ) -> List[WeatherInfo]:
        """
        3.5.2 获取天气预报

        获取指定城市未来天气预报，包含每天的最高温度、最低温度、天气状况等。

        Args:
            city: 城市名（如"北京"）或 adcode（如"110000"）
            days: 预报天数，默认 3 天（高德支持 1-4 天）
            use_cache: 是否使用缓存

        Returns:
            List[WeatherInfo]，每天的天气信息列表
        """
        days = min(max(1, days), 4)
        cache_key = f"forecast:{city}:{days}"

        if use_cache:
            cached = cache_service.get(
                cache_key,
                namespace=CacheNamespace.WEATHER,
            )
            if cached:
                logger.debug(f"天气预报缓存命中: {city}")
                return [WeatherInfo(**item) for item in cached]

        try:
            data = await self._fetch_weather(city, extensions="all")
            forecast_data = self._parse_forecast_data(data)

            if not forecast_data.status:
                logger.warning(f"天气预报获取失败 [{city}]: {forecast_data.info}")
                return []

            forecasts = []
            base_date = date_type.today()

            for i, fc in enumerate(forecast_data.forecasts[:days]):
                fc_date = base_date + timedelta(days=i)
                weather_info = self._forecast_to_weather_info(fc, fc_date)
                forecasts.append(weather_info)

            if use_cache:
                cache_service.set(
                    cache_key,
                    [item.model_dump() for item in forecasts],
                    namespace=CacheNamespace.WEATHER,
                    strategy=CacheStrategy.LONG_TERM,
                )

            logger.info(f"天气预报获取成功 [{city}]: {len(forecasts)} 天")
            return forecasts

        except Exception as e:
            logger.error(f"天气预报获取异常 [{city}]: {e}")
            return []

    async def batch_get_weather(
        self,
        cities: List[str],
        include_live: bool = True,
        include_forecast: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """
        3.5.3 批量获取多城市天气

        批量获取多个城市的天气信息，支持并发请求。

        Args:
            cities: 城市列表
            include_live: 是否包含实时天气
            include_forecast: 是否包含预报天气

        Returns:
            Dict[str, Dict]，每个城市对应其天气数据：
            {
                "北京": {"live": WeatherInfo, "forecast": List[WeatherInfo]},
                "上海": {"live": WeatherInfo, "forecast": List[WeatherInfo]},
            }
        """
        if not cities:
            return {}

        tasks = []

        for city in cities:
            if include_live:
                tasks.append(self._batch_live_task(city))
            else:
                tasks.append(self._batch_none_task(city, "live"))

            if include_forecast:
                tasks.append(self._batch_forecast_task(city))
            else:
                tasks.append(self._batch_none_task(city, "forecast"))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        weather_map: Dict[str, Dict[str, Any]] = {
            city: {"live": None, "forecast": []}
            for city in cities
        }

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"批量天气请求异常: {result}")
                continue

            city = result.get("city")
            if city not in weather_map:
                continue

            if "live" in result:
                weather_map[city]["live"] = result["live"]
            if "forecast" in result:
                weather_map[city]["forecast"] = result["forecast"]

        return weather_map

    async def _batch_none_task(self, city: str, key: str) -> Dict[str, Any]:
        """批量任务：未启用项的占位结果（替代已移除的 asyncio.coroutine）。"""
        return {"city": city, key: None}

    async def _batch_live_task(self, city: str) -> Dict[str, Any]:
        """批量任务：获取实时天气"""
        return {
            "city": city,
            "live": await self.get_live_weather(city),
        }

    async def _batch_forecast_task(self, city: str) -> Dict[str, Any]:
        """批量任务：获取天气预报（拉满 4 天，覆盖当天 + 未来 3 天）"""
        return {
            "city": city,
            "forecast": await self.get_forecast(city, days=4),
        }

    async def get_trip_weather(
        self,
        cities: List[str],
        start_date: date_type,
        days: int = 3,
    ) -> Dict[str, List[WeatherInfo]]:
        """
        3.5.4 获取行程天气

        获取行程期间各城市的天气预报，按日期和城市组织。

        Args:
            cities: 行程中的城市列表
            start_date: 行程开始日期
            days: 行程天数

        Returns:
            Dict[str, List[WeatherInfo]]，每个城市的天气预报列表：
            {
                "北京": [WeatherInfo(day1), WeatherInfo(day2), WeatherInfo(day3)],
                "大理": [WeatherInfo(day1), WeatherInfo(day2), WeatherInfo(day3)],
            }
        """
        if not cities or days <= 0:
            return {}

        city_forecasts = await self.batch_get_weather(
            cities,
            include_live=False,
            include_forecast=True,
        )

        result: Dict[str, List[WeatherInfo]] = {}
        end_date = start_date + timedelta(days=days)

        for city, data in city_forecasts.items():
            forecasts = data.get("forecast", []) or []
            # 按行程日期对齐：只保留 [start_date, end_date) 区间内的预报
            aligned = [
                f for f in forecasts
                if f.forecast_date and start_date <= f.forecast_date < end_date
            ]
            result[city] = aligned[:days] if aligned else forecasts[:days]

        logger.info(f"行程天气获取完成: {len(result)} 个城市")
        return result

    async def get_city_adcode(self, city: str) -> Optional[str]:
        """
        获取城市的 adcode

        用于将城市名转换为 adcode，以便更精确地查询天气。

        Args:
            city: 城市名

        Returns:
            adcode 字符串或 None
        """
        try:
            data = await self._fetch_weather(city, extensions="base")
            if data.get("status") == "1":
                lives = data.get("lives", [])
                if lives:
                    return lives[0].get("adcode")
        except Exception as e:
            logger.warning(f"获取城市 adcode 失败 [{city}]: {e}")
        return None

    def clear_cache(self, city: Optional[str] = None) -> int:
        """
        清除天气缓存

        Args:
            city: 城市名，为 None 时清除所有天气缓存

        Returns:
            删除的缓存条目数
        """
        if city:
            count = 0
            count += 1 if cache_service.delete(f"live:{city}", CacheNamespace.WEATHER) else 0
            for d in range(1, 5):
                count += 1 if cache_service.delete(f"forecast:{city}:{d}", CacheNamespace.WEATHER) else 0
            logger.info(f"天气缓存已清除 [{city}]: {count} 条")
            return count
        else:
            count = cache_service.clear_namespace(CacheNamespace.WEATHER)
            logger.info(f"所有天气缓存已清除: {count} 条")
            return count


# 全局单例（需要初始化时设置 api_key）
weather_service: Optional[WeatherService] = None


def init_weather_service(
    api_key: str,
    timeout: float = 10.0,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    rate_limit_delay: float = RATE_LIMIT_DELAY,
) -> WeatherService:
    """
    初始化全局天气服务

    Args:
        api_key: 高德地图 API Key
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        rate_limit_delay: 限流保护延迟（秒）

    Returns:
        初始化后的 WeatherService 实例
    """
    global weather_service
    weather_service = WeatherService(
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        rate_limit_delay=rate_limit_delay,
    )
    logger.info("天气服务初始化成功")
    return weather_service


def get_weather_service() -> Optional[WeatherService]:
    """获取全局天气服务实例"""
    return weather_service


# 便捷函数
async def get_live_weather(
    city: str,
    use_cache: bool = True,
) -> Optional[WeatherInfo]:
    """
    获取实时天气（全局服务）

    Args:
        city: 城市名或 adcode
        use_cache: 是否使用缓存

    Returns:
        WeatherInfo 或 None
    """
    if not weather_service:
        raise RuntimeError("天气服务未初始化，请先调用 init_weather_service()")
    return await weather_service.get_live_weather(city, use_cache)


async def get_forecast(
    city: str,
    days: int = 3,
    use_cache: bool = True,
) -> List[WeatherInfo]:
    """
    获取天气预报（全局服务）

    Args:
        city: 城市名或 adcode
        days: 预报天数
        use_cache: 是否使用缓存

    Returns:
        List[WeatherInfo]
    """
    if not weather_service:
        raise RuntimeError("天气服务未初始化，请先调用 init_weather_service()")
    return await weather_service.get_forecast(city, days, use_cache)


async def batch_get_weather(
    cities: List[str],
    include_live: bool = True,
    include_forecast: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """
    批量获取多城市天气（全局服务）

    Args:
        cities: 城市列表
        include_live: 是否包含实时天气
        include_forecast: 是否包含预报天气

    Returns:
        Dict[str, Dict[str, Any]]
    """
    if not weather_service:
        raise RuntimeError("天气服务未初始化，请先调用 init_weather_service()")
    return await weather_service.batch_get_weather(cities, include_live, include_forecast)


async def get_trip_weather(
    cities: List[str],
    start_date: date_type,
    days: int = 3,
) -> Dict[str, List[WeatherInfo]]:
    """
    获取行程天气（全局服务）

    Args:
        cities: 行程中的城市列表
        start_date: 行程开始日期
        days: 行程天数

    Returns:
        Dict[str, List[WeatherInfo]]
    """
    if not weather_service:
        raise RuntimeError("天气服务未初始化，请先调用 init_weather_service()")
    return await weather_service.get_trip_weather(cities, start_date, days)
