"""
高德地图地理编码服务

基于高德地图 Web API 提供地理编码和逆地理编码功能。
每次请求直接从高德API获取数据，不维护本地注册表。
"""

import httpx
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


# 高德API基础地址
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"


@dataclass
class GeocodeResult:
    """地理编码结果"""
    status: bool                          # 请求是否成功
    formatted_address: str = ""          # 格式化地址
    province: str = ""                    # 省份
    city: str = ""                        # 城市
    district: str = ""                    # 区/县
    street: str = ""                      # 街道
    street_number: str = ""               # 门牌号
    adcode: str = ""                      # 行政区划代码
    citycode: str = ""                    # 城市代码
    longitude: Optional[float] = None     # 经度
    latitude: Optional[float] = None      # 纬度
    level: str = ""                       # 匹配级别
    info: str = ""                        # 状态信息


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
    所有数据直接从高德API获取，不维护本地缓存。
    """

    def __init__(self, api_key: str, timeout: float = 10.0):
        """
        初始化服务

        Args:
            api_key: 高德地图 API Key
            timeout: 请求超时时间（秒）
        """
        self._api_key = api_key
        self._timeout = timeout

    async def geocode(self, address: str, city: Optional[str] = None) -> GeocodeResult:
        """
        地理编码：将地址转换为经纬度坐标

        Args:
            address: 结构化地址（如：北京市朝阳区阜通东大街6号）
            city: 指定查询的城市（可选，支持中文城市名、拼音、citycode、adcode）

        Returns:
            GeocodeResult: 地理编码结果
        """
        params = {
            "key": self._api_key,
            "address": address,
            "output": "json",
        }
        if city:
            params["city"] = city

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(AMAP_GEOCODE_URL, params=params)
                response.raise_for_status()
                data = response.json()

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
                )

        except httpx.TimeoutException:
            return GeocodeResult(status=False, info="请求超时")
        except httpx.HTTPStatusError as e:
            return GeocodeResult(status=False, info=f"HTTP错误: {e.response.status_code}")
        except Exception as e:
            return GeocodeResult(status=False, info=f"请求异常: {str(e)}")

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
        params = {
            "key": self._api_key,
            "location": f"{longitude},{latitude}",
            "radius": min(radius, 3000),
            "extensions": extensions,
            "output": "json",
        }
        if poitype:
            params["poitype"] = poitype

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(AMAP_REGEO_URL, params=params)
                response.raise_for_status()
                data = response.json()

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

    async def parse_location(self, text: str) -> Optional[GeocodeResult]:
        """
        解析文本描述的地点，返回地理编码结果

        适用场景：
        - "北京"
        - "杭州西湖"
        - "天安门广场"

        Args:
            text: 地点文本描述

        Returns:
            GeocodeResult 或 None（解析失败时）
        """
        return await self.geocode(address=text)

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


# 全局单例（需要初始化时设置api_key）
amap_geo: Optional[AmapGeoService] = None


def init_amap_geo_service(api_key: str, timeout: float = 10.0) -> AmapGeoService:
    """
    初始化全局高德地理编码服务

    Args:
        api_key: 高德地图 API Key
        timeout: 请求超时时间（秒）

    Returns:
        初始化后的 AmapGeoService 实例
    """
    global amap_geo
    amap_geo = AmapGeoService(api_key=api_key, timeout=timeout)
    return amap_geo


def get_amap_geo_service() -> Optional[AmapGeoService]:
    """获取全局高德地理编码服务实例"""
    return amap_geo
