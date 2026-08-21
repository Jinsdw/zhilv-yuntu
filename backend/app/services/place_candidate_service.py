"""
智旅云图 - 动态 POI 候选池服务

按城市/偏好从高德拉真实地点，供 trip_planner_agent 约束选点。
不重做地图 HTTP；不编排路线/天气（留给 6.1）。

功能模块：
- 5.3.1 服务骨架与契约：模型、异常、PlaceCandidateService
- 5.3.2 搜索策略生成：TripRequest → QueryPlan
- 5.3.3 多路拉取与缓存：map_service + cache
- 5.3.4 过滤打分与成池：去重、排除、多样性 Top-N
- 5.3.5 对外 API：build_pool / resolve_name / to_prompt_items
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence

from loguru import logger
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import (
    Coordinate,
    TravelStyle,
    TripRequest,
)
from .cache_service import (
    CacheNamespace,
    CacheStrategy,
    cache_service,
)
from .map_service import (
    MapService,
    POIInfo,
    POISearchResult,
    get_map_service,
    init_map_service,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_MAX_PLACES = 40
DEFAULT_PER_TASK_LIMIT = 15
DEFAULT_BUCKET_CAP = 8
DEFAULT_CACHE_TTL_STRATEGY = CacheStrategy.LONG_TERM  # 24h
RATE_LIMIT_DELAY = 0.15
MAX_CONCURRENCY = 4

# 高德常用 POI 类型码（景点/餐饮/住宿相关）
TYPE_SCENIC = "110000"  # 风景名胜
TYPE_MUSEUM = "140100"  # 博物馆
TYPE_PARK = "110101"  # 公园
TYPE_TEMPLE = "140600"  # 宗教
TYPE_FOOD = "050000"  # 餐饮服务
TYPE_HOTEL = "100000"  # 住宿服务
TYPE_SHOPPING = "060000"  # 购物

# 明显非旅游类型（名称/type 命中则过滤）
NON_TRAVEL_TYPE_HINTS = (
    "公司",
    "企业",
    "有限",
    "厂",
    "小区",
    "住宅",
    "写字楼",
    "停车场",
    "公厕",
    "ATM",
    "银行",
    "加油站",
)

INDOOR_HINTS = ("博物馆", "美术馆", "展览", "室内", "商场", "温泉", "水族")
OUTDOOR_HINTS = ("公园", "山", "湖", "海", "古镇", "风景", "户外", "徒步", "峡谷")

STYLE_KEYWORDS: dict[str, list[str]] = {
    TravelStyle.RELAXED.value: ["公园", "古城", "慢游", "风景区"],
    TravelStyle.COMPACT.value: ["必去", "地标", "热门景点"],
    TravelStyle.ADVENTURE.value: ["登山", "徒步", "峡谷", "漂流"],
    TravelStyle.CULTURAL.value: ["博物馆", "古迹", "历史", "寺庙", "故居"],
    TravelStyle.FOODIE.value: ["美食", "小吃", "夜市", "特色餐厅"],
}

STYLE_TYPES: dict[str, list[str]] = {
    TravelStyle.RELAXED.value: [TYPE_PARK, TYPE_SCENIC],
    TravelStyle.COMPACT.value: [TYPE_SCENIC],
    TravelStyle.ADVENTURE.value: [TYPE_SCENIC, TYPE_PARK],
    TravelStyle.CULTURAL.value: [TYPE_MUSEUM, TYPE_TEMPLE, TYPE_SCENIC],
    TravelStyle.FOODIE.value: [TYPE_FOOD, TYPE_SCENIC],
}

# RAG 片段中抽取景点名的轻量模式
_POI_NAME_PATTERNS = [
    re.compile(r"[「『《【]([^」』》】]{2,20})[」』》】]"),
    re.compile(r"(?:推荐|必去|打卡)[：:]\s*([^\s，,。；;、]{2,16})"),
    re.compile(r"^[-*•]\s*\*?\*?([^\s*，,。：:]{2,16})", re.MULTILINE),
]


# ---------------------------------------------------------------------------
# 5.3.1 异常与契约
# ---------------------------------------------------------------------------

class CandidateError(Exception):
    """候选池通用错误"""


class CandidateFetchError(CandidateError):
    """地图拉取全部失败"""


class CandidateEmptyError(CandidateError):
    """过滤后候选为空（默认不硬抛，仅作信号）"""


class SearchMode(str, Enum):
    KEYWORD = "keyword"
    TYPES = "types"
    NEARBY = "nearby"


class SearchTask(BaseModel):
    """单路搜索任务"""

    mode: SearchMode
    keywords: Optional[str] = None
    types: Optional[str] = None
    limit: int = Field(default=DEFAULT_PER_TASK_LIMIT, ge=1, le=50)
    priority: int = Field(default=0, description="越大越优先")
    label: str = ""


class QueryPlan(BaseModel):
    """搜索计划"""

    city: str
    target_size: int = DEFAULT_MAX_PLACES
    tasks: list[SearchTask] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    preferred_keywords: list[str] = Field(default_factory=list)
    seed_names: list[str] = Field(default_factory=list)
    include_indoor: bool = True
    include_outdoor: bool = True
    with_kids: bool = False
    with_elderly: bool = False
    travel_style: str = TravelStyle.RELAXED.value


class CandidatePlace(BaseModel):
    """候选地点（给 Agent / 编排使用）"""

    place_id: str
    name: str
    category: str = "景点"
    address: str = ""
    coordinate: Optional[Coordinate] = None
    district: Optional[str] = None
    business_area: str = ""
    tags: list[str] = Field(default_factory=list)
    type_code: str = ""
    rating: Optional[float] = None
    telephone: str = ""
    opening_hours: str = ""
    distance: int = 0
    source: str = "amap"
    score: float = 0.0
    reason: str = ""

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "place_id": self.place_id,
            "name": self.name,
            "category": self.category,
            "address": self.address,
            "district": self.district,
            "tags": self.tags[:6],
            "score": round(self.score, 3),
        }


class CandidatePool(BaseModel):
    """候选池结果"""

    city: str
    places: list[CandidatePlace] = Field(default_factory=list)
    query_plan: Optional[QueryPlan] = None
    fetched_at: str = ""
    warnings: list[str] = Field(default_factory=list)
    cache_hits: int = 0
    raw_count: int = 0

    def to_prompt_items(self) -> list[dict[str, Any]]:
        return [p.to_prompt_dict() for p in self.places]


@dataclass
class PlaceCandidateConfig:
    """可测配置"""

    max_places: int = DEFAULT_MAX_PLACES
    per_task_limit: int = DEFAULT_PER_TASK_LIMIT
    bucket_cap: int = DEFAULT_BUCKET_CAP
    rate_limit_delay: float = RATE_LIMIT_DELAY
    max_concurrency: int = MAX_CONCURRENCY
    use_cache: bool = True
    cache_strategy: CacheStrategy = DEFAULT_CACHE_TTL_STRATEGY


# ---------------------------------------------------------------------------
# 5.3.2 搜索策略
# ---------------------------------------------------------------------------

def extract_seed_names_from_hints(hints: Sequence[str] | None, *, limit: int = 12) -> list[str]:
    """从 RAG 文本轻量抽取可能的景点名（不调 LLM）。"""
    if not hints:
        return []
    found: list[str] = []
    seen: set[str] = set()
    blob = "\n".join(h for h in hints if h)
    for pattern in _POI_NAME_PATTERNS:
        for m in pattern.finditer(blob):
            name = (m.group(1) or "").strip()
            name = re.sub(r"[*#`]", "", name).strip()
            if len(name) < 2 or len(name) > 20:
                continue
            if name in seen:
                continue
            # 过滤明显非地名
            if any(x in name for x in ("http", "预算", "天数", "建议", "注意")):
                continue
            seen.add(name)
            found.append(name)
            if len(found) >= limit:
                return found
    return found


def build_query_plan(
    request: TripRequest,
    *,
    rag_hints: Sequence[str] | None = None,
    max_places: int = DEFAULT_MAX_PLACES,
    per_task_limit: int = DEFAULT_PER_TASK_LIMIT,
) -> QueryPlan:
    """5.3.2 将 TripRequest 转为可执行搜索计划。"""
    days = max(1, (request.end_date - request.start_date).days + 1)
    target = min(
        max_places,
        max(12, days * request.max_places_per_day * 2),
    )

    style = getattr(request.travel_style, "value", request.travel_style)
    style_key = str(style)
    preferred = [k.strip() for k in (request.preferred_keywords or []) if k and k.strip()]
    excluded = [k.strip() for k in (request.excluded_keywords or []) if k and k.strip()]
    seeds = extract_seed_names_from_hints(rag_hints)

    tasks: list[SearchTask] = []

    # 用户偏好关键字（最高优先）
    for i, kw in enumerate(preferred[:6]):
        if any(ex in kw for ex in excluded):
            continue
        tasks.append(
            SearchTask(
                mode=SearchMode.KEYWORD,
                keywords=kw,
                limit=per_task_limit,
                priority=100 - i,
                label=f"preferred:{kw}",
            )
        )

    # RAG 种子名
    for i, name in enumerate(seeds[:8]):
        if any(ex in name for ex in excluded):
            continue
        tasks.append(
            SearchTask(
                mode=SearchMode.KEYWORD,
                keywords=name,
                limit=min(8, per_task_limit),
                priority=80 - i,
                label=f"seed:{name}",
            )
        )

    # 风格关键字
    for i, kw in enumerate(STYLE_KEYWORDS.get(style_key, STYLE_KEYWORDS[TravelStyle.RELAXED.value])):
        tasks.append(
            SearchTask(
                mode=SearchMode.KEYWORD,
                keywords=kw,
                types=TYPE_SCENIC if style_key != TravelStyle.FOODIE.value else None,
                limit=per_task_limit,
                priority=50 - i,
                label=f"style_kw:{kw}",
            )
        )

    # 风格类型码
    for i, tcode in enumerate(STYLE_TYPES.get(style_key, [TYPE_SCENIC])):
        tasks.append(
            SearchTask(
                mode=SearchMode.TYPES,
                types=tcode,
                keywords=request.destination,
                limit=per_task_limit,
                priority=40 - i,
                label=f"style_type:{tcode}",
            )
        )

    # 特殊人群补充
    if request.with_kids:
        tasks.append(
            SearchTask(
                mode=SearchMode.KEYWORD,
                keywords="亲子",
                limit=per_task_limit,
                priority=45,
                label="flag:kids",
            )
        )
    if request.with_elderly:
        tasks.append(
            SearchTask(
                mode=SearchMode.KEYWORD,
                keywords="休闲公园",
                limit=per_task_limit,
                priority=44,
                label="flag:elderly",
            )
        )

    # 城市底盘：风景名胜 + 热门
    tasks.append(
        SearchTask(
            mode=SearchMode.KEYWORD,
            keywords="热门景点",
            types=TYPE_SCENIC,
            limit=per_task_limit,
            priority=20,
            label="base:hot",
        )
    )

    # 美食风格额外餐饮
    if style_key == TravelStyle.FOODIE.value or any("美食" in k or "吃" in k for k in preferred):
        tasks.append(
            SearchTask(
                mode=SearchMode.TYPES,
                types=TYPE_FOOD,
                keywords="特色",
                limit=per_task_limit,
                priority=35,
                label="food:types",
            )
        )

    # 去重同 label/keywords
    deduped: list[SearchTask] = []
    seen_keys: set[str] = set()
    for t in sorted(tasks, key=lambda x: -x.priority):
        key = f"{t.mode.value}|{t.keywords or ''}|{t.types or ''}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(t)

    return QueryPlan(
        city=request.destination.strip(),
        target_size=target,
        tasks=deduped,
        excluded_keywords=excluded,
        preferred_keywords=preferred,
        seed_names=seeds,
        include_indoor=request.include_indoor,
        include_outdoor=request.include_outdoor,
        with_kids=request.with_kids,
        with_elderly=request.with_elderly,
        travel_style=style_key,
    )


# ---------------------------------------------------------------------------
# 5.3.4 过滤 / 打分（纯函数，便于单测）
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip()).lower()


def _category_from_poi(poi: POIInfo) -> str:
    t = (poi.type or "").lower()
    if any(x in t for x in ("餐", "食", "咖啡", "酒吧")):
        return "餐厅"
    if any(x in t for x in ("酒店", "宾馆", "旅馆", "民宿")):
        return "酒店"
    return "景点"


def poi_to_candidate(poi: POIInfo, *, source: str = "amap") -> Optional[CandidatePlace]:
    name = (poi.name or "").strip()
    if not name:
        return None
    place_id = (poi.id or "").strip() or f"name-{hashlib.md5(name.encode()).hexdigest()[:12]}"
    tags = [x for x in re.split(r"[,;|，、]", poi.tag or "") if x.strip()]
    if poi.type:
        tags.append(poi.type.split(";")[0] if ";" in poi.type else poi.type)
    return CandidatePlace(
        place_id=place_id,
        name=name,
        category=_category_from_poi(poi),
        address=poi.address or "",
        coordinate=poi.location,
        district=None,
        business_area=poi.business_area or "",
        tags=[t.strip() for t in tags if t.strip()][:8],
        type_code=poi.type_code or "",
        rating=poi.rating,
        telephone=poi.telephone or "",
        opening_hours=poi.opening_hours or "",
        distance=int(poi.distance or 0),
        source=source,
    )


def _is_non_travel(place: CandidatePlace) -> bool:
    blob = f"{place.name}{' '.join(place.tags)}{place.address}"
    return any(h in blob for h in NON_TRAVEL_TYPE_HINTS)


def _indoor_outdoor_label(place: CandidatePlace) -> str:
    blob = f"{place.name}{' '.join(place.tags)}"
    indoor = any(h in blob for h in INDOOR_HINTS)
    outdoor = any(h in blob for h in OUTDOOR_HINTS)
    if indoor and not outdoor:
        return "indoor"
    if outdoor and not indoor:
        return "outdoor"
    return "unknown"


def score_candidate(place: CandidatePlace, plan: QueryPlan) -> tuple[float, str]:
    """返回 (score, reason)。"""
    score = 1.0
    reasons: list[str] = []
    blob = f"{place.name} {' '.join(place.tags)} {place.address}".lower()

    for kw in plan.preferred_keywords:
        if kw.lower() in blob:
            score += 3.0
            reasons.append(f"偏好:{kw}")

    for seed in plan.seed_names:
        if seed in place.name or place.name in seed:
            score += 4.0
            reasons.append("RAG种子")
            break

    style_kws = STYLE_KEYWORDS.get(plan.travel_style, [])
    for kw in style_kws:
        if kw.lower() in blob:
            score += 1.5
            reasons.append(f"风格:{kw}")
            break

    if place.rating is not None:
        score += float(place.rating)
        reasons.append(f"评分{place.rating}")

    if place.business_area:
        score += 0.5

    if place.coordinate is not None:
        score += 0.8
    else:
        score -= 2.0
        reasons.append("无坐标")

    io = _indoor_outdoor_label(place)
    if io == "indoor" and not plan.include_indoor:
        score -= 5.0
        reasons.append("室内冲突")
    if io == "outdoor" and not plan.include_outdoor:
        score -= 5.0
        reasons.append("室外冲突")

    if plan.with_kids and any(x in blob for x in ("亲子", "儿童", "乐园")):
        score += 1.2
        reasons.append("亲子友好")
    if plan.with_elderly and any(x in blob for x in ("休闲", "公园", "博物馆")):
        score += 0.8
        reasons.append("适老")

    return score, "；".join(reasons[:4])


def filter_and_rank(
    candidates: Sequence[CandidatePlace],
    plan: QueryPlan,
    *,
    max_places: int = DEFAULT_MAX_PLACES,
    bucket_cap: int = DEFAULT_BUCKET_CAP,
) -> tuple[list[CandidatePlace], list[str]]:
    """5.3.4 去重、过滤、打分、多样性裁剪。"""
    warnings: list[str] = []
    by_name: dict[str, CandidatePlace] = {}

    for c in candidates:
        if not c.name:
            continue
        if _is_non_travel(c):
            continue
        if any(ex in c.name or ex in " ".join(c.tags) for ex in plan.excluded_keywords):
            continue
        io = _indoor_outdoor_label(c)
        if io == "indoor" and not plan.include_indoor:
            continue
        if io == "outdoor" and not plan.include_outdoor:
            continue

        key = _normalize_name(c.name)
        scored, reason = score_candidate(c, plan)
        c = c.model_copy(update={"score": scored, "reason": reason})

        prev = by_name.get(key)
        if prev is None:
            by_name[key] = c
            continue
        # 保留更高分；同分优先有坐标
        better = c
        if prev.score > c.score:
            better = prev
        elif prev.score == c.score:
            if prev.coordinate is not None and c.coordinate is None:
                better = prev
        by_name[key] = better

    ranked = sorted(by_name.values(), key=lambda x: (-x.score, x.name))
    if not ranked:
        warnings.append("过滤后候选为空")
        return [], warnings

    # 按商圈/区粗分桶
    buckets: dict[str, list[CandidatePlace]] = {}
    for p in ranked:
        bucket = (p.business_area or p.district or "其他").strip() or "其他"
        buckets.setdefault(bucket, []).append(p)

    selected: list[CandidatePlace] = []
    selected_ids: set[str] = set()
    # 轮询各桶，保证多样性
    while len(selected) < max_places:
        progressed = False
        for bucket, items in buckets.items():
            taken = sum(1 for s in selected if (s.business_area or s.district or "其他") == bucket)
            if taken >= bucket_cap:
                continue
            for item in items:
                if item.place_id in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(item.place_id)
                progressed = True
                break
            if len(selected) >= max_places:
                break
        if not progressed:
            break

    # 不足时按全局排名补齐
    if len(selected) < min(max_places, len(ranked)):
        for p in ranked:
            if p.place_id in selected_ids:
                continue
            selected.append(p)
            selected_ids.add(p.place_id)
            if len(selected) >= max_places:
                break

    selected.sort(key=lambda x: (-x.score, x.name))
    if len(ranked) > len(selected):
        warnings.append(f"已从 {len(ranked)} 条裁剪为 {len(selected)} 条")
    return selected[:max_places], warnings


# ---------------------------------------------------------------------------
# 5.3.1 / 5.3.3 / 5.3.5 PlaceCandidateService
# ---------------------------------------------------------------------------

class PlaceCandidateService:
    """动态 POI 候选池服务。"""

    def __init__(
        self,
        map_service: Optional[MapService] = None,
        config: Optional[PlaceCandidateConfig] = None,
        cache: Any = None,
    ):
        self._map = map_service
        self.config = config or PlaceCandidateConfig()
        self._cache = cache if cache is not None else cache_service
        self._last_request_time = 0.0

    def _ensure_map(self) -> MapService:
        if self._map is not None:
            return self._map
        existing = get_map_service()
        if existing is not None:
            self._map = existing
            return existing
        self._map = init_map_service(api_key=settings.AMAP_API_KEY)
        return self._map

    # ---------- 5.3.2 ----------

    def build_query_plan(
        self,
        request: TripRequest,
        *,
        rag_hints: Sequence[str] | None = None,
        max_places: Optional[int] = None,
    ) -> QueryPlan:
        return build_query_plan(
            request,
            rag_hints=rag_hints,
            max_places=max_places or self.config.max_places,
            per_task_limit=self.config.per_task_limit,
        )

    # ---------- 5.3.3 拉取 ----------

    def _cache_key(self, city: str, task: SearchTask) -> str:
        raw = json.dumps(
            {
                "city": city,
                "mode": task.mode.value,
                "kw": task.keywords or "",
                "types": task.types or "",
                "limit": task.limit,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return f"poi:{city}:{digest}"

    def _pois_from_cache(self, key: str) -> Optional[list[dict[str, Any]]]:
        if not self.config.use_cache:
            return None
        return self._cache.get(key, namespace=CacheNamespace.PLACE)

    def _pois_to_cache(self, key: str, pois: list[dict[str, Any]]) -> None:
        if not self.config.use_cache:
            return
        self._cache.set(
            key,
            pois,
            namespace=CacheNamespace.PLACE,
            strategy=self.config.cache_strategy,
        )

    @staticmethod
    def _serialize_poi(poi: POIInfo) -> dict[str, Any]:
        loc = None
        if poi.location is not None:
            loc = {
                "latitude": poi.location.latitude,
                "longitude": poi.location.longitude,
            }
        return {
            "id": poi.id,
            "name": poi.name,
            "type": poi.type,
            "type_code": poi.type_code,
            "address": poi.address,
            "location": loc,
            "telephone": poi.telephone,
            "distance": poi.distance,
            "business_area": poi.business_area,
            "city": poi.city,
            "tag": poi.tag,
            "rating": poi.rating,
            "cost": poi.cost,
            "opening_hours": poi.opening_hours,
        }

    @staticmethod
    def _deserialize_poi(data: dict[str, Any]) -> POIInfo:
        loc = data.get("location")
        coordinate = None
        if isinstance(loc, dict) and loc.get("latitude") is not None:
            coordinate = Coordinate(
                latitude=float(loc["latitude"]),
                longitude=float(loc["longitude"]),
            )
        return POIInfo(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=data.get("type", ""),
            type_code=data.get("type_code", ""),
            address=data.get("address", ""),
            location=coordinate,
            telephone=data.get("telephone", ""),
            distance=int(data.get("distance") or 0),
            business_area=data.get("business_area", ""),
            city=data.get("city", ""),
            tag=data.get("tag", ""),
            rating=data.get("rating"),
            cost=data.get("cost"),
            opening_hours=data.get("opening_hours", ""),
            info="OK",
            status=True,
        )

    async def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        delay = self.config.rate_limit_delay
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_request_time = time.time()

    async def _resolve_city_center(
        self, city: str
    ) -> Optional[tuple[float, float]]:
        """返回 (lng, lat)。"""
        try:
            await self._rate_limit()
            districts = await self._ensure_map().get_district(city, subdistrict=0)
            if districts and districts[0].center is not None:
                c = districts[0].center
                return (c.longitude, c.latitude)
        except Exception as e:
            logger.warning(f"获取城市中心失败 [{city}]: {e}")
        return None

    async def _execute_task(
        self,
        city: str,
        task: SearchTask,
        *,
        city_center: Optional[tuple[float, float]],
    ) -> tuple[list[POIInfo], bool, Optional[str]]:
        """返回 (pois, cache_hit, error)。"""
        cache_key = self._cache_key(city, task)
        cached = self._pois_from_cache(cache_key)
        if cached is not None:
            return [self._deserialize_poi(x) for x in cached], True, None

        map_svc = self._ensure_map()
        try:
            await self._rate_limit()
            result: POISearchResult
            if task.mode == SearchMode.NEARBY:
                if not city_center:
                    return [], False, "无城市中心，跳过周边搜索"
                result = await map_svc.search_nearby(
                    location=city_center,
                    keywords=[task.keywords] if task.keywords else None,
                    types=task.types,
                    page_size=task.limit,
                    radius=8000,
                )
            elif task.mode == SearchMode.TYPES:
                result = await map_svc.search_poi(
                    keywords=task.keywords or city,
                    city=city,
                    citylimit=True,
                    types=task.types,
                    page_size=task.limit,
                )
            else:
                result = await map_svc.search_poi(
                    keywords=task.keywords or city,
                    city=city,
                    citylimit=True,
                    types=task.types,
                    page_size=task.limit,
                )

            if not result.status:
                return [], False, result.info or "搜索失败"

            pois = list(result.pois or [])[: task.limit]
            self._pois_to_cache(cache_key, [self._serialize_poi(p) for p in pois])
            return pois, False, None
        except Exception as e:
            logger.error(f"POI 任务失败 [{task.label}]: {e}")
            return [], False, str(e)

    async def fetch_raw(
        self,
        plan: QueryPlan,
        *,
        include_nearby: bool = True,
    ) -> tuple[list[POIInfo], list[str], int]:
        """5.3.3 多路拉取。返回 (pois, warnings, cache_hits)。"""
        warnings: list[str] = []
        cache_hits = 0
        city_center: Optional[tuple[float, float]] = None

        tasks = list(plan.tasks)
        if include_nearby:
            # 动态追加一路周边热门（有中心点时）
            city_center = await self._resolve_city_center(plan.city)
            if city_center:
                tasks.append(
                    SearchTask(
                        mode=SearchMode.NEARBY,
                        keywords="景点",
                        types=TYPE_SCENIC,
                        limit=self.config.per_task_limit,
                        priority=15,
                        label="nearby:scenic",
                    )
                )
            else:
                warnings.append("未解析到城市中心，跳过周边搜索")

        sem = asyncio.Semaphore(self.config.max_concurrency)
        results: list[POIInfo] = []
        errors = 0

        async def _run(task: SearchTask) -> None:
            nonlocal cache_hits, errors
            async with sem:
                pois, hit, err = await self._execute_task(
                    plan.city, task, city_center=city_center
                )
                if hit:
                    cache_hits += 1
                if err:
                    errors += 1
                    warnings.append(f"{task.label}: {err}")
                else:
                    results.extend(pois)

        await asyncio.gather(*[_run(t) for t in tasks])

        if not results and errors:
            raise CandidateFetchError(
                f"全部搜索失败（{errors} 路），城市={plan.city}"
            )
        if not results:
            warnings.append("地图未返回任何 POI")
        return results, warnings, cache_hits

    # ---------- 5.3.5 对外 API ----------

    async def build_pool(
        self,
        request: TripRequest,
        *,
        rag_hints: Sequence[str] | None = None,
        max_places: Optional[int] = None,
        include_nearby: bool = True,
    ) -> CandidatePool:
        """构建候选池；空池降级为空列表 + warnings，不拖垮主流程。"""
        limit = max_places or self.config.max_places
        plan = self.build_query_plan(request, rag_hints=rag_hints, max_places=limit)
        warnings: list[str] = []
        raw_pois: list[POIInfo] = []
        cache_hits = 0

        try:
            raw_pois, fetch_warnings, cache_hits = await self.fetch_raw(
                plan, include_nearby=include_nearby
            )
            warnings.extend(fetch_warnings)
        except CandidateFetchError as e:
            warnings.append(str(e))
            logger.warning(f"候选池拉取失败，返回空池: {e}")

        candidates: list[CandidatePlace] = []
        for poi in raw_pois:
            c = poi_to_candidate(poi)
            if c:
                candidates.append(c)

        ranked, rank_warnings = filter_and_rank(
            candidates,
            plan,
            max_places=limit,
            bucket_cap=self.config.bucket_cap,
        )
        warnings.extend(rank_warnings)

        return CandidatePool(
            city=plan.city,
            places=ranked,
            query_plan=plan,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            warnings=warnings,
            cache_hits=cache_hits,
            raw_count=len(raw_pois),
        )

    def build_pool_sync(
        self,
        request: TripRequest,
        *,
        rag_hints: Sequence[str] | None = None,
        max_places: Optional[int] = None,
        include_nearby: bool = True,
    ) -> CandidatePool:
        """同步包装，供非 async 编排（如临时脚本）使用。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            raise CandidateError(
                "当前已在事件循环中，请使用 await build_pool()，勿调用 build_pool_sync()"
            )
        return asyncio.run(
            self.build_pool(
                request,
                rag_hints=rag_hints,
                max_places=max_places,
                include_nearby=include_nearby,
            )
        )

    @staticmethod
    def to_prompt_items(pool: CandidatePool) -> list[dict[str, Any]]:
        return pool.to_prompt_items()

    async def resolve_name(
        self,
        city: str,
        name: str,
        *,
        limit: int = 5,
    ) -> Optional[CandidatePlace]:
        """单点名称解析/纠名，供 6.1 或 edit_day 使用。"""
        name = (name or "").strip()
        city = (city or "").strip()
        if not name or not city:
            return None

        task = SearchTask(
            mode=SearchMode.KEYWORD,
            keywords=name,
            limit=limit,
            priority=100,
            label=f"resolve:{name}",
        )
        pois, _, err = await self._execute_task(city, task, city_center=None)
        if err or not pois:
            return None

        # 精确/包含优先
        best: Optional[POIInfo] = None
        for poi in pois:
            if poi.name == name:
                best = poi
                break
            if name in (poi.name or "") or (poi.name or "") in name:
                best = poi
                break
        if best is None:
            best = pois[0]
        return poi_to_candidate(best)


# 模块单例
place_candidate_service = PlaceCandidateService()
