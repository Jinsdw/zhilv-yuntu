"""
智旅云图 - 行程服务编排（Phase 6.1）

职责：
    把 Agent 输出的"坐标占位"行程草案，串联地图/天气/存储/缓存，
    产出可对外发布的完整 TripResponse。

分层定位：
    - Agent 层（Phase 5, LangGraph）：LLM + RAG → 占位坐标的草案
    - 服务层（Phase 3）：地图/天气/存储/POI候选池/缓存等原子能力
    - 编排层（本文件）：串联 + enrichment + token 统计 + 持久化
    - API 层（Phase 7）：HTTP 入口，仅调用本服务

主流程 generate_trip:
    入参校验 → 缓存命中 → 城市分级 → Agent.plan →
    地图补全(geocode) → 天气补全 → 预算二次校正 → token 回填 → 持久化 → 返回

设计原则：
    - 失败不阻断主流程：地图/天气/缓存失败均记入 metadata["enrich_warnings"]
    - 分层职责清晰：Agent 不堆异步 IO，编排层负责补全真实坐标/天气
    - 沉淀城市走 RAG 工具；动态城市先拉 POI 候选池再喂给 Agent
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from datetime import date as date_type, datetime
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from pydantic import BaseModel

from app.agents.llm_factory import build_json_llm
from app.agents.trip_planner_agent import TripPlannerAgent, trip_planner_agent
from langchain_core.messages import HumanMessage
from app.config import settings
from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    TripRequest,
    TripResponse,
    WeatherInfo,
)
from app.services.amap_geo_service import (
    AmapGeoService,
    CityMatchType,
    GeocodeResult,
    get_amap_geo_service,
    init_amap_geo_service,
)
from app.services.cache_service import CacheNamespace, cache_service
from app.services.place_candidate_service import (
    CandidatePool,
    PlaceCandidateService,
    place_candidate_service,
)
from app.services.storage_service import storage_service
from app.services.weather_service import get_weather_service, init_weather_service

from app.rag.guide_catalog import guide_catalog


# ============================================================================
# 常量
# ============================================================================

# 沉淀城市白名单（A级）：由 guide_catalog 扫描 data/*_guide.md 动态生成
# 6.2 迁移完成：城市信息单一事实来源为 app.rag.guide_catalog
PRESET_CITIES: frozenset[str] = guide_catalog.list_preset_cities()

PLACEHOLDER_ADDRESS = "待地图服务补全"
PLACEHOLDER_COORD = Coordinate(latitude=0.0, longitude=0.0)

# 缓存 TTL（秒）
TRIP_CACHE_TTL = 3600


# ============================================================================
# 工具函数
# ============================================================================

def _normalize_destination(dest: str) -> str:
    """把用户输入的目的地归一化到沉淀城市标准名（或原样返回）。

    6.2 迁移：别名/关键词归一化交给 LLM，此处仅做白名单校验 + 轻量匹配。
    """
    if not dest:
        return dest
    resolved = guide_catalog.resolve_city(dest)
    return resolved if resolved else dest.strip()


def is_preset_city(destination: str) -> bool:
    """判断是否为沉淀城市（A 级，走 RAG 检索）。"""
    return guide_catalog.is_preset_city(destination)


def _run_async(coro):
    """
    在同步上下文中跑 async 方法。
    若已在事件循环中（如 FastAPI async 路由直接调用本服务的同步方法），
    退到独立线程跑 asyncio.run，避免阻塞主循环。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


def _strip_json_fence(text: str) -> str:
    """去掉 LLM 输出可能包裹的 ```json ... ``` 代码围栏。"""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


# ============================================================================
# 异常
# ============================================================================

class TripServiceError(Exception):
    """编排服务通用错误"""


class CityNotSupportedError(TripServiceError):
    """城市不支持（C 级，如省级目的地）"""


class TripNotFoundError(TripServiceError):
    """行程不存在"""


# ============================================================================
# TripService
# ============================================================================

class TripService:
    """
    行程编排服务：Agent → 地图 → 天气 → 持久化。

    注入点（单测可替换为 mock）：
        agent / amap_geo / place_service / weather / storage / cache
    """

    def __init__(
        self,
        *,
        agent: Optional[TripPlannerAgent] = None,
        amap_geo: Optional[AmapGeoService] = None,
        place_service: Optional[PlaceCandidateService] = None,
        weather: Any = None,
        storage: Any = None,
        cache: Any = None,
        llm: Any = None,
    ):
        self._agent = agent or trip_planner_agent
        self._amap_geo = amap_geo
        self._place_service = place_service or place_candidate_service
        self._weather = weather
        self._storage = storage or storage_service
        self._cache = cache or cache_service
        self._llm = llm

    # ------------------------------------------------------------------
    # 服务懒加载（避免启动期失败 / 循环导入）
    # ------------------------------------------------------------------

    def _get_amap_geo(self) -> Optional[AmapGeoService]:
        if self._amap_geo is not None:
            return self._amap_geo
        svc = get_amap_geo_service()
        if svc is None:
            try:
                svc = init_amap_geo_service(api_key=settings.AMAP_API_KEY)
            except Exception as e:
                logger.warning(f"amap_geo 初始化失败: {e}")
        self._amap_geo = svc
        return svc

    def _get_weather_service(self):
        if self._weather is not None:
            return self._weather
        svc = get_weather_service()
        if svc is None:
            try:
                svc = init_weather_service(api_key=settings.AMAP_API_KEY)
            except Exception as e:
                logger.warning(f"weather_service 初始化失败: {e}")
        self._weather = svc
        return svc

    # ================================================================
    # 6.1.2 + 6.1.3 主编排流程
    # ================================================================

    def generate_trip(
        self,
        request: TripRequest,
        *,
        user_id: Optional[str] = None,
        use_cache: bool = True,
    ) -> TripResponse:
        """
        生成行程：Agent 产出草案 → 地图补全 → 天气补全 → token 统计 → 持久化。

        Args:
            request: 行程请求
            user_id: 可选用户ID
            use_cache: 是否启用缓存命中（默认 True）

        Returns:
            TripResponse，已补全地图/天气，并已写库
        """
        started_at = time.time()

        # 1. 城市归一化（"北京市" → "北京"）
        dest = _normalize_destination(request.destination)
        request = request.model_copy(update={"destination": dest})

        # 2. 缓存命中检查
        cache_key = self._trip_cache_key(request, user_id)
        if use_cache:
            cached = self._safe_cache_get(cache_key)
            if cached is not None:
                try:
                    trip = TripResponse.model_validate(cached)
                    trip = trip.model_copy(update={
                        "metadata": {
                            **(trip.metadata or {}),
                            "cache_hit": True,
                        }
                    })
                    logger.info(f"行程缓存命中: {cache_key}")
                    return trip
                except Exception as e:
                    logger.warning(f"缓存反序列化失败，重新生成: {e}")

        # 3. Agent 调用（包裹 token callback）
        token_usage: Dict[str, Any] = {}
        callback_cm = self._make_token_callback()
        if callback_cm is not None:
            with callback_cm as cb:
                trip = self._invoke_agent(request)
            token_usage = self._extract_token_usage(cb)
        else:
            trip = self._invoke_agent(request)

        # 4. 地图补全（仅 geocode）
        enrich_warnings: List[str] = []
        trip = self._enrich_map(trip, request, enrich_warnings)

        # 5. 天气补全
        trip = self._enrich_weather(trip, request, enrich_warnings)

        # 5.1 天气出行建议（大模型基于天气生成两条简短建议）
        trip = self._enrich_weather_suggestions(trip, enrich_warnings)

        # 6. 预算二次校正（基于补全后的真实门票）
        trip = self._recalculate_budget(trip, request)

        # 7. 元数据回填（token / warnings / 耗时）
        meta = dict(trip.metadata or {})
        if token_usage:
            meta["token_usage"] = token_usage
        if enrich_warnings:
            meta["enrich_warnings"] = enrich_warnings
        meta["generation_time"] = round(time.time() - started_at, 3)
        meta["needs_enrichment"] = False
        meta["preset_city"] = is_preset_city(dest)
        trip = trip.model_copy(update={"metadata": meta})

        # 8. 持久化
        try:
            trip_id = self._storage.create_trip(request, trip, user_id=user_id)
            trip = trip.model_copy(update={"trip_id": trip_id})
            logger.info(f"行程已保存: {trip_id}")
        except Exception as e:
            logger.error(f"行程持久化失败: {e}")
            # 持久化失败不阻断返回

        # 9. 缓存写入
        if use_cache:
            self._safe_cache_set(cache_key, trip)

        return trip

    # ------------------------------------------------------------------
    # Agent 调用：根据城市分级走不同分支
    # ------------------------------------------------------------------

    def _invoke_agent(self, request: TripRequest) -> TripResponse:
        """
        根据城市分级调用 TripPlannerAgent.plan：

        - 沉淀城市：Agent 走 RAG 工具调用模式（use_tools=True）
        - 动态城市：先拉 POI 候选池喂给 Agent（use_tools=False）
                    POI 拉取失败则降级回 RAG 路径
        """
        dest = request.destination

        if is_preset_city(dest):
            logger.info(f"沉淀城市 [{dest}]：Agent 走 RAG 工具")
            return self._agent.plan(
                request,
                use_tools=True,
                allow_fallback=True,
            )

        # 动态城市：先拉 POI 候选池
        logger.info(f"动态城市 [{dest}]：先拉 POI 候选池")
        try:
            pool = self._place_service.build_pool_sync(request)
            items = PlaceCandidateService.to_prompt_items(pool)
            if not items:
                logger.warning(f"动态城市 [{dest}] 候选池为空，退回 RAG 路径")
                return self._agent.plan(request, use_tools=True, allow_fallback=True)
        except Exception as e:
            logger.warning(f"POI 候选池构建失败: {e}，退回 RAG 路径")
            return self._agent.plan(request, use_tools=True, allow_fallback=True)

        return self._agent.plan(
            request,
            candidate_places=items,
            use_tools=False,
            allow_fallback=True,
        )

    # ------------------------------------------------------------------
    # 地图补全（仅 geocode）
    # ------------------------------------------------------------------

    def _enrich_map(
        self,
        trip: TripResponse,
        request: TripRequest,
        warnings: List[str],
    ) -> TripResponse:
        """
        对每个 PlaceInfo 调 geocode 补全坐标/地址/行政区。
        失败保留占位符，记入 warnings。
        """
        amap = self._get_amap_geo()
        if amap is None:
            warnings.append("amap_geo 服务不可用，地图未补全")
            return trip

        city = trip.destination
        new_days: List[ItineraryDay] = []
        photo_cache: Dict[str, List[str]] = {}
        for day in trip.days:
            new_items: List[ItineraryItem] = []
            for item in day.items:
                new_place = self._geocode_place(
                    item.place, city, amap, warnings, day.day_number
                )
                new_place = self._enrich_place_photos(
                    new_place, city, amap, warnings, f"第{day.day_number}天", photo_cache
                )
                new_items.append(item.model_copy(update={"place": new_place}))
            new_day = day.model_copy(update={"items": new_items})
            new_day = self._enrich_day_meals_hotel(
                new_day, city, amap, warnings, photo_cache
            )
            new_days.append(new_day)

        return trip.model_copy(update={"days": new_days})

    def _geocode_place(
        self,
        place: PlaceInfo,
        city: str,
        amap: AmapGeoService,
        warnings: List[str],
        day_number: int,
    ) -> PlaceInfo:
        """对单个 PlaceInfo 调 geocode。已有真实坐标/地址则跳过。"""
        # 已是真实坐标则跳过
        if place.coordinate.latitude != 0.0 or place.coordinate.longitude != 0.0:
            return place
        # 已有真实地址则跳过
        if place.address and place.address != PLACEHOLDER_ADDRESS:
            return place

        query = f"{place.name}({city})" if city else place.name
        try:
            result = _run_async(amap.geocode(query, city=city))
        except Exception as e:
            warnings.append(
                f"第{day_number}天 [{place.name}] geocode 调用失败: {e}"
            )
            return place

        if result is None or not result.is_valid():
            warnings.append(f"第{day_number}天 [{place.name}] geocode 无结果")
            return place

        coord = Coordinate(
            latitude=float(result.latitude),
            longitude=float(result.longitude),
        )
        # 高德返回的 formatted_address 实际是入参 address，用 province+city+district 拼一个更完整的
        better_addr = self._compose_address(result) or place.address
        return place.model_copy(update={
            "coordinate": coord,
            "address": better_addr,
            "district": result.district or place.district,
        })

    def _enrich_place_photos(
        self,
        place: PlaceInfo,
        city: str,
        amap: AmapGeoService,
        warnings: List[str],
        context: str,
        photo_cache: Dict[str, List[str]],
    ) -> PlaceInfo:
        """用高德 POI 详情 photos 给地点补图片。失败不影响主流程。"""
        if place.cover_image or place.images:
            return place

        get_photos = getattr(amap, "get_place_photos", None)
        if not callable(get_photos) or not inspect.iscoroutinefunction(get_photos):
            return place

        try:
            photos = self._get_cached_photos(
                place.name, city, get_photos, photo_cache
            )
        except Exception as e:
            warnings.append(f"{context} [{place.name}] 图片补全失败: {e}")
            return place

        photos = [url for url in (photos or []) if isinstance(url, str) and url]
        if not photos:
            return place
        return place.model_copy(update={"images": photos, "cover_image": photos[0]})

    @staticmethod
    def _compose_address(result: GeocodeResult) -> Optional[str]:
        """用高德返回的省/市/区/街道拼一个完整地址。"""
        parts = [result.province, result.city, result.district, result.street]
        parts = [p for p in parts if p]
        if not parts:
            return None
        addr = "".join(parts)
        if result.street_number:
            addr += result.street_number
        return addr or None

    def _enrich_day_meals_hotel(
        self,
        day: ItineraryDay,
        city: str,
        amap: AmapGeoService,
        warnings: List[str],
        photo_cache: Dict[str, List[str]],
    ) -> ItineraryDay:
        """对 day 的餐饮/酒店做 geocode 补全。"""
        updates: Dict[str, Any] = {}

        for meal_field in ("breakfast", "lunch", "dinner"):
            meal = getattr(day, meal_field, None)
            if meal is None:
                continue
            if meal.coordinate.latitude != 0.0:
                enriched_meal = self._enrich_named_entity_photos(
                    meal, city, amap, warnings, f"第{day.day_number}天餐", photo_cache
                )
                if enriched_meal is not meal:
                    updates[meal_field] = enriched_meal
                continue
            query = f"{meal.name}({city})" if city else meal.name
            try:
                result = _run_async(amap.geocode(query, city=city))
            except Exception as e:
                warnings.append(
                    f"第{day.day_number}天餐 [{meal.name}] geocode 失败: {e}"
                )
                continue
            if result is None or not result.is_valid():
                continue
            updated_meal = meal.model_copy(update={
                "coordinate": Coordinate(
                    latitude=float(result.latitude),
                    longitude=float(result.longitude),
                ),
                "address": self._compose_address(result) or meal.address,
            })
            updated_meal = self._enrich_named_entity_photos(
                updated_meal, city, amap, warnings, f"第{day.day_number}天餐", photo_cache
            )
            updates[meal_field] = updated_meal

        # 酒店
        if day.hotel and day.hotel.coordinate.latitude == 0.0:
            query = f"{day.hotel.name}({city})" if city else day.hotel.name
            try:
                result = _run_async(amap.geocode(query, city=city))
            except Exception as e:
                warnings.append(
                    f"第{day.day_number}天酒店 [{day.hotel.name}] geocode 失败: {e}"
                )
                result = None
            if result is not None and result.is_valid():
                updated_hotel = day.hotel.model_copy(update={
                    "coordinate": Coordinate(
                        latitude=float(result.latitude),
                        longitude=float(result.longitude),
                    ),
                    "address": self._compose_address(result) or day.hotel.address,
                })
                updated_hotel = self._enrich_named_entity_photos(
                    updated_hotel, city, amap, warnings, f"第{day.day_number}天酒店", photo_cache
                )
                updates["hotel"] = updated_hotel
        elif day.hotel:
            updated_hotel = self._enrich_named_entity_photos(
                day.hotel, city, amap, warnings, f"第{day.day_number}天酒店", photo_cache
            )
            if updated_hotel is not day.hotel:
                updates["hotel"] = updated_hotel

        if updates:
            return day.model_copy(update=updates)
        return day

    def _enrich_named_entity_photos(
        self,
        entity: Any,
        city: str,
        amap: AmapGeoService,
        warnings: List[str],
        context: str,
        photo_cache: Dict[str, List[str]],
    ) -> Any:
        """给餐厅/酒店等带 name/images 的模型补图片。"""
        if getattr(entity, "cover_image", None) or getattr(entity, "images", None):
            return entity

        get_photos = getattr(amap, "get_place_photos", None)
        if not callable(get_photos) or not inspect.iscoroutinefunction(get_photos):
            return entity

        name = getattr(entity, "name", "")
        try:
            photos = self._get_cached_photos(name, city, get_photos, photo_cache)
        except Exception as e:
            warnings.append(f"{context} [{name}] 图片补全失败: {e}")
            return entity

        photos = [url for url in (photos or []) if isinstance(url, str) and url]
        if not photos:
            return entity

        updates: Dict[str, Any] = {"images": photos}
        if hasattr(entity, "cover_image"):
            updates["cover_image"] = photos[0]
        return entity.model_copy(update=updates)

    @staticmethod
    def _get_cached_photos(
        name: str,
        city: str,
        get_photos: Any,
        photo_cache: Dict[str, List[str]],
    ) -> List[str]:
        """同一次行程补全过程中复用相同地点的图片查询结果。"""
        key = f"{city}|{name}"
        if key not in photo_cache:
            photo_cache[key] = _run_async(get_photos(name, city=city, limit=3)) or []
        return photo_cache[key]

    # ------------------------------------------------------------------
    # 天气补全
    # ------------------------------------------------------------------

    def _enrich_weather(
        self,
        trip: TripResponse,
        request: TripRequest,
        warnings: List[str],
    ) -> TripResponse:
        """调 weather_service.get_trip_weather 给每天补 WeatherInfo。"""
        weather_svc = self._get_weather_service()
        if weather_svc is None:
            warnings.append("weather_service 不可用，天气未补全")
            return trip

        try:
            city_weather_map: Dict[str, List[WeatherInfo]] = _run_async(
                weather_svc.get_trip_weather(
                    [trip.destination],
                    request.start_date,
                    trip.total_days,
                )
            )
        except Exception as e:
            warnings.append(f"天气查询失败: {e}")
            return trip

        forecasts = city_weather_map.get(trip.destination) or []
        if not forecasts:
            warnings.append(f"未获取到 [{trip.destination}] 的天气预报")
            return trip

        # 按 itinerary_date 匹配，匹配不到则按 day_number 兜底
        forecast_by_date: Dict[date_type, WeatherInfo] = {
            f.forecast_date: f for f in forecasts if f.forecast_date
        }

        new_days: List[ItineraryDay] = []
        for day in trip.days:
            w = forecast_by_date.get(day.itinerary_date)
            if w is None and 0 <= day.day_number - 1 < len(forecasts):
                w = forecasts[day.day_number - 1]
            new_days.append(day.model_copy(update={"weather": w}))

        return trip.model_copy(update={"days": new_days})

    def _enrich_weather_suggestions(
        self,
        trip: TripResponse,
        warnings: List[str],
    ) -> TripResponse:
        """基于天气预报调用大模型，生成两条简短出行建议。"""
        days_with_weather = [d for d in trip.days if d.weather]
        if not days_with_weather:
            return trip

        summary_lines: List[str] = []
        for d in days_with_weather:
            w = d.weather
            wind = (
                f"{w.wind_direction or ''}"
                f"{(' ' + str(w.wind_speed)) if w.wind_speed else ''}"
            ).strip() or "未知"
            summary_lines.append(
                f"{d.itinerary_date.isoformat()}：{w.weather_type}，"
                f"{w.temp_low}~{w.temp_high}°C，风力{wind}"
            )
        summary = "\n".join(summary_lines)

        prompt = (
            f"你是资深旅行顾问。请根据以下「{trip.destination}」的天气预报，"
            f"给出两条简短实用的出行建议（每条不超过25字，聚焦天气应对，"
            f"如携带雨具、防晒、添衣保暖、调整游览时段等）。\n\n"
            f"行程日期：{trip.start_date.isoformat()} 至 {trip.end_date.isoformat()}\n"
            f"天气预报：\n{summary}\n\n"
            f'只返回 JSON，格式：{{"suggestions": ["建议一", "建议二"]}}'
        )

        try:
            llm = self._llm or build_json_llm(temperature=0.3, max_tokens=256)
            resp = llm.invoke([HumanMessage(content=prompt)])
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            data = json.loads(_strip_json_fence(content))
            raw = data.get("suggestions", [])
            suggestions = [
                s.strip() for s in raw
                if isinstance(s, str) and s.strip()
            ][:2]
        except Exception as e:
            logger.warning(f"天气出行建议生成失败: {e}")
            warnings.append(f"天气出行建议生成失败: {e}")
            suggestions = []

        return trip.model_copy(update={"weather_suggestions": suggestions})

    # ------------------------------------------------------------------
    # 预算二次校正
    # ------------------------------------------------------------------

    def _recalculate_budget(
        self,
        trip: TripResponse,
        request: TripRequest,
    ) -> TripResponse:
        """
        若地图补全带回了真实门票价格（it.place.ticket_price），
        重新汇总 day.daily_cost 与 trip.budget。
        Agent 内部的预算估算是基于草案的占位价，这里校正为补全后的真实价。
        """
        travelers = max(1, request.travelers)
        new_days: List[ItineraryDay] = []
        changed = False

        for day in trip.days:
            ticket_total = 0.0
            for it in day.items:
                p = it.ticket_price
                if p is None:
                    p = it.place.ticket_price
                if p is not None:
                    ticket_total += float(p) * travelers

            old_breakdown = day.cost_breakdown or {}
            old_ticket = float(old_breakdown.get("ticket", 0.0))
            if abs(ticket_total - old_ticket) < 0.01:
                new_days.append(day)
                continue

            changed = True
            new_breakdown = dict(old_breakdown)
            new_breakdown["ticket"] = round(ticket_total, 2)
            accommodation = float(new_breakdown.get("accommodation", 0.0))
            food = float(new_breakdown.get("food", 0.0))
            transport = float(new_breakdown.get("transportation", 0.0))
            daily_cost = accommodation + food + ticket_total + transport
            new_days.append(day.model_copy(update={
                "daily_cost": round(daily_cost, 2),
                "cost_breakdown": new_breakdown,
            }))

        if not changed:
            return trip

        total_ticket = sum(
            float(d.cost_breakdown.get("ticket", 0.0)) for d in new_days
        )
        old_budget = trip.budget
        new_total = (
            float(old_budget.accommodation_budget)
            + float(old_budget.food_budget)
            + total_ticket
            + float(old_budget.transportation_budget)
            + float(old_budget.other_budget)
        )
        new_budget = old_budget.model_copy(update={
            "ticket_budget": round(total_ticket, 2),
            "total_budget": round(new_total, 2),
            "daily_avg_budget": round(new_total / max(1, trip.total_days), 2),
            "budget_per_person": round(new_total / travelers, 2),
        })
        return trip.model_copy(update={"days": new_days, "budget": new_budget})

    # ================================================================
    # 6.1.4 Token 使用量统计
    # ================================================================

    def _make_token_callback(self):
        """
        构造 LangChain token 回调上下文管理器。
        优先用 langchain_community.get_openai_callback；
        不可用时降级到 langchain_core.callbacks.OpenAICallbackHandler；
        再不可用则返回 None（token 不统计）。
        """
        try:
            from langchain_community.callbacks import get_openai_callback

            return get_openai_callback()
        except ImportError:
            pass

        try:
            import contextlib

            from langchain_core.callbacks import OpenAICallbackHandler

            @contextlib.contextmanager
            def _cm():
                cb = OpenAICallbackHandler()
                yield cb

            return _cm()
        except ImportError:
            logger.debug("langchain token callback 不可用，跳过 token 统计")
            return None

    @staticmethod
    def _extract_token_usage(cb: Any) -> Dict[str, Any]:
        """从 callback 提取 token 使用统计。"""
        if cb is None:
            return {}
        return {
            "total_tokens": int(getattr(cb, "total_tokens", 0) or 0),
            "prompt_tokens": int(getattr(cb, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(cb, "completion_tokens", 0) or 0),
            "total_cost": round(float(getattr(cb, "total_cost", 0.0) or 0.0), 6),
            "successful_requests": int(getattr(cb, "successful_requests", 0) or 0),
        }

    # ================================================================
    # 6.1.5 行程编辑（单日编辑 + 规则降级）
    # ================================================================

    def edit_trip_day(
        self,
        trip_id: str,
        day_number: int,
        instruction: str,
        *,
        user_id: Optional[str] = None,
        request: Optional[TripRequest] = None,
        context: Optional[str] = None,
    ) -> TripResponse:
        """
        编辑行程的指定天。

        规则降级策略：
            - 行程不存在 → 抛 TripNotFoundError
            - Agent.edit_day 失败 → 返回原 trip + metadata["edit_failed"]=True
            - 地图补全失败 → 保留占位 + 记入 metadata["edit_warnings"]
            - 持久化失败 → 不阻断返回，记入 warnings

        Args:
            trip_id: 行程ID
            day_number: 第几天（1-based）
            instruction: 编辑指令（自然语言）
            user_id: 可选用户ID
            request: 可选的原始请求（用于 Agent.edit_day）
            context: 可选的攻略上下文

        Returns:
            编辑后的 TripResponse（即使失败也不抛异常）
        """
        # 1. 读库
        history = self._storage.get_trip_as_history(trip_id)
        if history is None:
            raise TripNotFoundError(f"行程不存在: {trip_id}")

        base_trip = history.response
        edit_warnings: List[str] = []

        # 2. Agent 单日编辑（内部已实现降级：失败时返回原 trip + edit_failed）
        try:
            edited = self._agent.edit_day(
                base_trip,
                day_number,
                instruction,
                request=request,
                context=context,
                allow_fallback=True,
            )
        except Exception as e:
            logger.error(f"edit_trip_day Agent 调用失败: {e}")
            return base_trip.model_copy(update={
                "metadata": {
                    **(base_trip.metadata or {}),
                    "edit_failed": True,
                    "edit_error": str(e),
                }
            })

        # 3. 对编辑后的单日做地图补全（其他日保持原样）
        edited = self._enrich_single_day_map(
            edited, day_number, base_trip.destination, edit_warnings
        )

        # 4. 持久化
        try:
            self._storage.update_trip(
                trip_id,
                response_data=json.loads(
                    json.dumps(edited.model_dump(mode="json"), default=str)
                ),
            )
        except Exception as e:
            logger.error(f"编辑后持久化失败: {e}")
            edit_warnings.append(f"持久化失败: {e}")

        # 5. 元数据回填
        meta = dict(edited.metadata or {})
        if edit_warnings:
            meta["edit_warnings"] = edit_warnings
        meta["edited_at"] = datetime.now().isoformat()
        return edited.model_copy(update={"metadata": meta})

    def _enrich_single_day_map(
        self,
        trip: TripResponse,
        day_number: int,
        city: str,
        warnings: List[str],
    ) -> TripResponse:
        """对编辑后的单日做 geocode 补全（其他日保持原样）。"""
        amap = self._get_amap_geo()
        if amap is None:
            warnings.append("amap_geo 不可用，单日地图未补全")
            return trip

        if day_number < 1 or day_number > len(trip.days):
            return trip

        idx = day_number - 1
        day = trip.days[idx]

        new_items: List[ItineraryItem] = []
        for item in day.items:
            new_place = self._geocode_place(
                item.place, city, amap, warnings, day_number
            )
            new_items.append(item.model_copy(update={"place": new_place}))

        new_day = day.model_copy(update={"items": new_items})
        new_day = self._enrich_day_meals_hotel(new_day, city, amap, warnings)

        new_days = list(trip.days)
        new_days[idx] = new_day
        return trip.model_copy(update={"days": new_days})

    # ================================================================
    # 行程 CRUD（薄包装 storage_service，供 Phase 7 API 直接调用）
    # ================================================================

    def get_trip(self, trip_id: str):
        """获取行程历史详情。"""
        return self._storage.get_trip_as_history(trip_id)

    def list_trips(
        self,
        user_id: Optional[str] = None,
        destination: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """列出行程（分页）。"""
        return self._storage.list_trips(
            user_id=user_id,
            destination=destination,
            is_favorite=is_favorite,
            limit=limit,
            offset=offset,
            order_by=order_by,
            order_desc=order_desc,
        )

    def delete_trip(self, trip_id: str) -> bool:
        """删除行程。"""
        return self._storage.delete_trip(trip_id)

    # ================================================================
    # 辅助
    # ================================================================

    def _trip_cache_key(self, request: TripRequest, user_id: Optional[str]) -> str:
        """根据请求 + user_id 生成稳定缓存 key。"""
        payload = json.dumps(
            {
                "destination": request.destination,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "travelers": request.travelers,
                "budget_level": str(request.budget_level),
                "travel_style": str(request.travel_style),
                "user_id": user_id or "",
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        digest = hashlib.md5(payload.encode("utf-8")).hexdigest()
        return f"trip:{digest}"

    def _safe_cache_get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """带异常保护的缓存读。"""
        try:
            return self._cache.get(cache_key, namespace=CacheNamespace.HISTORY)
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
            return None

    def _safe_cache_set(self, cache_key: str, trip: TripResponse) -> None:
        """带异常保护的缓存写。"""
        try:
            self._cache.set(
                cache_key,
                trip.model_dump(mode="json"),
                namespace=CacheNamespace.HISTORY,
                ttl=TRIP_CACHE_TTL,
            )
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")


# ============================================================================
# 模块级单例
# ============================================================================

trip_service = TripService()
