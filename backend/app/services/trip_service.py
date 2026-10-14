"""
山海拾光（智旅云图） - 行程服务编排（Phase 6.1）

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
import concurrent.futures
import hashlib
import inspect
import json
import time
import uuid
from datetime import date as date_type, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from app.agents.day_chain import _agent_shell, render_day_summary_line, run_day_chain
from app.agents.llm_factory import (
    build_json_llm,
    get_llm_thinking_config,
    log_llm_invocation,
    log_llm_reasoning_from_message,
    log_llm_request,
)
from app.agents.rag_tool import rag_tool as default_rag_tool
from app.agents.trip_planner_agent import (
    DEFAULT_RATING,
    TripPlannerAgent,
    trip_planner_agent,
)
from langchain_core.messages import HumanMessage
from app.config import get_active_llm_config, settings
from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    PreviewCandidate,
    TripRequest,
    TripResponse,
    TripPreviewResponse,
    WeatherInfo,
)
from app.services.amap_geo_service import (
    AmapGeoService,
    GeocodeResult,
    get_amap_geo_service,
    init_amap_geo_service,
)
from app.services.cache_service import CacheNamespace, cache_service
from app.services.geo_validation import validate_coordinate_for_city
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

# 12.2 SSE 流式：阶段事件进度（0-100，预估）
STREAM_STAGES: Dict[str, int] = {
    "cache_hit": 100,
    "poi_pool": 15,
    "planning": 30,
    "day_generating": 40,
    "draft": 45,
    "enrich": 70,
    "weather": 85,
    "finalize": 95,
}


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
        self._city_adcode_cache: Dict[str, str] = {}

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

    def _resolve_city_adcode(self, city: str) -> Optional[str]:
        """解析目标城市 adcode（行政区查询接口，进程内缓存）。失败返回 None（校验降级为仅边界）。"""
        if not city:
            return None
        if city in self._city_adcode_cache:
            return self._city_adcode_cache[city]
        amap = self._get_amap_geo()
        if amap is None:
            return None
        resolver = getattr(amap, "get_city_adcode", None)
        if not callable(resolver):
            return None
        try:
            adcode = _run_async(resolver(city))
        except Exception as e:
            logger.warning(f"解析城市 adcode 失败 [{city}]: {e}")
            return None
        if not isinstance(adcode, str) or not adcode.strip():
            return None
        self._city_adcode_cache[city] = adcode
        return adcode

    @staticmethod
    def _geocode_coord_valid(
        result: GeocodeResult,
        city: str,
        city_adcode: Optional[str],
    ) -> Tuple[bool, str]:
        """校验 geocode 返回的坐标是否可用于目标城市行程。"""
        return validate_coordinate_for_city(
            longitude=result.longitude,
            latitude=result.latitude,
            adcode=result.adcode or "",
            province=result.province or "",
            city=result.city or "",
            expected_city_adcode=city_adcode,
            expected_city=city,
        )

    # ================================================================
    # 6.1.2 + 6.1.3 主编排流程
    # ================================================================

    def generate_trip(
        self,
        request: TripRequest,
        *,
        user_id: Optional[str] = None,
        use_cache: bool = True,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        gen_mode: Optional[str] = None,
    ) -> TripResponse:
        """
        生成行程：缓存直出 → 分派 batch（Agent 整份生成）或 daily（逐天生成）
        → 补全 → token 统计 → 持久化。

        Args:
            request: 行程请求
            user_id: 可选用户ID
            use_cache: 是否启用缓存命中（默认 True）
            on_event: 12.2 事件 sink（SSE 流式推送）；None 时保持原同步语义
            gen_mode: 生成模式覆盖（batch | daily）；None 时跟随 settings.TRIP_GEN_MODE

        Returns:
            TripResponse，已补全地图/天气，并已写库
        """
        started_at = time.time()
        emit = lambda event: self._emit_event(on_event, event)

        # 1. 城市归一化（"北京市" → "北京"）
        dest = _normalize_destination(request.destination)
        request = request.model_copy(update={"destination": dest})

        # 2. 缓存命中检查（batch / daily 共用同一 cache key，结果结构等价互命中）
        cache_key = self._trip_cache_key(request, user_id)
        cached_trip = self._try_cache_hit(cache_key, use_cache, emit)
        if cached_trip is not None:
            return cached_trip

        # 2.1 生成模式分派：请求级 gen_mode 优先，缺省跟随 settings.TRIP_GEN_MODE
        mode = self._resolve_gen_mode(gen_mode)
        logger.info(f"行程生成模式: {mode}（TRIP_GEN_MODE={settings.TRIP_GEN_MODE}）")

        # 3. 生成调用（包裹 token callback）
        token_usage: Dict[str, Any] = {}
        enrich_warnings: List[str] = []
        callback_cm = self._make_token_callback()

        def _run_plan() -> TripResponse:
            if mode == "daily":
                # 13.3.1 逐天循环（含单日补全/天气挂载/day 事件/全量收尾）
                return self._generate_daily(request, on_event=emit)

            # batch：Agent 一次生成 → 整份补全（12.2 基线语义不变）
            trip = self._invoke_agent(request, on_event=emit)
            emit(self._draft_event_payload(trip))
            emit({
                "type": "status",
                "stage": "enrich",
                "message": "补全地图坐标与景点图片",
                "progress": STREAM_STAGES["enrich"],
            })
            trip = self._enrich_map(trip, request, enrich_warnings)
            emit({
                "type": "status",
                "stage": "weather",
                "message": "查询天气并生成出行建议",
                "progress": STREAM_STAGES["weather"],
            })
            trip = self._enrich_weather(trip, request, enrich_warnings)
            trip = self._enrich_weather_suggestions(trip, enrich_warnings)
            emit({
                "type": "status",
                "stage": "finalize",
                "message": "拆分预算并保存方案",
                "progress": STREAM_STAGES["finalize"],
            })
            return self._recalculate_budget(trip, request)

        if callback_cm is not None:
            with callback_cm as cb:
                trip = _run_plan()
            token_usage = self._extract_token_usage(cb)
        else:
            trip = _run_plan()

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

    # ================================================================
    # 13.3 方案B：逐天编排循环（真·逐天生成，多次 LLM 调用）
    # ================================================================

    def _try_cache_hit(
        self,
        cache_key: str,
        use_cache: bool,
        emit: Callable[[Dict[str, Any]], None],
    ) -> Optional[TripResponse]:
        """缓存命中直出（batch / daily 共用同一 cache key，结果结构等价互命中）。"""
        if not use_cache:
            return None
        cached = self._safe_cache_get(cache_key)
        if cached is None:
            return None
        try:
            trip = TripResponse.model_validate(cached)
            trip = trip.model_copy(update={
                "metadata": {
                    **(trip.metadata or {}),
                    "cache_hit": True,
                }
            })
            logger.info(f"行程缓存命中: {cache_key}")
            emit({
                "type": "status",
                "stage": "cache_hit",
                "message": "命中缓存，直接返回",
                "progress": STREAM_STAGES["cache_hit"],
            })
            return trip
        except Exception as e:
            logger.warning(f"缓存反序列化失败，重新生成: {e}")
            return None

    @staticmethod
    def _resolve_gen_mode(override: Optional[str]) -> str:
        """生成模式解析：请求级 override 优先，缺省跟随 settings.TRIP_GEN_MODE。"""
        if override in ("batch", "daily"):
            return override
        mode = getattr(settings, "TRIP_GEN_MODE", "daily")
        return mode if mode in ("batch", "daily") else "daily"

    def _generate_daily(
        self,
        request: TripRequest,
        *,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> TripResponse:
        """13.3.1 逐天编排循环：prepare → for day in 1..N: run_day_chain →
        跨天记忆 → day(draft) 事件 → 单日地图/图片补全 → 天气挂载 →
        day(enriched) 事件 → append；最后 _finalize_daily 全量收尾。

        非流式（on_event=None）走同一路径，仅不推事件。
        单日兜底仍失败（罕见）时中止整份并抛 TripServiceError，不持久化部分行程。
        """
        emit = lambda event: self._emit_event(on_event, event)

        state = self._prepare_day_state(request, emit)
        total_days = state["total_days"]
        day_dates = state["day_dates"]
        warnings: List[str] = []
        days: List[ItineraryDay] = []
        daily_meta: Dict[str, Any] = {
            "daily_llm_calls": [],
            "fallback_days": [],
            "repair_days": [],
        }

        emit({
            "type": "status",
            "stage": "planning",
            "message": "大模型开始逐天规划行程",
            "progress": STREAM_STAGES["planning"],
        })

        # 天气一次性取整段预报（1 次调用），逐天按日期挂载
        forecast_by_date = self._fetch_forecast_by_date(request)
        if not forecast_by_date:
            warnings.append("天气预报未获取到，各天天气留空")

        amap = self._get_amap_geo()
        if amap is None:
            warnings.append("amap_geo 服务不可用，地图未补全")
        city_adcode = (
            self._resolve_city_adcode(request.destination) if amap is not None else None
        )
        photo_cache: Dict[str, List[str]] = {}
        city = request.destination

        for day_no in range(1, total_days + 1):
            day_state: Dict[str, Any] = {
                **state,
                "day_number": day_no,
                "day_date": day_dates[day_no - 1],
                "day_summaries": list(state["day_summaries"]),
                "used_place_ids": list(state["used_place_ids"]),
                "used_names": list(state["used_names"]),
                "prev_district": state["prev_district"],
                "prev_hotel": state["prev_hotel"],
                "accumulated_budget": state["accumulated_budget"],
                "meta": {},
            }
            res = run_day_chain(day_state, on_event=on_event)

            if res.get("error"):
                logger.error(f"第{day_no}天生成失败且兜底失败: {res['error']}")
                raise TripServiceError(f"第{day_no}天生成失败: {res['error']}")

            # 13.3.2 跨天记忆维护（供下一天 build_day_prompt 渲染前 N-1 天摘要）
            memory = res.get("memory") or {}
            state["used_place_ids"] += list(memory.get("used_place_ids_added") or [])
            state["used_names"] += list(memory.get("used_names_added") or [])
            if memory.get("prev_district"):
                state["prev_district"] = memory["prev_district"]
            if memory.get("prev_hotel"):
                state["prev_hotel"] = memory["prev_hotel"]
            summary = memory.get("day_summary")
            if summary:
                state["day_summaries"].append(summary)
                try:
                    state["accumulated_budget"] += float(summary.get("cost") or 0.0)
                except (TypeError, ValueError):
                    pass

            day_meta = res.get("meta") or {}
            daily_meta["daily_llm_calls"].extend(day_meta.get("daily_llm_calls") or [])
            if day_meta.get("day_repair_used"):
                daily_meta["repair_days"].append(day_no)
            if res.get("fallback_used"):
                daily_meta["fallback_days"].append(day_no)

            day_warnings = list(res.get("day_warnings") or [])
            warnings.extend(day_warnings)
            day = res["day"]

            # 草案版 day 事件（补全前先给前端：主题 + 地点链 + day_summary）
            emit(self._day_draft_event_payload(day_no, total_days, res.get("draft_day")))

            # 单日地图/图片补全（占位坐标 → 真实坐标/地址/图片；失败不影响当天）
            if amap is not None:
                day = self._enrich_day_map(day, city, amap, warnings, photo_cache, city_adcode)

            # 天气挂载（无预报保持 None）
            day = self._attach_day_weather(day, forecast_by_date)

            # 补全版 day 事件
            emit({
                "type": "day",
                "state": "enriched",
                "day_number": day_no,
                "total_days": total_days,
                "day": day.model_dump(mode="json"),
            })

            days.append(day)

        emit({
            "type": "status",
            "stage": "finalize",
            "message": "汇总行程亮点并保存方案",
            "progress": STREAM_STAGES["finalize"],
        })

        return self._finalize_daily(request, days, state, warnings, daily_meta)

    def _prepare_day_state(
        self,
        request: TripRequest,
        emit: Callable[[Dict[str, Any]], None],
    ) -> Dict[str, Any]:
        """城市级一次性准备 → DayGenState 循环不变量（13.1.2）。

        - A 级（沉淀城市）：rag_tool.search_for_trip 一次（生成上下文）+
          build_pool_sync 一次（仅供图/poi 事件，失败不影响规划）
        - B 级（动态城市）：build_pool_sync 一次 → sections/index/clusters；
          景点池为空或构建失败降级回 RAG 路径（与 batch _invoke_agent 一致）
        """
        dest = request.destination
        total_days = (request.end_date - request.start_date).days + 1
        day_dates = [request.start_date + timedelta(days=i) for i in range(total_days)]
        state: Dict[str, Any] = {
            "request": request,
            "total_days": total_days,
            "day_dates": day_dates,
            "global_constraints": {},
            "candidate_sections": {},
            "rag_context": "",
            "candidate_index": {},
            "district_clusters": {},
            "food_candidates": [],
            "hotel_candidates": [],
            "used_place_ids": [],
            "used_names": [],
            "prev_district": None,
            "prev_hotel": None,
            "day_summaries": [],
            "accumulated_budget": 0.0,
            "meta": {},
        }

        if is_preset_city(dest):
            logger.info(f"沉淀城市 [{dest}]：逐天模式走 RAG 工具")
            emit({
                "type": "status",
                "stage": "poi_pool",
                "message": f"检索 {dest} 攻略与候选图片",
                "progress": STREAM_STAGES["poi_pool"],
            })
            state["rag_context"] = self._search_rag_context(request)
            try:
                pool = self._place_service.build_pool_sync(request)
                self._emit_poi_batches(pool, emit)
            except Exception as e:
                logger.warning(f"A 级城市 POI 供图失败 [{dest}]: {e}")
            return state

        # 动态城市（B 级）：POI 三池驱动
        logger.info(f"动态城市 [{dest}]：构建 POI 三池（景点/餐饮/住宿）")
        emit({
            "type": "status",
            "stage": "poi_pool",
            "message": f"构建 {dest} POI 候选池",
            "progress": STREAM_STAGES["poi_pool"],
        })
        try:
            pool = self._place_service.build_pool_sync(request)
        except Exception as e:
            logger.warning(f"POI 三池构建失败: {e}，退回 RAG 路径")
            state["rag_context"] = self._search_rag_context(request)
            return state

        sections = PlaceCandidateService.to_prompt_sections(pool)
        if not sections.get("scenic"):
            logger.warning(f"动态城市 [{dest}] 景点池为空，退回 RAG 路径")
            state["rag_context"] = self._search_rag_context(request)
            return state

        state["candidate_sections"] = sections
        state["candidate_index"] = sections.get("index") or {}
        state["district_clusters"] = sections.get("clusters") or {}
        state["food_candidates"] = sections.get("food") or []
        state["hotel_candidates"] = sections.get("hotel") or []
        logger.info(
            f"动态城市 [{dest}] 候选池: "
            f"景点{len(sections.get('scenic') or [])}个 "
            f"餐饮{len(state['food_candidates'])}个 "
            f"住宿{len(state['hotel_candidates'])}个 "
            f"区域{len(state['district_clusters'])}个"
        )
        self._emit_poi_batches(pool, emit)
        return state

    def _search_rag_context(self, request: TripRequest) -> str:
        """A 级 / B 级降级：攻略检索一次，失败返回空（由单日链兜底）。"""
        try:
            result = default_rag_tool.search_for_trip(request)
            return getattr(result, "context_text", "") or ""
        except Exception as e:
            logger.warning(f"攻略检索失败 [{request.destination}]: {e}")
            return ""

    @staticmethod
    def _day_draft_event_payload(
        day_number: int,
        total_days: int,
        draft_day: Any,
    ) -> Dict[str, Any]:
        """草案版 day 事件：主题 + 地点链 + day_summary（13.1.5 day=draft）。"""
        theme = None
        summary = None
        places: List[str] = []
        if draft_day is not None:
            theme = getattr(draft_day, "day_theme", None)
            summary = getattr(draft_day, "day_summary", None)
            places = [it.name for it in (getattr(draft_day, "items", None) or [])]
        return {
            "type": "day",
            "state": "draft",
            "day_number": day_number,
            "total_days": total_days,
            "theme": theme,
            "places": places,
            "day_summary": summary,
        }

    def _fetch_forecast_by_date(
        self,
        request: TripRequest,
    ) -> Optional[Dict[date_type, WeatherInfo]]:
        """一次性取整段行程的天气预报 → forecast_date → WeatherInfo（1 次调用）。"""
        weather_svc = self._get_weather_service()
        if weather_svc is None:
            return None
        total_days = (request.end_date - request.start_date).days + 1
        try:
            city_weather_map = _run_async(
                weather_svc.get_trip_weather(
                    [request.destination],
                    request.start_date,
                    total_days,
                )
            )
        except Exception as e:
            logger.warning(f"天气查询失败: {e}")
            return None
        forecasts = city_weather_map.get(request.destination) or []
        if not forecasts:
            return None
        by_date: Dict[date_type, WeatherInfo] = {}
        for f in forecasts:
            if f.forecast_date is not None:
                by_date[f.forecast_date] = f
        # 预报条数少于天数时按 day_number 位置兜底
        for i, f in enumerate(forecasts):
            by_date.setdefault(request.start_date + timedelta(days=i), f)
        return by_date

    @staticmethod
    def _attach_day_weather(
        day: ItineraryDay,
        forecast_by_date: Optional[Dict[date_type, WeatherInfo]],
    ) -> ItineraryDay:
        """按 itinerary_date 挂载当日天气；无预报时保持 None。"""
        if not forecast_by_date:
            return day
        w = forecast_by_date.get(day.itinerary_date)
        if w is None:
            return day
        return day.model_copy(update={"weather": w})

    def _finalize_daily(
        self,
        request: TripRequest,
        days: List[ItineraryDay],
        state: Dict[str, Any],
        warnings: List[str],
        daily_meta: Dict[str, Any],
    ) -> TripResponse:
        """13.3.3 全量收尾：聚合整份元信息 → TripResponse → 天气建议 → 预算校正。

        trip_name / highlights / tips / foods / shopping 由最后一轮 LLM 小调用生成
        （13.4.4，失败降级本地聚合）；special_needs_notes 本地确定性生成。
        """
        aggregated = self._aggregate_trip_summary(request, state["day_summaries"])
        overall_rating = (
            round(sum(d.total_rating for d in days) / len(days), 1) if days else DEFAULT_RATING
        )
        overall_rating = min(5.0, max(0.0, overall_rating))

        meta = {
            "needs_enrichment": False,
            "generation_mode": "daily",
            "gen_mode": "daily",
            "day_warnings": list(warnings),
            "enrich_warnings": list(warnings),
            **daily_meta,
        }

        trip = TripResponse(
            trip_id=str(uuid.uuid4()),
            destination=request.destination,
            trip_name=aggregated["trip_name"],
            start_date=request.start_date,
            end_date=request.end_date,
            total_days=state["total_days"],
            days=days,
            overall_rating=overall_rating,
            budget=BudgetInfo(
                total_budget=0,
                daily_avg_budget=0,
                budget_per_person=0,
            ),
            trip_highlights=aggregated["trip_highlights"],
            trip_tips=aggregated["trip_tips"],
            special_needs_notes=self._special_needs_notes(request),
            recommended_foods=aggregated["recommended_foods"],
            recommended_shopping=aggregated["recommended_shopping"],
            generated_at=datetime.now(),
            model_used=get_active_llm_config().get("model"),
            metadata=meta,
        )
        trip = self._enrich_weather_suggestions(trip, warnings)
        trip = _agent_shell().enrich_budget_and_summary(trip, request)
        return self._recalculate_budget(trip, request)

    def _aggregate_trip_summary(
        self,
        request: TripRequest,
        day_summaries: List[dict],
    ) -> Dict[str, Any]:
        """13.4.4 最后一轮 LLM 小调用：由 N 天紧凑摘要聚合整份行程元信息。

        失败（LLM 异常 / JSON 非法）自动降级为本地聚合（_aggregate_local）。
        """
        if not day_summaries:
            return self._aggregate_local(request, day_summaries)

        summary_lines = [render_day_summary_line(e) for e in day_summaries]
        prompt = (
            f"你是资深旅行顾问。请根据以下「{request.destination}」{len(day_summaries)} 日行程的每日摘要，"
            "生成整份行程的名称、亮点、贴士、推荐美食与购物建议。\n\n"
            f"行程日期：{request.start_date.isoformat()} 至 {request.end_date.isoformat()}\n"
            "每日摘要：\n"
            + "\n".join(summary_lines)
            + "\n\n"
            '只返回 JSON，格式：{"trip_name": "行程名称", "trip_highlights": ["亮点1", ...], '
            '"trip_tips": ["贴士1", ...], "recommended_foods": ["美食1", ...], '
            '"recommended_shopping": ["购物1", ...]}'
        )
        try:
            llm = self._llm or build_json_llm(temperature=0.3, max_tokens=512)
            log_llm_invocation()
            messages = [HumanMessage(content=prompt)]
            log_llm_request(
                messages=messages,
                note="trip_summary",
                model=getattr(llm, "model_name", None),
                temperature=0.3,
                max_tokens=512,
                streaming=False,
                thinking=get_llm_thinking_config(),
            )
            resp = llm.invoke(messages)
            log_llm_reasoning_from_message(resp, note="trip_summary")
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            data = json.loads(_strip_json_fence(content))
            if not isinstance(data, dict):
                raise ValueError("聚合结果不是 JSON 对象")
            return self._normalize_aggregated(data, request, day_summaries)
        except Exception as e:
            logger.warning(f"整份行程聚合 LLM 调用失败，降级本地聚合: {e}")
            return self._aggregate_local(request, day_summaries)

    @staticmethod
    def _normalize_aggregated(
        data: dict,
        request: TripRequest,
        day_summaries: List[dict],
    ) -> Dict[str, Any]:
        """LLM 聚合结果规范化（类型/长度裁剪；缺失字段用本地聚合补齐）。"""
        local = TripService._aggregate_local(request, day_summaries)

        def _list(value: Any, default: List[str]) -> List[str]:
            if not isinstance(value, list):
                return default
            cleaned = [str(x).strip() for x in value if isinstance(x, str) and x.strip()]
            return cleaned[:8] or default

        def _str(value: Any, default: str) -> str:
            return str(value).strip()[:60] if isinstance(value, str) and value.strip() else default

        return {
            "trip_name": _str(data.get("trip_name"), local["trip_name"]),
            "trip_highlights": _list(data.get("trip_highlights"), local["trip_highlights"]),
            "trip_tips": _list(data.get("trip_tips"), local["trip_tips"]),
            "recommended_foods": _list(data.get("recommended_foods"), local["recommended_foods"]),
            "recommended_shopping": _list(
                data.get("recommended_shopping"), local["recommended_shopping"]
            ),
        }

    @staticmethod
    def _aggregate_local(
        request: TripRequest,
        day_summaries: List[dict],
    ) -> Dict[str, Any]:
        """本地聚合兜底：由每日摘要/主题/餐饮名拼装整份元信息（0 次 LLM 调用）。"""
        total = len(day_summaries) or 1
        highlights: List[str] = []
        for e in day_summaries:
            theme = e.get("theme") or f"第{e.get('day_number')}天"
            places = "、".join(str(p) for p in (e.get("places") or [])[:3])
            highlights.append(f"{theme}：{places}" if places else theme)
        if not highlights:
            highlights = [f"{request.destination}{total}日经典行程"]
        tips = [
            "【出行准备】出行前确认各景点最新开放时间和预约政策，热门景点建议提前预约",
            "【交通出行】建议提前规划每日交通路线，预留通勤时间",
            "【安全须知】保管好个人财物，尤其在人流密集的景区",
        ]
        foods: List[str] = []
        for e in day_summaries:
            for key in ("lunch", "dinner"):
                name = e.get(key)
                if name and str(name) not in foods:
                    foods.append(str(name))
            if len(foods) >= 5:
                break
        return {
            "trip_name": f"{request.destination}{total}日游",
            "trip_highlights": highlights[:5],
            "trip_tips": tips,
            "recommended_foods": foods[:8],
            "recommended_shopping": [],
        }

    @staticmethod
    def _special_needs_notes(request: TripRequest) -> List[str]:
        """同行状态（特殊需求）满足说明（与 batch draft_to_trip_response 同源）。"""
        notes: List[str] = []
        if request.with_kids:
            notes.append("已优先安排亲子友好、安全可控的景点，避免高强度徒步与危险区域")
            notes.append("行程节奏舒缓，预留充足休息与用餐时间，适合儿童体力")
        if request.with_elderly:
            notes.append("已安排轻松、少步行的路线，每日景点数量适中，控制体力消耗")
            notes.append("优先选择有休息设施、平坦好走的景点，避免长时间爬山")
        if request.has_disability:
            notes.append("已优先选择无障碍通道可达、台阶少、地面平缓的景点")
            notes.append("每日行程均考虑轮椅通行便利性，尽量减少步行距离")
        return notes

    # ================================================================
    # 12.1 方案 A：行程预览（先图后等）
    # ================================================================

    def build_preview(
        self,
        request: TripRequest,
        *,
        user_id: Optional[str] = None,
    ) -> TripPreviewResponse:
        """
        构建行程预览：拉取 POI 候选池（A/B 级城市均出图），快速返回候选图片池。

        与 generate_trip 的差异：
        - 不调用 Agent / LLM，只复用候选池（24h 缓存）→ 秒级返回
        - A 级（preset）与 B 级（dynamic）统一走 build_pool_sync，仅供图不参与规划
        - 失败不阻断：候选池为空/异常时返回空 candidates + source=fallback

        Args:
            request: 行程请求
            user_id: 可选用户ID（预留，暂不参与缓存键）

        Returns:
            TripPreviewResponse：候选地点（含图片）+ 城市等级 + 耗时
        """
        started_at = time.time()

        # 1. 城市归一化（与 generate_trip 一致）
        dest = _normalize_destination(request.destination)
        request = request.model_copy(update={"destination": dest})
        level = "preset" if is_preset_city(dest) else "dynamic"

        warnings: List[str] = []
        candidates: List[PreviewCandidate] = []
        source = "poi_pool"

        # 2. 拉取候选池（复用 24h 缓存；A 级城市同样走 POI 池仅供图）
        try:
            pool = self._place_service.build_pool_sync(request)
            warnings.extend([w for w in (pool.warnings or []) if w][:5])

            raw_candidates: List[PreviewCandidate] = []
            for place in (
                list(pool.scenic_places or [])[:8]
                + list(pool.food_places or [])[:4]
                + list(pool.hotel_places or [])[:3]
            ):
                photos = [u for u in (place.photos or []) if isinstance(u, str) and u]
                raw_candidates.append(
                    PreviewCandidate(
                        name=place.name,
                        category=place.category or "景点",
                        address=place.address or None,
                        district=place.district,
                        rating=place.rating,
                        photos=photos,
                        score=round(float(place.score or 0.0), 3),
                    )
                )

            # 有图优先，再按打分降序（保证图片墙先满）
            candidates = sorted(
                raw_candidates,
                key=lambda c: (0 if c.photos else 1, -c.score),
            )

            if not candidates:
                warnings.append(f"[{dest}] 候选池为空，图片预览不可用")
                source = "fallback"
        except Exception as e:
            logger.warning(f"预览候选池构建失败 [{dest}]: {e}")
            warnings.append(f"候选池构建失败: {e}")
            source = "fallback"

        return TripPreviewResponse(
            destination=dest,
            city_level=level,
            candidates=candidates,
            total=len(candidates),
            estimate_seconds=round(time.time() - started_at, 3),
            source=source,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Agent 调用：根据城市分级走不同分支
    # ------------------------------------------------------------------

    def _invoke_agent(
        self,
        request: TripRequest,
        *,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> TripResponse:
        """
        根据城市分级调用 TripPlannerAgent.plan：

        - 沉淀城市（A 级）：Agent 走 RAG 工具调用模式（use_tools=True），
          POI 池在独立线程并行供图（12.2.5），供图失败不影响规划
        - 动态城市（B 级）：构建三池（景点/餐饮/住宿）+ 区域聚类 → 全链路 POI 驱动，
          POI 池就绪后先推 poi 事件再进 LLM（12.2.4）；拉取失败则降级回 RAG 路径
        """
        emit = lambda event: self._emit_event(on_event, event)
        dest = request.destination

        if is_preset_city(dest):
            logger.info(f"沉淀城市 [{dest}]：Agent 走 RAG 工具")
            emit({
                "type": "status",
                "stage": "poi_pool",
                "message": f"检索 {dest} 攻略与候选图片",
                "progress": STREAM_STAGES["poi_pool"],
            })
            # 12.2.5 流式模式：POI 供图线程与 RAG/LLM 规划并行（供图失败不影响规划）
            if on_event is not None:
                pool: Optional[CandidatePool] = None
                trip: Optional[TripResponse] = None
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool_exec:
                        pool_future = pool_exec.submit(self._place_service.build_pool_sync, request)
                        emit({
                            "type": "status",
                            "stage": "planning",
                            "message": "大模型开始规划行程",
                            "progress": STREAM_STAGES["planning"],
                        })
                        trip = self._agent.plan(request, use_tools=True, allow_fallback=True)
                except Exception as e:
                    logger.error(f"A 级城市规划失败 [{dest}]: {e}")
                    raise
                try:
                    # with 退出（shutdown wait）保证供图已就绪；供图失败不影响已完成的规划
                    pool = pool_future.result(timeout=30)
                except Exception as e:
                    logger.warning(f"A 级城市 POI 供图失败 [{dest}]: {e}")
                    pool = None
                if pool is not None:
                    self._emit_poi_batches(pool, emit)
                return trip
            else:
                # 非流式（普通 generate / 降级）：保持原语义，不额外拉池
                emit({
                    "type": "status",
                    "stage": "planning",
                    "message": "大模型开始规划行程",
                    "progress": STREAM_STAGES["planning"],
                })
                return self._agent.plan(
                    request,
                    use_tools=True,
                    allow_fallback=True,
                )

        # 动态城市：构建三池（景点/餐饮/住宿）+ 区域聚类
        logger.info(f"动态城市 [{dest}]：构建 POI 三池（景点/餐饮/住宿）")
        emit({
            "type": "status",
            "stage": "poi_pool",
            "message": f"构建 {dest} POI 候选池",
            "progress": STREAM_STAGES["poi_pool"],
        })
        try:
            pool = self._place_service.build_pool_sync(request)
            sections = PlaceCandidateService.to_prompt_sections(pool)
            if not sections.get("scenic"):
                logger.warning(f"动态城市 [{dest}] 景点池为空，退回 RAG 路径")
                emit({
                    "type": "status",
                    "stage": "planning",
                    "message": "大模型开始规划行程",
                    "progress": STREAM_STAGES["planning"],
                })
                return self._agent.plan(request, use_tools=True, allow_fallback=True)
        except Exception as e:
            logger.warning(f"POI 三池构建失败: {e}，退回 RAG 路径")
            emit({
                "type": "status",
                "stage": "planning",
                "message": "大模型开始规划行程",
                "progress": STREAM_STAGES["planning"],
            })
            return self._agent.plan(request, use_tools=True, allow_fallback=True)

        logger.info(
            f"动态城市 [{dest}] 候选池: "
            f"景点{len(sections.get('scenic') or [])}个 "
            f"餐饮{len(sections.get('food') or [])}个 "
            f"住宿{len(sections.get('hotel') or [])}个 "
            f"区域{len(sections.get('clusters') or {})}个"
        )

        # POI 池就绪：先按类别分批推图，再进 LLM 规划
        self._emit_poi_batches(pool, emit)
        emit({
            "type": "status",
            "stage": "planning",
            "message": "大模型开始规划行程",
            "progress": STREAM_STAGES["planning"],
        })
        return self._agent.plan(
            request,
            candidate_sections=sections,
            use_tools=False,
            allow_fallback=True,
        )

    # ------------------------------------------------------------------
    # 12.2 SSE 流式事件
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_event(
        on_event: Optional[Callable[[Dict[str, Any]], None]],
        event: Dict[str, Any],
    ) -> None:
        """事件 sink 调用：失败不影响主流程（客户端断开时静默忽略）。"""
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception as e:
            logger.debug(f"事件推送失败（忽略）: {e}")

    @staticmethod
    def _emit_poi_batches(
        pool: CandidatePool,
        emit: Callable[[Dict[str, Any]], None],
    ) -> None:
        """按 scenic/food/hotel 分批推 poi 事件（先于 LLM 返回）。"""
        limits = {"scenic": 8, "food": 4, "hotel": 3}
        for category, places in (
            ("scenic", getattr(pool, "scenic_places", None) or []),
            ("food", getattr(pool, "food_places", None) or []),
            ("hotel", getattr(pool, "hotel_places", None) or []),
        ):
            items: List[Dict[str, Any]] = []
            for p in places[: limits[category]]:
                photos = [u for u in (p.photos or []) if isinstance(u, str) and u]
                items.append({
                    "name": p.name,
                    "category": p.category or category,
                    "address": p.address or None,
                    "district": p.district,
                    "rating": p.rating,
                    "photos": photos,
                    "score": round(float(p.score or 0.0), 3),
                })
            if items:
                emit({"type": "poi", "category": category, "items": items})

    @staticmethod
    def _draft_event_payload(trip: TripResponse) -> Dict[str, Any]:
        """草案骨架事件：每日地点名 + 主题 + 行程亮点（补全前先给前端）。"""
        days: List[Dict[str, Any]] = []
        for day in trip.days:
            days.append({
                "day_number": day.day_number,
                "theme": day.day_theme or f"第{day.day_number}天",
                "places": [item.place.name for item in day.items],
            })
        return {
            "type": "draft",
            "days": days,
            "highlights": list(trip.trip_highlights or []),
        }

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
        city_adcode = self._resolve_city_adcode(city)
        photo_cache: Dict[str, List[str]] = {}
        new_days = [
            self._enrich_day_map(day, city, amap, warnings, photo_cache, city_adcode)
            for day in trip.days
        ]

        return trip.model_copy(update={"days": new_days})

    def _enrich_day_map(
        self,
        day: ItineraryDay,
        city: str,
        amap: AmapGeoService,
        warnings: List[str],
        photo_cache: Dict[str, List[str]],
        city_adcode: Optional[str],
    ) -> ItineraryDay:
        """单日地图/图片补全（供 13.3 逐天循环逐日调用；batch _enrich_map 同源复用）。"""
        new_items: List[ItineraryItem] = []
        for item in day.items:
            new_place = self._geocode_place(
                item.place, city, amap, warnings, day.day_number, city_adcode
            )
            new_place = self._enrich_place_photos(
                new_place, city, amap, warnings, f"第{day.day_number}天", photo_cache
            )
            new_items.append(item.model_copy(update={"place": new_place}))
        new_day = day.model_copy(update={"items": new_items})
        return self._enrich_day_meals_hotel(
            new_day, city, amap, warnings, photo_cache, city_adcode
        )

    def _geocode_place(
        self,
        place: PlaceInfo,
        city: str,
        amap: AmapGeoService,
        warnings: List[str],
        day_number: int,
        city_adcode: Optional[str],
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

        ok, reason = self._geocode_coord_valid(result, city, city_adcode)
        if not ok:
            warnings.append(
                f"第{day_number}天 [{place.name}] geocode 坐标校验未通过: {reason}"
            )
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
        city_adcode: Optional[str],
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
            ok, reason = self._geocode_coord_valid(result, city, city_adcode)
            if not ok:
                warnings.append(
                    f"第{day.day_number}天餐 [{meal.name}] geocode 坐标校验未通过: {reason}"
                )
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
                ok, reason = self._geocode_coord_valid(result, city, city_adcode)
                if not ok:
                    warnings.append(
                        f"第{day.day_number}天酒店 [{day.hotel.name}] geocode 坐标校验未通过: {reason}"
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
            log_llm_invocation()
            messages = [HumanMessage(content=prompt)]
            log_llm_request(
                messages=messages,
                note="weather_suggest",
                temperature=0.3,
                max_tokens=256,
                streaming=False,
                thinking=get_llm_thinking_config(),
            )
            resp = llm.invoke(messages)
            log_llm_reasoning_from_message(resp, note="weather_suggest")
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
    # 行程 CRUD（薄包装 storage_service，供 Phase 7 API 直接调用）
    # ================================================================

    def get_trip(self, trip_id: str, user_id: Optional[str] = None):
        """获取行程历史详情。"""
        return self._storage.get_trip_as_history(trip_id, user_id=user_id)

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

    def delete_trip(self, trip_id: str, user_id: Optional[str] = None) -> bool:
        """删除行程。"""
        return self._storage.delete_trip(trip_id, user_id=user_id)

    def delete_trips(self, trip_ids: List[str], user_id: Optional[str] = None) -> int:
        """批量删除行程，返回实际删除数量。"""
        return self._storage.delete_trips(trip_ids, user_id=user_id)

    def set_favorites(self, trip_ids: List[str], is_favorite: bool, user_id: Optional[str] = None) -> int:
        """批量设置收藏状态，返回实际更新数量。"""
        return self._storage.set_favorites(trip_ids, is_favorite, user_id=user_id)

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
                "with_kids": request.with_kids,
                "with_elderly": request.with_elderly,
                "has_disability": request.has_disability,
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
