"""
智旅云图 - RAG 工具（Agent 可调用）

将第四阶段 Retriever 封装为智谱/OpenAI 兼容的 function calling 工具。

功能模块：
- 5.1.1 工具契约：Pydantic 入参/出参 + as_openai_tools()
- 5.1.2 检索适配：search_guides() 调用 Retriever，城市/类别映射
- 5.1.3 上下文压缩：按 token 预算拼 RAGContext，带引用编号
- 5.1.4 多路编排与降级：行程类多路检索、空结果放宽过滤
"""

from __future__ import annotations

import json
import re
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Union

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.rag.guide_catalog import guide_catalog

if TYPE_CHECKING:
    from app.rag.retriever import Retriever

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TOOL_NAME = "search_travel_guides"
TOOL_DESCRIPTION = (
    "从本地旅游攻略知识库检索景点、餐饮、住宿、行程片段，用于规划行程。"
    "规划行程、推荐美食或景点前应先调用。城市未知时不要编造。"
)

# 沉淀城市白名单：由 guide_catalog 动态生成（6.2 迁移）
ALLOWED_CITIES = tuple(guide_catalog.list_preset_cities())
MAX_TOP_K = 8
DEFAULT_TOP_K = 5
MAX_TOTAL_TOKENS = 3000
MAX_CHUNK_CHARS = 400  # 约 500–600 tokens 量级（中文）

# 意图码 → 入库 category（中文）
INTENT_TO_CATEGORY: dict[str, str] = {
    "scenic_spot": "景点",
    "dining": "餐饮",
    "accommodation": "住宿",
    "itinerary": "行程",
}

CATEGORY_WEIGHT: dict[str, float] = {
    "行程": 1.15,
    "景点": 1.10,
    "餐饮": 1.05,
    "住宿": 1.0,
}

# 城市别名归一化已迁移至 guide_catalog.resolve_city()（6.2）


# ---------------------------------------------------------------------------
# 5.1.1 Pydantic 契约
# ---------------------------------------------------------------------------

class GuideCity(str, Enum):
    BEIJING = "北京"
    DALI = "大理"
    CHENGDU = "成都"
    XIAN = "西安"
    XIAMEN = "厦门"
    SANYA = "三亚"


class GuideCategory(str, Enum):
    SCENIC = "景点"
    DINING = "餐饮"
    STAY = "住宿"
    ITINERARY = "行程"


class SearchGuidesArgs(BaseModel):
    """Agent 工具入参"""

    query: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="检索用的自然语言，需含目的地和诉求",
    )
    city: Optional[GuideCity] = Field(
        default=None,
        description="目的地城市；不确定就不要填",
    )
    category: Optional[GuideCategory] = Field(
        default=None,
        description="只查某一类时填写：景点/餐饮/住宿/行程",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description="返回片段数量，默认 5，最大 8",
    )
    use_cache: bool = Field(default=True, description="是否使用检索缓存")
    use_rerank: bool = Field(default=True, description="是否使用重排序")

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query 不能为空")
        return v


class RAGChunk(BaseModel):
    """单条检索片段（压缩后）"""

    rank: int = Field(..., description="引用编号，从 1 起")
    city: Optional[str] = None
    category: Optional[str] = None
    section: Optional[str] = None
    content: str
    score: float = 0.0
    source_file: Optional[str] = None


class RAGQueryInfo(BaseModel):
    original: str
    city: Optional[str] = None
    days: Optional[int] = None
    intent: Optional[str] = None
    confidence: float = 0.0


class RAGToolStats(BaseModel):
    total_ms: float = 0.0
    cached: bool = False
    chunk_count: int = 0
    approx_tokens: int = 0
    degraded: bool = False
    paths_used: int = 1


class RAGToolResult(BaseModel):
    """工具出参，序列化后作为 tool 消息回传给 LLM"""

    ok: bool = True
    query_info: RAGQueryInfo
    chunks: list[RAGChunk] = Field(default_factory=list)
    context_text: str = ""
    stats: RAGToolStats = Field(default_factory=RAGToolStats)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    """中文粗估 token：len / 1.5"""
    if not text:
        return 0
    return max(1, int(len(text) / 1.5))


def _normalize_city(city: Optional[str]) -> Optional[str]:
    """将城市规范为沉淀城市之一；非法则返回 None（不硬过滤）

    6.2 迁移：委托 guide_catalog.resolve_city() 做白名单校验 + 轻量归一化。
    """
    return guide_catalog.resolve_city(city)


def _normalize_category(category: Optional[str]) -> Optional[str]:
    """英文意图码 / 中文类别 → 入库 category"""
    if not category:
        return None
    category = category.strip()
    if category in INTENT_TO_CATEGORY:
        return INTENT_TO_CATEGORY[category]
    valid = {c.value for c in GuideCategory}
    if category in valid:
        return category
    # 容错：餐厅→餐饮
    aliases = {
        "餐厅": "餐饮",
        "美食": "餐饮",
        "酒店": "住宿",
        "民宿": "住宿",
        "景区": "景点",
        "路线": "行程",
    }
    return aliases.get(category)


def _doc_score(doc: dict) -> float:
    if "rerank_score" in doc and doc["rerank_score"] is not None:
        return float(doc["rerank_score"])
    if "rrf_score" in doc and doc["rrf_score"] is not None:
        return float(doc["rrf_score"])
    if "similarity" in doc and doc["similarity"] is not None:
        return float(doc["similarity"])
    return 0.0


def _doc_key(doc: dict) -> str:
    meta = doc.get("metadata") or {}
    source = meta.get("source_file") or meta.get("source") or ""
    section = meta.get("section") or meta.get("subsection") or ""
    content = (doc.get("document") or doc.get("content") or "")[:80]
    return f"{source}|{section}|{content}"


def _truncate_content(text: str, max_chars: int = MAX_CHUNK_CHARS) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_chars:
        return text
    # 尽量在句号处截断
    cut = text[:max_chars]
    for sep in ("。", "！", "？", "；", "\n"):
        idx = cut.rfind(sep)
        if idx >= max_chars // 2:
            return cut[: idx + 1]
    return cut + "…"


def _style_label(style: Any) -> str:
    if style is None:
        return ""
    value = getattr(style, "value", style)
    mapping = {
        "relaxed": "休闲",
        "compact": "紧凑",
        "adventure": "探险",
        "cultural": "文化",
        "foodie": "美食",
    }
    return mapping.get(str(value), str(value))


# ---------------------------------------------------------------------------
# RAGTool
# ---------------------------------------------------------------------------

class RAGTool:
    """
    Agent 侧 RAG 工具。

    - as_openai_tools(): 智谱 tools 说明书
    - execute(): function_call 分发入口
    - search_guides(): 单次/多路检索 + 压缩
    - search_for_trip(): 从 TripRequest 构造查询（非 LLM 路径）
    """

    def __init__(self, retriever: Optional[Any] = None):
        self._retriever = retriever

    @property
    def retriever(self) -> Any:
        if self._retriever is None:
            from app.rag.retriever import retriever as default_retriever

            self._retriever = default_retriever
        return self._retriever

    @retriever.setter
    def retriever(self, value: Any) -> None:
        self._retriever = value

    # ---------- 5.1.1 Schema ----------

    def as_openai_tools(self) -> list[dict]:
        """生成智谱/OpenAI 兼容的 tools 数组（说明书，不执行检索）"""
        schema = SearchGuidesArgs.model_json_schema()
        # 扁平 schema：去掉 title/$defs，展开 $ref（若有）
        schema = self._flatten_json_schema(schema)
        return [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "parameters": schema,
                },
            }
        ]

    @staticmethod
    def _flatten_json_schema(schema: dict) -> dict:
        """去掉 Pydantic 多余字段，内联 $defs 引用，便于智谱解析"""
        defs = schema.pop("$defs", {}) or schema.pop("definitions", {}) or {}
        schema.pop("title", None)

        def resolve(node: Any) -> Any:
            if isinstance(node, dict):
                if "$ref" in node:
                    ref = node["$ref"]
                    name = ref.rsplit("/", 1)[-1]
                    if name in defs:
                        return resolve(defs[name])
                    return node
                return {k: resolve(v) for k, v in node.items() if k not in ("title",)}
            if isinstance(node, list):
                return [resolve(x) for x in node]
            return node

        return resolve(schema)

    def execute(self, name: str, arguments: Union[str, dict]) -> str:
        """
        function_call 分发入口。

        Returns:
            JSON 字符串（RAGToolResult），作为 tool 消息 content
        """
        if name != TOOL_NAME:
            result = RAGToolResult(
                ok=False,
                query_info=RAGQueryInfo(original=""),
                error=f"未知工具: {name}",
            )
            return result.model_dump_json(ensure_ascii=False)

        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(raw, dict):
                raise ValueError("arguments 必须是 JSON 对象")
            # top_k 超限时钳制，避免校验失败直接拒绝对话
            if "top_k" in raw and isinstance(raw["top_k"], (int, float)):
                raw["top_k"] = int(max(1, min(MAX_TOP_K, int(raw["top_k"]))))
            # city 非法：不硬拒，改为 None 并 warning
            if raw.get("city"):
                normalized = _normalize_city(str(raw["city"]))
                if normalized:
                    raw["city"] = normalized
                else:
                    logger.warning(f"非法城市，忽略过滤: {raw.get('city')}")
                    raw["city"] = None
            if raw.get("category"):
                normalized_cat = _normalize_category(str(raw["category"]))
                raw["category"] = normalized_cat

            args = SearchGuidesArgs.model_validate(raw)
            result = self.search_guides(args)
            return result.model_dump_json(ensure_ascii=False)
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"RAG 工具参数校验失败: {e}")
            result = RAGToolResult(
                ok=False,
                query_info=RAGQueryInfo(original=str(arguments)[:200]),
                error=f"参数无效: {e}",
            )
            return result.model_dump_json(ensure_ascii=False)
        except Exception as e:
            logger.error(f"RAG 工具执行失败: {e}")
            result = RAGToolResult(
                ok=False,
                query_info=RAGQueryInfo(original=""),
                error=f"检索失败: {e}",
            )
            return result.model_dump_json(ensure_ascii=False)

    # ---------- 5.1.2 / 5.1.4 检索 ----------

    def search_guides(
        self,
        args: Optional[SearchGuidesArgs] = None,
        *,
        query: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        use_cache: bool = True,
        use_rerank: bool = True,
        force_multi_path: bool = False,
    ) -> RAGToolResult:
        """
        执行检索并压缩为 Agent 可用上下文。

        未指定 category 且意图为 itinerary（或 force_multi_path）时走多路。
        """
        start = time.time()
        if args is not None:
            query = args.query
            city = args.city.value if args.city else city
            category = args.category.value if args.category else category
            top_k = args.top_k
            use_cache = args.use_cache
            use_rerank = args.use_rerank

        if not query or not str(query).strip():
            return RAGToolResult(
                ok=False,
                query_info=RAGQueryInfo(original=""),
                error="query 不能为空",
            )

        query = str(query).strip()
        city = _normalize_city(city)
        category = _normalize_category(category)
        top_k = max(1, min(MAX_TOP_K, int(top_k)))

        try:
            # 先做一次轻量预检：用 retriever 的预处理拿 intent（避免多路时重复意图检测成本过高——
            # 仍调用完整 retrieve，但用第一次结果的 query_info）
            single = self._retrieve_with_fallback(
                query=query,
                city=city,
                category=category,
                use_cache=use_cache,
                use_rerank=use_rerank,
                top_k=top_k,
            )

            intent = (single.get("query_info") or {}).get("intent")
            use_multi = force_multi_path or (
                category is None and intent == "itinerary"
            )

            degraded = bool(single.get("_degraded"))
            paths_used = 1
            raw_docs = list(single.get("results") or [])
            query_info_raw = single.get("query_info") or {}
            cached = bool(single.get("cached"))

            if use_multi:
                multi_docs, multi_degraded, paths_used = self._multi_path_retrieve(
                    query=query,
                    city=city or query_info_raw.get("city"),
                    days=query_info_raw.get("days"),
                    use_cache=use_cache,
                    use_rerank=use_rerank,
                    top_k=top_k,
                )
                raw_docs = multi_docs
                degraded = degraded or multi_degraded
                # 多路通常不命中同一缓存键
                cached = False

            chunks, context_text, approx_tokens = self.format_context(
                raw_docs,
                query_info=query_info_raw,
                top_k=top_k,
                cached=cached,
            )

            degraded = degraded or (len(chunks) == 0)
            error = None
            if not chunks:
                error = "知识库暂无足够攻略，请结合地图POI"

            elapsed = round((time.time() - start) * 1000, 2)
            return RAGToolResult(
                ok=True,
                query_info=RAGQueryInfo(
                    original=query_info_raw.get("original") or query,
                    city=query_info_raw.get("city") or city,
                    days=query_info_raw.get("days"),
                    intent=intent,
                    confidence=float(query_info_raw.get("confidence") or 0),
                ),
                chunks=chunks,
                context_text=context_text,
                stats=RAGToolStats(
                    total_ms=elapsed,
                    cached=cached,
                    chunk_count=len(chunks),
                    approx_tokens=approx_tokens,
                    degraded=degraded,
                    paths_used=paths_used,
                ),
                error=error,
            )
        except Exception as e:
            logger.error(f"search_guides 失败: {e}")
            return RAGToolResult(
                ok=False,
                query_info=RAGQueryInfo(original=query),
                error=f"检索失败: {e}",
                stats=RAGToolStats(
                    total_ms=round((time.time() - start) * 1000, 2),
                    degraded=True,
                ),
            )

    def search_for_trip(self, request: Any) -> RAGToolResult:
        """
        从 TripRequest（或兼容对象）构造查询，走多路检索。
        供 5.2 / 6.1 非 Tool-Call 路径使用。
        """
        destination = getattr(request, "destination", None) or ""
        destination = _normalize_city(str(destination)) or str(destination).strip()

        start_date = getattr(request, "start_date", None)
        end_date = getattr(request, "end_date", None)
        days = None
        try:
            if start_date and end_date:
                days = (end_date - start_date).days + 1
        except Exception:
            days = None
        days = days or 3

        style = _style_label(getattr(request, "travel_style", None))
        preferred = getattr(request, "preferred_keywords", None) or []
        excluded = getattr(request, "excluded_keywords", None) or []

        parts = [destination, f"{days}天"]
        if style:
            parts.append(style)
        parts.extend(["行程", "景点", "餐饮", "住宿"])
        if preferred:
            parts.append("偏好：" + "、".join(str(x) for x in preferred[:8]))
        if excluded:
            parts.append("避开：" + "、".join(str(x) for x in excluded[:8]))

        query = " ".join(parts)
        return self.search_guides(
            query=query,
            city=destination if destination in ALLOWED_CITIES else None,
            category=None,
            top_k=DEFAULT_TOP_K,
            force_multi_path=True,
        )

    # ---------- 降级与多路 ----------

    def _retrieve_with_fallback(
        self,
        query: str,
        city: Optional[str],
        category: Optional[str],
        use_cache: bool,
        use_rerank: bool,
        top_k: int,
    ) -> dict:
        """
        空结果降级阶梯：
        1) 去掉 category
        2) 去掉 city（仅当 query 含城市语义）
        3) 关闭 rerank
        """
        degraded = False
        result = self.retriever.retrieve(
            query=query,
            city=city,
            category=category,
            use_cache=use_cache,
            use_rerank=use_rerank,
            top_k=top_k,
        )
        if result.get("results"):
            result["_degraded"] = False
            return result

        degraded = True
        if category:
            logger.info("RAG 降级: 去掉 category 重试")
            result = self.retriever.retrieve(
                query=query,
                city=city,
                category=None,
                use_cache=use_cache,
                use_rerank=use_rerank,
                top_k=top_k,
            )
            if result.get("results"):
                result["_degraded"] = True
                return result

        # 仅当 query 能抽出城市时才放开 city，避免串城
        query_city = self.retriever.preprocessor.extract_city(query)
        if city and query_city:
            logger.info("RAG 降级: 去掉 city 重试")
            result = self.retriever.retrieve(
                query=query,
                city=None,
                category=None,
                use_cache=use_cache,
                use_rerank=use_rerank,
                top_k=top_k,
            )
            if result.get("results"):
                result["_degraded"] = True
                return result

        if use_rerank:
            logger.info("RAG 降级: 关闭 rerank 重试")
            result = self.retriever.retrieve(
                query=query,
                city=city,
                category=None,
                use_cache=use_cache,
                use_rerank=False,
                top_k=top_k,
            )
            result["_degraded"] = True
            return result

        result["_degraded"] = degraded
        return result

    def _multi_path_retrieve(
        self,
        query: str,
        city: Optional[str],
        days: Optional[int],
        use_cache: bool,
        use_rerank: bool,
        top_k: int,
    ) -> tuple[list[dict], bool, int]:
        """行程类最多 4 路检索，交错融合"""
        city_label = city or ""
        days_label = f"{days}日" if days else ""
        paths = [
            (f"{city_label}{days_label}经典行程".strip() or query, "行程"),
            (f"{city_label} 核心景点 必去".strip(), "景点"),
            (f"{city_label} 美食 餐厅 小吃".strip(), "餐饮"),
            (f"{city_label} 住宿 酒店 民宿".strip(), "住宿"),
        ]

        all_docs: list[dict] = []
        degraded = False
        paths_used = 0

        for path_query, cat in paths:
            if not path_query.strip():
                continue
            paths_used += 1
            res = self._retrieve_with_fallback(
                query=path_query,
                city=city,
                category=cat,
                use_cache=use_cache,
                use_rerank=use_rerank,
                top_k=top_k,
            )
            degraded = degraded or bool(res.get("_degraded"))
            for doc in res.get("results") or []:
                # 标记来源路径，便于加权
                doc = dict(doc)
                meta = dict(doc.get("metadata") or {})
                if not meta.get("category"):
                    meta["category"] = cat
                doc["metadata"] = meta
                doc["_path_category"] = cat
                all_docs.append(doc)

        merged = self._merge_docs(all_docs, top_k=top_k * 2)
        return merged, degraded, paths_used

    def _merge_docs(self, docs: list[dict], top_k: int) -> list[dict]:
        """按 score × 类别权重去重融合"""
        best: dict[str, dict] = {}
        for doc in docs:
            key = _doc_key(doc)
            meta = doc.get("metadata") or {}
            cat = meta.get("category") or doc.get("_path_category") or ""
            score = _doc_score(doc) * CATEGORY_WEIGHT.get(cat, 1.0)
            doc = dict(doc)
            doc["_merge_score"] = score
            if key not in best or score > best[key].get("_merge_score", 0):
                best[key] = doc

        merged = sorted(best.values(), key=lambda d: d.get("_merge_score", 0), reverse=True)
        return merged[:top_k]

    # ---------- 5.1.3 压缩 ----------

    def format_context(
        self,
        docs: list[dict],
        query_info: Optional[dict] = None,
        top_k: int = DEFAULT_TOP_K,
        cached: bool = False,
    ) -> tuple[list[RAGChunk], str, int]:
        """
        去重、截断、按 token 预算拼 context_text。

        Returns:
            (chunks, context_text, approx_tokens)
        """
        query_info = query_info or {}
        # 去重
        seen: set[str] = set()
        cleaned: list[dict] = []
        for doc in docs:
            content = (doc.get("document") or doc.get("content") or "").strip()
            if not content:
                continue
            # 跳过过短/纯标题
            if len(content) < 8:
                continue
            key = _doc_key(doc)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(doc)

        # 按分数排序
        cleaned.sort(key=lambda d: d.get("_merge_score", _doc_score(d)), reverse=True)

        chunks: list[RAGChunk] = []
        lines: list[str] = []
        header = (
            f"【攻略检索】城市={query_info.get('city') or '未知'} "
            f"intent={query_info.get('intent') or 'unknown'} "
            f"confidence={float(query_info.get('confidence') or 0):.2f} "
            f"cached={str(cached).lower()}"
        )
        lines.append(header)
        used_tokens = _approx_tokens(header)

        for doc in cleaned:
            if len(chunks) >= top_k:
                break
            meta = doc.get("metadata") or {}
            content = _truncate_content(doc.get("document") or doc.get("content") or "")
            section = meta.get("subsection") or meta.get("section") or ""
            category = meta.get("category") or ""
            city = meta.get("city")
            source = meta.get("source_file") or meta.get("source") or ""
            score = float(doc.get("_merge_score", _doc_score(doc)))

            rank = len(chunks) + 1
            block_header = f"[{rank}][{category or '综合'}] {section or '片段'} · 来源:{source}"
            block = f"{block_header}\n{content}"
            block_tokens = _approx_tokens(block)
            if used_tokens + block_tokens > MAX_TOTAL_TOKENS and chunks:
                break

            chunk = RAGChunk(
                rank=rank,
                city=city,
                category=category or None,
                section=section or None,
                content=content,
                score=round(score, 4),
                source_file=source or None,
            )
            chunks.append(chunk)
            lines.append(block)
            used_tokens += block_tokens

        context_text = "\n\n".join(lines)
        return chunks, context_text, used_tokens


# 模块级单例
rag_tool = RAGTool()
