"""
智旅云图 - RAG 检索器模块
提供查询改写、意图识别、同义词扩展、重排序和结果缓存能力
"""

import os
import re
import json
import hashlib
import time
from typing import Optional, Any
from pathlib import Path

import redis
import yaml
from loguru import logger

from app.config import settings
from app.rag.guide_catalog import guide_catalog
from app.rag.vector_db import vector_db_service, hybrid_search_engine


class QueryPreprocessor:
    """查询预处理器 - 快速提取城市和天数"""

    # 6.2 迁移：城市正则由 guide_catalog 动态生成（沉淀 + 动态城市）
    CITY_PATTERN = guide_catalog.build_city_pattern()
    DAYS_PATTERNS = [
        r"(\d+)\s*天",
        r"(\d+)\s*日",
        r"三天|两日|四天|五天|六天|七天|一日|两日|三日|四日|五日|六日|七日",
    ]

    CHINESE_DAYS = {
        "一": 1, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "日": 1
    }

    def extract_city(self, query: str) -> Optional[str]:
        """提取城市名称"""
        match = re.search(self.CITY_PATTERN, query)
        return match.group(1) if match else None

    def extract_days(self, query: str) -> Optional[int]:
        """提取行程天数"""
        for pattern in self.DAYS_PATTERNS:
            match = re.search(pattern, query)
            if match:
                if match.lastindex and match.lastindex >= 1:
                    num_str = match.group(1)
                    return int(num_str) if num_str.isdigit() else self.CHINESE_DAYS.get(num_str, 3)
                elif match.lastindex is None:
                    word = match.group(0).replace("天", "").replace("日", "")
                    return self.CHINESE_DAYS.get(word, 3)
        return None

    def preprocess(self, query: str) -> dict:
        """
        预处理查询，快速提取基本信息

        Returns:
            {
                "original": 原始查询,
                "city": 城市或None,
                "days": 天数或None
            }
        """
        return {
            "original": query,
            "city": self.extract_city(query),
            "days": self.extract_days(query)
        }


class IntentDetector:
    """意图检测器 - 使用 LLM 识别用户意图"""

    SYSTEM_PROMPT = """你是一个旅游助手，负责分析用户的查询意图。

支持的意图类型：
- scenic_spot: 景点推荐（问哪里好玩、打卡地、景区）
- dining: 餐饮推荐（问吃什么、美食、餐厅、小吃）
- accommodation: 住宿推荐（问住哪里、酒店、民宿）
- itinerary: 行程规划（问几天、路线、安排、规划）

请分析用户查询，返回JSON格式结果：
{
    "primary_intent": "意图类型",
    "confidence": 0.0-1.0,
    "secondary_intents": ["其他可能的意图"],
    "supplementary_terms": ["补充查询词"]
}

注意事项：
- 只返回JSON，不要有其他内容
- confidence 表示主意图的置信度
- secondary_intents 列出其他可能的意图（可选）
- supplementary_terms 给出同义词或相关词（可选）
"""

    USER_PROMPT_TEMPLATE = "用户查询：{query}"

    def __init__(self):
        self._client = None
        self._initialized = False

    def _get_client(self):
        """获取 LLM 客户端"""
        if self._client is None:
            try:
                from zai import ZhipuAiClient
                self._client = ZhipuAiClient(api_key=settings.ZHIPU_API_KEY)
                self._initialized = True
            except ImportError:
                logger.warning("zai 未安装，意图检测将使用降级方案")
                self._initialized = False
                return None
        return self._client

    def detect(self, query: str) -> dict:
        """
        检测用户意图

        Args:
            query: 用户查询

        Returns:
            {
                "primary_intent": "意图类型",
                "confidence": float,
                "secondary_intents": [],
                "supplementary_terms": []
            }
        """
        if not self._initialized:
            self._get_client()

        if self._client is None:
            return self._fallback_detection(query)

        try:
            response = self._client.chat.completions.create(
                model=settings.ZHIPU_MODEL,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": self.USER_PROMPT_TEMPLATE.format(query=query)}
                ],
                temperature=0.1,
                max_tokens=1500
            )

            content = response.choices[0].message.content.strip() if response.choices[0].message.content else ""

            if not content:
                logger.error(f"LLM 返回空内容，原始响应: {response}")
                return self._fallback_detection(query)

            if content.startswith("```"):
                content = re.sub(r"```json\s*|\s*```", "", content)

            result = json.loads(content)

            return {
                "primary_intent": result.get("primary_intent", "itinerary"),
                "confidence": result.get("confidence", 0.5),
                "secondary_intents": result.get("secondary_intents", []),
                "supplementary_terms": result.get("supplementary_terms", [])
            }
        except Exception as e:
            logger.error(f"LLM意图检测失败: {e}")
            return self._fallback_detection(query)

    def _fallback_detection(self, query: str) -> dict:
        """降级意图检测（基于关键词）"""
        keyword_intents = {
            "景点": "scenic_spot",
            "玩": "scenic_spot",
            "打卡": "scenic_spot",
            "景区": "scenic_spot",
            "观光": "scenic_spot",
            "吃": "dining",
            "美食": "dining",
            "餐厅": "dining",
            "小吃": "dining",
            "住": "accommodation",
            "酒店": "accommodation",
            "民宿": "accommodation",
            "行程": "itinerary",
            "路线": "itinerary",
            "安排": "itinerary",
            "规划": "itinerary",
        }

        matched_intents = []
        for keyword, intent in keyword_intents.items():
            if keyword in query:
                matched_intents.append(intent)

        if not matched_intents:
            return {
                "primary_intent": "itinerary",
                "confidence": 0.3,
                "secondary_intents": [],
                "supplementary_terms": []
            }

        primary = max(set(matched_intents), key=matched_intents.count)
        confidence = matched_intents.count(primary) / len(matched_intents)

        return {
            "primary_intent": primary,
            "confidence": confidence,
            "secondary_intents": [],
            "supplementary_terms": []
        }


class QueryExpander:
    """查询扩展器 - 使用 Embedding 进行同义词匹配"""

    EXPANSION_TERMS = {
        "scenic_spot": [
            "景点", "景区", "打卡地", "观光", "旅游", "必去",
            "风景", "公园", "博物馆", "古迹", "地标"
        ],
        "dining": [
            "美食", "餐厅", "小吃", "餐馆", "特色菜", "推荐吃",
            "好吃", "地道", "网红店", "夜市", "小吃街"
        ],
        "accommodation": [
            "酒店", "民宿", "住宿", "客栈", "公寓", "推荐住",
            "舒适", "性价比", "位置好", "方便", "中心"
        ],
        "itinerary": [
            "行程", "路线", "安排", "规划", "攻略", "推荐玩法",
            "几天", "时间", "日程", "游玩顺序"
        ]
    }

    def __init__(self):
        self._embedding_client = None
        self._initialized = False
        self._term_embeddings: dict[str, list] = {}

    def _get_embedding_client(self):
        """获取 Embedding 客户端"""
        if self._embedding_client is None:
            try:
                from zai import ZhipuAiClient
                self._embedding_client = ZhipuAiClient(api_key=settings.EMBEDDING_API_KEY)
                self._initialized = True
                self._precompute_embeddings()
            except ImportError:
                logger.warning("zai 未安装，使用词表扩展")
                self._initialized = False
        return self._embedding_client

    def _precompute_embeddings(self):
        """预计算扩展词的 Embedding"""
        if self._embedding_client is None:
            return

        try:
            all_terms = set()
            for terms in self.EXPANSION_TERMS.values():
                all_terms.update(terms)

            embeddings = self._embedding_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=list(all_terms)
            )

            for i, embedding in enumerate(embeddings.data):
                term = embeddings.data[i].embedding
                self._term_embeddings[list(all_terms)[i]] = term

            logger.info(f"预计算了 {len(self._term_embeddings)} 个扩展词向量")
        except Exception as e:
            logger.error(f"预计算扩展词向量失败: {e}")

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """计算余弦相似度"""
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        return dot / (norm1 * norm2 + 1e-8)

    def expand(self, query: str, intent: str, top_k: int = 5) -> list[str]:
        """
        扩展查询词

        Args:
            query: 原始查询
            intent: 识别出的意图
            top_k: 返回的扩展词数量

        Returns:
            扩展后的查询词列表
        """
        terms = self.EXPANSION_TERMS.get(intent, [])

        if not self._initialized or not self._term_embeddings:
            return terms[:top_k]

        try:
            embedding_response = self._embedding_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=[query]
            )
            query_embedding = embedding_response.data[0].embedding

            similarities = []
            for term in terms:
                if term in self._term_embeddings:
                    sim = self._cosine_similarity(query_embedding, self._term_embeddings[term])
                    similarities.append((term, sim))

            similarities.sort(key=lambda x: x[1], reverse=True)
            expanded = [term for term, _ in similarities[:top_k]]

            return expanded if expanded else terms[:top_k]
        except Exception as e:
            logger.error(f"查询扩展失败: {e}")
            return terms[:top_k]


class RetrievalCache:
    """检索结果缓存 - 基于 Redis"""

    CACHE_PREFIX = "rag:retrieval:"
    DEFAULT_TTL = 3600

    def __init__(self, redis_url: Optional[str] = None, ttl: int = DEFAULT_TTL):
        self._redis_client: Optional[redis.Redis] = None
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._ttl = ttl
        self._connected = False

    def _get_client(self) -> Optional[redis.Redis]:
        """获取 Redis 客户端"""
        if self._redis_client is None:
            try:
                self._redis_client = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2
                )
                self._redis_client.ping()
                self._connected = True
                logger.info("Redis 缓存连接成功")
            except redis.ConnectionError as e:
                logger.warning(f"Redis 连接失败: {e}，将使用内存回退")
                self._redis_client = None
                self._connected = False
            except Exception as e:
                logger.error(f"Redis 初始化失败: {e}")
                self._redis_client = None
                self._connected = False
        return self._redis_client

    def _generate_key(self, query: str, city: Optional[str] = None, intent: Optional[str] = None) -> str:
        """生成缓存键"""
        key_parts = [query]
        if city:
            key_parts.append(city)
        if intent:
            key_parts.append(intent)
        key_str = ":".join(key_parts)
        return self.CACHE_PREFIX + hashlib.md5(key_str.encode()).hexdigest()

    def get(self, query: str, city: Optional[str] = None, intent: Optional[str] = None) -> Optional[dict]:
        """
        获取缓存的检索结果

        Args:
            query: 查询文本
            city: 城市
            intent: 意图

        Returns:
            缓存结果或 None
        """
        client = self._get_client()
        if client is None:
            return None

        try:
            key = self._generate_key(query, city, intent)
            cached = client.get(key)

            if cached:
                logger.debug(f"缓存命中: {key[:50]}...")
                return json.loads(cached)

            return None
        except Exception as e:
            logger.error(f"获取缓存失败: {e}")
            return None

    def set(
        self,
        query: str,
        city: Optional[str],
        intent: Optional[str],
        results: list[dict],
        query_info: dict
    ) -> bool:
        """
        缓存检索结果

        Args:
            query: 查询文本
            city: 城市
            intent: 意图
            results: 检索结果
            query_info: 查询信息

        Returns:
            是否成功
        """
        client = self._get_client()
        if client is None:
            return False

        try:
            key = self._generate_key(query, city, intent)
            cache_data = {
                "results": results,
                "query_info": query_info,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            client.setex(key, self._ttl, json.dumps(cache_data, ensure_ascii=False))
            logger.debug(f"缓存写入: {key[:50]}...")
            return True
        except Exception as e:
            logger.error(f"写入缓存失败: {e}")
            return False

    def invalidate(self, pattern: Optional[str] = None) -> int:
        """
        使缓存失效

        Args:
            pattern: 匹配模式，None 则清空所有

        Returns:
            删除的键数量
        """
        client = self._get_client()
        if client is None:
            return 0

        try:
            if pattern:
                keys = client.keys(self.CACHE_PREFIX + pattern)
            else:
                keys = client.keys(self.CACHE_PREFIX + "*")

            if keys:
                return client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"清空缓存失败: {e}")
            return 0

    def get_stats(self) -> dict:
        """获取缓存统计"""
        client = self._get_client()
        if client is None:
            return {"status": "disconnected"}

        try:
            keys = client.keys(self.CACHE_PREFIX + "*")
            return {
                "status": "connected",
                "total_keys": len(keys),
                "ttl_seconds": self._ttl
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}


class Reranker:
    """重排序器 - 使用本地模型"""

    def __init__(self):
        self._model = None
        self._initialized = False
        self._model_name = "BAAI/bge-reranker-v2-m3"

    def _load_model(self):
        """加载重排序模型"""
        if self._model is None and not self._initialized:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self._model_name, max_length=512)
                self._initialized = True
                logger.info(f"Rerank 模型加载成功: {self._model_name}")
            except ImportError:
                logger.warning("sentence-transformers 未安装，重排序将跳过")
                self._initialized = True
            except Exception as e:
                logger.error(f"加载 Rerank 模型失败: {e}")
                self._initialized = True

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int = 5,
        score_threshold: float = 0.35
    ) -> list[dict]:
        """
        对检索结果进行重排序

        Args:
            query: 查询文本
            documents: 候选文档列表
            top_n: 返回前 N 条
            score_threshold: 分数阈值

        Returns:
            重排后的文档列表
        """
        if not documents:
            return []

        self._load_model()

        if self._model is None:
            return documents[:top_n]

        try:
            doc_texts = [
                doc.get("document", doc.get("content", "")) for doc in documents
            ]

            pairs = [(query, doc_text) for doc_text in doc_texts]
            scores = self._model.predict(pairs)

            for i, doc in enumerate(documents):
                doc["rerank_score"] = float(scores[i]) if hasattr(scores, "__iter__") else float(scores)

            reranked = sorted(documents, key=lambda x: x.get("rerank_score", 0), reverse=True)

            filtered = [
                doc for doc in reranked
                if doc.get("rerank_score", 0) >= score_threshold
            ]

            return filtered[:top_n]
        except Exception as e:
            logger.error(f"Rerank 失败: {e}")
            return documents[:top_n]


class Retriever:
    """
    统一检索服务 - 整合所有组件
    """

    def __init__(self):
        self.preprocessor = QueryPreprocessor()
        self.intent_detector = IntentDetector()
        self.query_expander = QueryExpander()
        self.reranker = Reranker()
        self.cache = RetrievalCache()
        self.search_engine = hybrid_search_engine

    def retrieve(
        self,
        query: str,
        city: Optional[str] = None,
        category: Optional[str] = None,
        use_cache: bool = True,
        use_rerank: bool = True,
        top_k: int = 5
    ) -> dict:
        """
        执行检索的完整流程

        Args:
            query: 用户查询
            city: 目标城市（可选，自动从查询提取）
            category: 内容类别（景点/餐饮/住宿/行程）
            use_cache: 是否使用缓存
            use_rerank: 是否使用重排序
            top_k: 返回结果数量

        Returns:
            {
                "results": [...],
                "query_info": {...},
                "cached": bool,
                "total_time_ms": float,
                "stages": {...}
            }
        """
        start_time = time.time()
        stages = {}

        basic_info = self.preprocessor.preprocess(query)
        city = city or basic_info["city"]
        days = basic_info["days"]
        stages["preprocess_ms"] = round((time.time() - start_time) * 1000, 2)

        intent_start = time.time()
        intent_info = self.intent_detector.detect(query)
        stages["intent_detect_ms"] = round((time.time() - intent_start) * 1000, 2)

        intent = intent_info["primary_intent"]
        supplementary_terms = intent_info.get("supplementary_terms", [])

        cache_key_city = city or "all"
        cache_key_intent = intent

        if use_cache:
            cache_start = time.time()
            cached_result = self.cache.get(query, cache_key_city, cache_key_intent)
            stages["cache_check_ms"] = round((time.time() - cache_start) * 1000, 2)

            if cached_result:
                stages["total_ms"] = round((time.time() - start_time) * 1000, 2)
                cached_result["cached"] = True
                cached_result["stages"] = stages
                return cached_result
        else:
            stages["cache_check_ms"] = 0

        search_queries = [query]
        if supplementary_terms:
            expanded_terms = self.query_expander.expand(query, intent, top_k=3)
            search_queries.extend(expanded_terms[:2])

        search_start = time.time()
        search_results = self.search_engine.search(
            query=query,
            query_embedding=self._get_query_embedding(query),
            city=city,
            category=category,
            top_k=top_k * 3
        )
        stages["search_ms"] = round((time.time() - search_start) * 1000, 2)

        if use_rerank and search_results:
            rerank_start = time.time()
            final_results = self.reranker.rerank(
                query=query,
                documents=search_results,
                top_n=top_k,
                score_threshold=0.35
            )
            stages["rerank_ms"] = round((time.time() - rerank_start) * 1000, 2)
        else:
            final_results = search_results[:top_k]
            stages["rerank_ms"] = 0

        query_info = {
            "original": query,
            "city": city,
            "days": days,
            "intent": intent,
            "confidence": intent_info.get("confidence", 0),
            "secondary_intents": intent_info.get("secondary_intents", []),
            "supplementary_terms": supplementary_terms
        }

        if use_cache:
            self.cache.set(query, cache_key_city, cache_key_intent, final_results, query_info)

        stages["total_ms"] = round((time.time() - start_time) * 1000, 2)

        return {
            "results": final_results,
            "query_info": query_info,
            "cached": False,
            "total_time_ms": stages["total_ms"],
            "stages": stages
        }

    def _get_query_embedding(self, query: str) -> list[float]:
        """获取查询向量"""
        try:
            from zai import ZhipuAiClient
            client = ZhipuAiClient(api_key=settings.EMBEDDING_API_KEY)
            response = client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=[query]
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"获取查询向量失败: {e}")
            return [0.0] * 256


retriever = Retriever()
