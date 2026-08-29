"""
高德地图地理编码服务

基于高德地图 Web API 提供地理编码和逆地理编码功能。
每次请求直接从高德API获取数据，不维护本地注册表。

优化遵循高德地图 JSAPI v2.0 开发技能规范：
- 支持重试机制（指数退避）
- 支持批量处理
- 支持多种城市指定方式（城市名、citycode、adcode）
- 完善的错误处理和日志记录
- 请求限流保护
"""

import httpx
import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

# 配置日志
logger = logging.getLogger(__name__)

# 高德API基础地址
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
AMAP_PLACE_DETAIL_URL_V3 = "https://restapi.amap.com/v3/place/detail"
AMAP_PLACE_DETAIL_URL_V5 = "https://restapi.amap.com/v5/place/detail"


class CityMatchType(Enum):
    """城市指定方式枚举"""
    CITY_NAME = "city_name"      # 城市名称（中文/拼音）
    CITY_CODE = "city_code"       # 城市电话区号
    ADCODE = "adcode"             # 行政区划代码


@dataclass
class GeocodeResult:
    """地理编码结果"""
    status: bool                          # 请求是否成功
    formatted_address: str = ""           # 格式化地址
    province: str = ""                     # 省份
    city: str = ""                         # 城市
    district: str = ""                     # 区/县
    street: str = ""                       # 街道
    street_number: str = ""                # 门牌号
    adcode: str = ""                       # 行政区划代码
    citycode: str = ""                     # 城市代码
    longitude: Optional[float] = None      # 经度
    latitude: Optional[float] = None       # 纬度
    level: str = ""                        # 匹配级别
    info: str = ""                         # 状态信息
    match_type: str = ""                   # 匹配类型

    def is_valid(self) -> bool:
        """检查结果是否有效"""
        return self.status and self.longitude is not None and self.latitude is not None


@dataclass
class RegeoResult:
    """逆地理编码结果"""
    status: bool                          # 请求是否成功
    country: str = ""                     # 国家
    province: str = ""                    # 省份
    city: str = ""                        # 城市
    district: str = ""                    # 区/县
    township: str = ""                    # 乡镇/街道
    street: str = ""                      # 街道
    street_number: str = ""               # 门牌号
    adcode: str = ""                      # 行政区划代码
    citycode: str = ""                    # 城市代码
    formatted_address: str = ""           # 格式化地址
    longitude: Optional[float] = None     # 经度
    latitude: Optional[float] = None      # 纬度
    business_areas: List[Dict[str, Any]] = None  # 商圈信息
    pois: List[Dict[str, Any]] = None     # 附近POI列表
    info: str = ""                        # 状态信息

    def __post_init__(self):
        if self.business_areas is None:
            self.business_areas = []
        if self.pois is None:
            self.pois = []


class AmapGeoService:
    """
    高德地图地理编码服务

    提供地址到坐标、坐标到地址的相互转换功能。
    所有数据直接从高德API获取，支持重试、批量处理和限流保护。

    优化特性：
    - 重试机制：指数退避重试，提高稳定性
    - 批量处理：支持批量地理编码和逆地理编码
    - 多种城市指定方式：支持城市名、citycode、adcode
    - 限流保护：避免触发高德API限流
    - 完善的错误处理和日志记录
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        rate_limit_delay: float = 0.2,
    ):
        """
        初始化服务

        Args:
            api_key: 高德地图 API Key
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒），使用指数退避
            rate_limit_delay: 限流保护延迟（秒），每次请求间隔
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
            url: 请求URL
            params: 请求参数

        Returns:
            API响应数据
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
            url: 请求URL
            params: 请求参数

        Returns:
            API响应数据

        Raises:
            httpx.HTTPStatusError: HTTP错误
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
                        f"请求失败 (尝试 {attempt + 1}/{self._max_retries}): {e}. "
                        f"{delay:.1f}秒后重试..."
                    )
                    await asyncio.sleep(delay)
                continue
            except Exception as e:
                last_error = e
                logger.error(f"请求异常: {e}")
                break

        raise last_error or Exception("请求失败")

    def _build_city_params(
        self,
        city: Optional[str] = None,
        city_match_type: CityMatchType = CityMatchType.CITY_NAME,
    ) -> Dict[str, str]:
        """
        根据匹配类型构建城市参数

        Args:
            city: 城市标识
            city_match_type: 匹配类型

        Returns:
            参数字典
        """
        if not city:
            return {}

        params = {}
        if city_match_type == CityMatchType.CITY_CODE:
            params["city"] = city  # citycode
        elif city_match_type == CityMatchType.ADCODE:
            params["city"] = city  # adcode
        else:
            params["city"] = city  # 城市名或拼音

        return params

    def geocode_params(
        self,
        address: str,
        city: Optional[str] = None,
        city_match_type: CityMatchType = CityMatchType.CITY_NAME,
    ) -> Dict[str, Any]:
        """
        构建地理编码请求参数

        Args:
            address: 地址
            city: 城市
            city_match_type: 城市匹配类型

        Returns:
            请求参数字典
        """
        params = {
            "key": self._api_key,
            "address": address,
            "output": "json",
        }
        params.update(self._build_city_params(city, city_match_type))
        return params

    def regeo_params(
        self,
        longitude: float,
        latitude: float,
        radius: int = 1000,
        extensions: str = "base",
        poitype: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        构建逆地理编码请求参数

        Args:
            longitude: 经度
            latitude: 纬度
            radius: 搜索半径（米）
            extensions: 返回结果控制
            poitype: POI类型

        Returns:
            请求参数字典
        """
        params = {
            "key": self._api_key,
            "location": f"{longitude},{latitude}",
            "radius": min(radius, 3000),
            "extensions": extensions,
            "output": "json",
        }
        if poitype:
            params["poitype"] = poitype
        return params

    async def geocode(
        self,
        address: str,
        city: Optional[str] = None,
        city_match_type: CityMatchType = CityMatchType.CITY_NAME,
    ) -> GeocodeResult:
        """
        地理编码：将地址转换为经纬度坐标

        Args:
            address: 结构化地址（如：北京市朝阳区阜通东大街6号）
            city: 指定查询的城市（可选）
                - 城市名（中文/拼音）：如 "北京"、"Beijing"
                - citycode：如 "010"
                - adcode：如 "110000"
            city_match_type: 城市匹配类型，默认按城市名匹配

        Returns:
            GeocodeResult: 地理编码结果
        """
        params = self.geocode_params(address, city, city_match_type)

        try:
            data = await self._request_with_retry(AMAP_GEOCODE_URL, params)

            if data.get("status") != "1":
                return GeocodeResult(
                    status=False,
                    info=data.get("info", "请求失败"),
                )

            geocodes = data.get("geocodes", [])
            if not geocodes:
                return GeocodeResult(
                    status=False,
                    info="未找到匹配的地址",
                )

            geo = geocodes[0]
            location = geo.get("location", "").split(",")
            longitude = float(location[0]) if len(location) == 2 else None
            latitude = float(location[1]) if len(location) == 2 else None

            return GeocodeResult(
                status=True,
                formatted_address=address,
                province=geo.get("province", ""),
                city=geo.get("city", ""),
                district=geo.get("district", ""),
                street=geo.get("street", ""),
                street_number=geo.get("number", ""),
                adcode=geo.get("adcode", ""),
                citycode=geo.get("citycode", ""),
                longitude=longitude,
                latitude=latitude,
                level=geo.get("level", ""),
                info="OK",
                match_type=city_match_type.value if city else "",
            )

        except httpx.TimeoutException:
            return GeocodeResult(status=False, info="请求超时")
        except httpx.HTTPStatusError as e:
            return GeocodeResult(status=False, info=f"HTTP错误: {e.response.status_code}")
        except Exception as e:
            return GeocodeResult(status=False, info=f"请求异常: {str(e)}")

    async def batch_geocode(
        self,
        addresses: List[Dict[str, Any]],
    ) -> List[GeocodeResult]:
        """
        批量地理编码：将多个地址转换为经纬度坐标

        Args:
            addresses: 地址列表，每个元素包含：
                - address: 地址字符串（必填）
                - city: 城市（可选）
                - city_match_type: 城市匹配类型（可选）

        Returns:
            List[GeocodeResult]: 地理编码结果列表
        """
        results = []
        for item in addresses:
            address = item.get("address")
            if not address:
                results.append(GeocodeResult(status=False, info="地址为空"))
                continue

            city = item.get("city")
            city_match = item.get(
                "city_match_type",
                CityMatchType.CITY_NAME,
            )
            if isinstance(city_match, str):
                city_match = CityMatchType(city_match)

            result = await self.geocode(address, city, city_match)
            results.append(result)

        return results

    async def regeo(
        self,
        longitude: float,
        latitude: float,
        radius: int = 1000,
        extensions: str = "base",
        poitype: Optional[str] = None,
    ) -> RegeoResult:
        """
        逆地理编码：将经纬度坐标转换为详细地址

        Args:
            longitude: 经度
            latitude: 纬度
            radius: 搜索半径（米），默认1000，最大3000
            extensions: 返回结果控制，"base"或"all"
            poitype: POI类型过滤（需要extensions=all）

        Returns:
            RegeoResult: 逆地理编码结果
        """
        params = self.regeo_params(longitude, latitude, radius, extensions, poitype)

        try:
            data = await self._request_with_retry(AMAP_REGEO_URL, params)

            if data.get("status") != "1":
                return RegeoResult(
                    status=False,
                    info=data.get("info", "请求失败"),
                )

            regeocode = data.get("regeocode", {})
            address_component = regeocode.get("addressComponent", {})
            street_number = address_component.get("streetNumber", {})
            business_areas = address_component.get("businessAreas", [])

            # 提取商圈信息
            business_area_list = []
            if isinstance(business_areas, list):
                for area in business_areas:
                    if isinstance(area, dict):
                        business_area_list.append({
                            "name": area.get("name", ""),
                            "location": area.get("location", ""),
                            "id": area.get("id", ""),
                        })

            # 提取POI信息（当extensions=all时）
            poi_list = []
            if extensions == "all":
                pois_data = regeocode.get("pois", [])
                for poi in pois_data:
                    if isinstance(poi, dict):
                        poi_list.append({
                            "id": poi.get("id", ""),
                            "name": poi.get("name", ""),
                            "type": poi.get("type", ""),
                            "address": poi.get("address", ""),
                            "location": poi.get("location", ""),
                            "distance": poi.get("distance", ""),
                            "business_area": poi.get("businessarea", ""),
                        })

            return RegeoResult(
                status=True,
                country=address_component.get("country", ""),
                province=address_component.get("province", ""),
                city=address_component.get("city", ""),
                district=address_component.get("district", ""),
                township=address_component.get("township", ""),
                street=street_number.get("street", ""),
                street_number=street_number.get("number", ""),
                adcode=address_component.get("adcode", ""),
                citycode=address_component.get("citycode", ""),
                formatted_address=regeocode.get("formatted_address", ""),
                longitude=longitude,
                latitude=latitude,
                business_areas=business_area_list,
                pois=poi_list,
                info="OK",
            )

        except httpx.TimeoutException:
            return RegeoResult(status=False, info="请求超时")
        except httpx.HTTPStatusError as e:
            return RegeoResult(status=False, info=f"HTTP错误: {e.response.status_code}")
        except Exception as e:
            return RegeoResult(status=False, info=f"请求异常: {str(e)}")

    async def batch_regeo(
        self,
        locations: List[Dict[str, Any]],
    ) -> List[RegeoResult]:
        """
        批量逆地理编码：将多个坐标转换为详细地址

        Args:
            locations: 坐标列表，每个元素包含：
                - longitude: 经度（必填）
                - latitude: 纬度（必填）
                - radius: 搜索半径（可选，默认1000）
                - extensions: 返回类型（可选，默认"base"）
                - poitype: POI类型（可选）

        Returns:
            List[RegeoResult]: 逆地理编码结果列表
        """
        results = []
        for item in locations:
            longitude = item.get("longitude")
            latitude = item.get("latitude")
            if longitude is None or latitude is None:
                results.append(RegeoResult(status=False, info="坐标参数不完整"))
                continue

            radius = item.get("radius", 1000)
            extensions = item.get("extensions", "base")
            poitype = item.get("poitype")

            result = await self.regeo(
                longitude, latitude, radius, extensions, poitype
            )
            results.append(result)

        return results

    async def parse_location(
        self,
        text: str,
        city: Optional[str] = None,
        city_match_type: CityMatchType = CityMatchType.CITY_NAME,
    ) -> Optional[GeocodeResult]:
        """
        解析文本描述的地点，返回地理编码结果

        适用场景：
        - "北京"
        - "杭州西湖"
        - "天安门广场"

        Args:
            text: 地点文本描述
            city: 限定城市（可选，提高匹配准确性）
            city_match_type: 城市匹配类型

        Returns:
            GeocodeResult 或 None（解析失败时）
        """
        result = await self.geocode(text, city, city_match_type)
        return result if result.status else None

    async def search_pois(
        self,
        keyword: str,
        city: Optional[str] = None,
        *,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """按关键词搜索 POI，供详情图片补全使用。"""
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        params: Dict[str, Any] = {
            "key": self._api_key,
            "keywords": keyword,
            "offset": min(max(1, limit), 25),
            "page": 1,
            "extensions": "base",
            "output": "json",
        }
        if city:
            params["city"] = city

        try:
            data = await self._request_with_retry(AMAP_PLACE_TEXT_URL, params)
        except Exception as e:
            logger.warning(f"POI搜索失败 [{keyword}]: {e}")
            return []

        if data.get("status") != "1":
            logger.warning(f"POI搜索失败 [{keyword}]: {data.get('info', '未知错误')}")
            return []
        return data.get("pois") or []

    async def get_poi_detail(self, poi_id: str) -> Optional[Dict[str, Any]]:
        """获取 POI 详情。先试 v3，未取到图片时回退 v5。"""
        poi_id = (poi_id or "").strip()
        if not poi_id:
            return None

        v3_params = {"key": self._api_key, "id": poi_id, "output": "json"}
        try:
            data = await self._request_with_retry(AMAP_PLACE_DETAIL_URL_V3, v3_params)
            if data.get("status") == "1" and data.get("pois"):
                detail = data["pois"][0]
                if detail.get("photos"):
                    return detail
        except Exception as e:
            logger.debug(f"POI详情v3失败 [{poi_id}]: {e}")

        v5_params = {"key": self._api_key, "id": poi_id}
        try:
            data = await self._request_with_retry(AMAP_PLACE_DETAIL_URL_V5, v5_params)
        except Exception as e:
            logger.warning(f"POI详情v5失败 [{poi_id}]: {e}")
            return None

        if data.get("status") == "1" and data.get("pois"):
            return data["pois"][0]
        return None

    @staticmethod
    def extract_photo_urls(poi: Dict[str, Any], *, limit: int = 3) -> List[str]:
        """从高德 POI 详情 photos 字段提取可展示图片 URL。"""
        urls: List[str] = []
        seen: set[str] = set()
        for photo in poi.get("photos") or []:
            if not isinstance(photo, dict):
                continue
            url = (photo.get("url") or photo.get("preurl") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    async def get_place_photos(
        self,
        keyword: str,
        city: Optional[str] = None,
        *,
        limit: int = 3,
    ) -> List[str]:
        """按地点名称获取 POI 图片 URL 列表。"""
        pois = await self.search_pois(keyword, city, limit=5)
        if not pois:
            return []

        best = pois[0]
        for poi in pois:
            name = str(poi.get("name") or "")
            if name and (name == keyword or keyword in name or name in keyword):
                best = poi
                break

        detail = await self.get_poi_detail(str(best.get("id") or ""))
        if not detail:
            return []
        return self.extract_photo_urls(detail, limit=limit)

    async def smart_geocode(
        self,
        address: str,
        preferred_city: Optional[str] = None,
    ) -> GeocodeResult:
        """
        智能地理编码：自动尝试多种城市指定方式

        如果首选城市指定失败，会回退到全国范围搜索

        Args:
            address: 地址
            preferred_city: 首选城市

        Returns:
            GeocodeResult: 地理编码结果
        """
        # 如果指定了城市，优先使用城市限定
        if preferred_city:
            result = await self.geocode(
                address,
                preferred_city,
                CityMatchType.CITY_NAME,
            )
            if result.status:
                return result

            # 尝试使用 adcode
            if len(preferred_city) == 6 and preferred_city.isdigit():
                result = await self.geocode(
                    address,
                    preferred_city,
                    CityMatchType.ADCODE,
                )
                if result.status:
                    return result

            # 尝试使用 citycode
            if len(preferred_city) <= 4 and preferred_city.isdigit():
                result = await self.geocode(
                    address,
                    preferred_city,
                    CityMatchType.CITY_CODE,
                )
                if result.status:
                    return result

        # 回退到全国范围搜索
        return await self.geocode(address)

    def parse_coordinates(self, location_str: str) -> Optional[tuple[float, float]]:
        """
        从字符串解析经纬度坐标

        Args:
            location_str: 坐标字符串，如 "116.397499,39.908722"

        Returns:
            (longitude, latitude) 元组或 None
        """
        try:
            parts = location_str.split(",")
            if len(parts) != 2:
                return None
            return float(parts[0]), float(parts[1])
        except (ValueError, AttributeError):
            return None

    async def extract_city_from_address(self, address: str) -> Optional[str]:
        """
        从地址中提取城市信息

        Args:
            address: 地址字符串

        Returns:
            城市名或 None
        """
        result = await self.geocode(address)
        if result.status and result.city:
            return result.city
        return None

    async def verify_coordinates(
        self,
        longitude: float,
        latitude: float,
    ) -> bool:
        """
        验证坐标是否在中国境内

        Args:
            longitude: 经度
            latitude: 纬度

        Returns:
            是否在中国境内
        """
        # 中国大致范围
        if not (73.0 <= longitude <= 135.0 and 18.0 <= latitude <= 54.0):
            return False

        result = await self.regeo(longitude, latitude)
        return result.status and result.country == "中国"


# 全局单例（需要初始化时设置api_key）
amap_geo: Optional[AmapGeoService] = None


def init_amap_geo_service(
    api_key: str,
    timeout: float = 10.0,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    rate_limit_delay: float = 0.2,
) -> AmapGeoService:
    """
    初始化全局高德地理编码服务

    Args:
        api_key: 高德地图 API Key
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        rate_limit_delay: 限流保护延迟（秒）

    Returns:
        初始化后的 AmapGeoService 实例
    """
    global amap_geo
    amap_geo = AmapGeoService(
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        rate_limit_delay=rate_limit_delay,
    )
    return amap_geo


def get_amap_geo_service() -> Optional[AmapGeoService]:
    """获取全局高德地理编码服务实例"""
    return amap_geo
