"""
智旅云图 - 天气 API 路由（Phase 7.3）

职责：HTTP 入口，仅调用 weather_service，不承载业务。

分层定位（与 trip_service 内的天气懒初始化对齐）：
    - 校验：Path/Query 参数（days 由 Query 夹在 1-4，mode 用 Literal 自动 422）
    - 编排：懒初始化 weather_service 单例，调用 get_live_weather / get_forecast
    - 错误：天气服务不可用 → 503；城市查无数据 → 200 + 空结构（天气是补充信息，
            不阻断主流程）

设计要点：
    - 路由函数声明为 async def：weather_service 的 get_live_weather / get_forecast /
      get_city_adcode 均为 async 接口，直接 await。
    - router 不携带 prefix，由 main.py include 时统一加 /weather，前缀归入口统一管理。
    - 复用 trip_service._get_weather_service 的懒初始化模式：get_weather_service()
      为空则 init_weather_service(api_key=settings.AMAP_API_KEY)。
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import WeatherInfo
from app.services.weather_service import (
    WeatherService,
    get_weather_service,
    init_weather_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class CityWeatherResponse(BaseModel):
    """城市天气响应模型（实时 + 预报组装结构）"""

    city: str = Field(..., description="城市名或adcode")
    adcode: Optional[str] = Field(default=None, description="行政区编码")
    live: Optional[WeatherInfo] = Field(default=None, description="实时天气")
    forecast: List[WeatherInfo] = Field(
        default_factory=list, description="未来 N 天预报"
    )


_weather_svc: Optional[WeatherService] = None


def _get_weather_svc() -> Optional[WeatherService]:
    """懒初始化天气服务（复用 trip_service._get_weather_service 的模式）。"""
    global _weather_svc
    if _weather_svc is not None:
        return _weather_svc
    svc = get_weather_service()
    if svc is None:
        try:
            svc = init_weather_service(api_key=settings.AMAP_API_KEY)
        except Exception as e:
            logger.warning(f"weather_service 初始化失败: {e}")
            svc = None
    _weather_svc = svc
    return svc


@router.get("/{city}", response_model=CityWeatherResponse, status_code=200)
async def get_weather(
    city: str = Path(..., description="城市名或adcode（如“北京”或“110000”）"),
    days: int = Query(3, ge=1, le=4, description="预报天数（1-4，高德上限4天）"),
    mode: Literal["live", "forecast", "both"] = Query(
        "both", description="返回内容：live=实时 / forecast=预报 / both=两者"
    ),
) -> CityWeatherResponse:
    """获取指定城市的实时天气与/或未来天气预报。"""
    svc = _get_weather_svc()
    if svc is None:
        raise HTTPException(status_code=503, detail="天气服务不可用")

    live: Optional[WeatherInfo] = None
    forecast: List[WeatherInfo] = []
    adcode: Optional[str] = None

    if mode in ("both", "live"):
        live = await svc.get_live_weather(city)
        adcode = await svc.get_city_adcode(city)
    if mode in ("both", "forecast"):
        forecast = await svc.get_forecast(city, days=days)

    return CityWeatherResponse(
        city=city,
        adcode=adcode,
        live=live,
        forecast=forecast,
    )
