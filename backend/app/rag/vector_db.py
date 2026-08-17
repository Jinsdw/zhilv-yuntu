"""
智旅云图 - ChromaDB 向量数据库服务
提供攻略文档的向量化存储和混合检索能力
"""

import os
import json
import hashlib
import shutil
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger

from app.config import settings


class VectorDBService:
    """ChromaDB 向量数据库服务封装"""

    COLLECTION_NAME = "travel_guides"
    EMBEDDING_DIMENSION = 256

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: str = COLLECTION_NAME
    ):
        """
        初始化向量数据库服务

        Args:
            persist_directory: ChromaDB 持久化目录
            collection_name: 集合名称
        """
        self.persist_directory = persist_directory or settings.CHROMA_DB_PATH
        self.collection_name = collection_name
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection: Optional[chromadb.Collection] = None
        self._retrieval_rules = self._load_retrieval_rules()

    def _load_retrieval_rules(self) -> dict:
        """加载检索规则配置"""
        rules_path = Path(__file__).parent.parent.parent / "data" / "retrieval_rules.json"
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载检索规则失败: {e}, 使用默认配置")
            return self._get_default_retrieval_rules()

    def _get_default_retrieval_rules(self) -> dict:
        """获取默认检索规则"""
        return {
            "retrieval": {
                "vector_search": {"top_k": 10},
                "keyword_search": {"top_k": 10, "enabled": True},
                "fusion": {"method": "rrf", "k": 60, "weights": {"vector": 0.7, "keyword": 0.3}}
            },
            "rerank": {
                "enabled": True,
                "primary_model": {"top_n": 5, "score_threshold": 0.35}
            },
            "output": {"max_chunks": 5}
        }

    @property
    def client(self) -> chromadb.PersistentClient:
        """获取 ChromaDB 客户端（延迟初始化）"""
        if self._client is None:
            os.makedirs(self.persist_directory, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"ChromaDB 客户端初始化完成，路径: {self.persist_directory}")
        return self._client

    @property
    def collection(self) -> chromadb.Collection:
        """获取集合（延迟初始化）"""
        if self._collection is None:
            self._collection = self.get_or_create_collection()
        return self._collection

    def get_or_create_collection(self) -> chromadb.Collection:
        """
        获取或创建集合

        Returns:
            chromadb.Collection: 向量数据库集合
        """
        try:
            collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "description": "智旅云图旅行攻略向量库",
                    "dimension": self.EMBEDDING_DIMENSION,
                    "created_at": datetime.now().isoformat()
                }
            )
            logger.info(f"集合 '{self.collection_name}' 已就绪")
            return collection
        except Exception as e:
            logger.error(f"创建集合失败: {e}")
            raise

    def reset_collection(self) -> bool:
        """
        重置集合（删除所有数据）

        Returns:
            bool: 是否成功重置
        """
        try:
            self.client.delete_collection(name=self.collection_name)
            self._collection = None
            logger.warning(f"集合 '{self.collection_name}' 已重置")
            return True
        except Exception as e:
            logger.error(f"重置集合失败: {e}")
            return False

    def get_collection_info(self) -> dict:
        """
        获取集合信息

        Returns:
            dict: 集合元数据
        """
        try:
            collection = self.get_or_create_collection()
            return {
                "name": collection.name,
                "count": collection.count(),
                "dimension": self.EMBEDDING_DIMENSION,
                "metadata": collection.metadata
            }
        except Exception as e:
            logger.error(f"获取集合信息失败: {e}")
            return {}

    def add_documents(
        self,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: Optional[list[dict]] = None,
        ids: Optional[list[str]] = None
    ) -> list[str]:
        """
        添加文档到向量库

        Args:
            documents: 文档内容列表
            embeddings: 向量嵌入列表
            metadatas: 元数据列表
            ids: 文档ID列表

        Returns:
            list[str]: 生成的文档ID列表
        """
        if ids is None:
            ids = [self._generate_doc_id(doc) for doc in documents]

        if metadatas is None:
            metadatas = [{} for _ in documents]

        try:
            self.collection.add(
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"成功添加 {len(documents)} 个文档到向量库")
            return ids
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            raise

    def delete_documents(self, ids: list[str]) -> bool:
        """
        删除文档

        Args:
            ids: 文档ID列表

        Returns:
            bool: 是否成功删除
        """
        try:
            self.collection.delete(ids=ids)
            logger.info(f"成功删除 {len(ids)} 个文档")
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return False

    def query_by_vector(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None
    ) -> dict:
        """
        基于向量相似度查询

        Args:
            query_embedding: 查询向量
            n_results: 返回结果数量
            where: 元数据过滤条件
            where_document: 文档内容过滤条件

        Returns:
            dict: 查询结果
        """
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                where_document=where_document,
                include=["documents", "metadatas", "distances"]
            )
            return self._format_query_results(results)
        except Exception as e:
            logger.error(f"向量查询失败: {e}")
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

    def query_by_text(
        self,
        query_texts: list[str],
        n_results: int = 10,
        where: Optional[dict] = None
    ) -> dict:
        """
        基于文本内容查询（ChromaDB 内置）

        Args:
            query_texts: 查询文本列表
            n_results: 返回结果数量
            where: 元数据过滤条件

        Returns:
            dict: 查询结果
        """
        try:
            results = self.collection.query(
                query_texts=query_texts,
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"]
            )
            return self._format_query_results(results)
        except Exception as e:
            logger.error(f"文本查询失败: {e}")
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

    def get_document(self, doc_id: str) -> Optional[dict]:
        """
        根据ID获取单个文档

        Args:
            doc_id: 文档ID

        Returns:
            Optional[dict]: 文档内容
        """
        try:
            result = self.collection.get(ids=[doc_id], include=["documents", "metadatas"])
            if result["ids"]:
                return {
                    "id": result["ids"][0],
                    "document": result["documents"][0],
                    "metadata": result["metadatas"][0]
                }
            return None
        except Exception as e:
            logger.error(f"获取文档失败: {e}")
            return None

    def count(self) -> int:
        """获取集合中的文档数量"""
        return self.collection.count()

    def _generate_doc_id(self, content: str) -> str:
        """生成文档ID（基于内容哈希）"""
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _format_query_results(self, results: dict) -> dict:
        """格式化查询结果"""
        return {
            "ids": results.get("ids", [[]])[0] if results.get("ids") else [],
            "documents": results.get("documents", [[]])[0] if results.get("documents") else [],
            "metadatas": results.get("metadatas", [[]])[0] if results.get("metadatas") else [],
            "distances": results.get("distances", [[]])[0] if results.get("distances") else []
        }


class HybridSearchEngine:
    """混合检索引擎（向量 + BM25 + RRF融合）"""

    def __init__(self, vector_db: VectorDBService):
        self.vector_db = vector_db
        self.retrieval_rules = vector_db._retrieval_rules

    def search(
        self,
        query: str,
        query_embedding: list[float],
        city: Optional[str] = None,
        category: Optional[str] = None,
        top_k: int = 10
    ) -> list[dict]:
        """
        执行混合检索

        Args:
            query: 原始查询文本
            query_embedding: 查询向量
            city: 城市过滤
            category: 类别过滤
            top_k: 返回结果数量

        Returns:
            list[dict]: 排序后的检索结果
        """
        fusion_config = self.retrieval_rules.get("retrieval", {}).get("fusion", {})
        fusion_method = fusion_config.get("method", "rrf")
        fusion_k = fusion_config.get("k", 60)
        weights = fusion_config.get("weights", {"vector": 0.7, "keyword": 0.3})

        where_filter = {}
        if city:
            where_filter["city"] = city
        if category:
            where_filter["category"] = category

        vector_results = self._vector_search(query_embedding, top_k * 2, where_filter)

        keyword_results = self._keyword_search(query, top_k * 2, where_filter)

        if fusion_method == "rrf":
            fused_results = self._rrf_fusion(
                vector_results,
                keyword_results,
                k=fusion_k,
                weights=weights
            )
        else:
            fused_results = self._weighted_fusion(vector_results, keyword_results, weights)

        return fused_results[:top_k]

    def _vector_search(
        self,
        query_embedding: list[float],
        top_k: int,
        where_filter: Optional[dict] = None
    ) -> list[dict]:
        """向量检索"""
        try:
            results = self.vector_db.query_by_vector(
                query_embedding=query_embedding,
                n_results=top_k,
                where=where_filter if where_filter else None
            )
            return self._results_to_list(results)
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        where_filter: Optional[dict] = None
    ) -> list[dict]:
        """
        关键词检索（基于 ChromaDB 的全文搜索）

        在 ChromaDB 中，文本查询会使用内部的 BM25 实现
        """
        try:
            results = self.vector_db.query_by_text(
                query_texts=[query],
                n_results=top_k,
                where=where_filter if where_filter else None
            )
            return self._results_to_list(results)
        except Exception as e:
            logger.error(f"关键词检索失败: {e}")
            return []

    def _rrf_fusion(
        self,
        vector_results: list[dict],
        keyword_results: list[dict],
        k: int = 60,
        weights: dict = None
    ) -> list[dict]:
        """
        RRF (Reciprocal Rank Fusion) 融合

        RRF score = Σ (weight_i / (k + rank_i))
        """
        if weights is None:
            weights = {"vector": 0.7, "keyword": 0.3}

        doc_scores = {}

        for rank, doc in enumerate(vector_results, 1):
            doc_id = doc["id"]
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {"doc": doc, "vector_rank": rank, "keyword_rank": None}
            else:
                doc_scores[doc_id]["vector_rank"] = rank

        for rank, doc in enumerate(keyword_results, 1):
            doc_id = doc["id"]
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {"doc": doc, "vector_rank": None, "keyword_rank": rank}
            else:
                doc_scores[doc_id]["keyword_rank"] = rank

        fused = []
        for doc_id, data in doc_scores.items():
            vector_rank = data["vector_rank"]
            keyword_rank = data["keyword_rank"]

            vector_score = weights.get("vector", 0.7) / (k + vector_rank) if vector_rank else 0
            keyword_score = weights.get("keyword", 0.3) / (k + keyword_rank) if keyword_rank else 0

            rrf_score = vector_score + keyword_score

            doc = data["doc"].copy()
            doc["rrf_score"] = rrf_score
            doc["vector_rank"] = vector_rank
            doc["keyword_rank"] = keyword_rank
            fused.append(doc)

        fused.sort(key=lambda x: x["rrf_score"], reverse=True)
        return fused

    def _weighted_fusion(
        self,
        vector_results: list[dict],
        keyword_results: list[dict],
        weights: dict
    ) -> list[dict]:
        """加权分数融合"""
        doc_scores = {}

        for rank, doc in enumerate(vector_results, 1):
            doc_id = doc["id"]
            doc_scores[doc_id] = {
                "doc": doc,
                "vector_score": 1.0 / rank,
                "keyword_score": 0
            }

        for rank, doc in enumerate(keyword_results, 1):
            doc_id = doc["id"]
            if doc_id in doc_scores:
                doc_scores[doc_id]["keyword_score"] = 1.0 / rank
            else:
                doc_scores[doc_id] = {
                    "doc": doc,
                    "vector_score": 0,
                    "keyword_score": 1.0 / rank
                }

        fused = []
        for doc_id, data in doc_scores.items():
            weighted_score = (
                weights.get("vector", 0.7) * data["vector_score"] +
                weights.get("keyword", 0.3) * data["keyword_score"]
            )
            doc = data["doc"].copy()
            doc["weighted_score"] = weighted_score
            fused.append(doc)

        fused.sort(key=lambda x: x["weighted_score"], reverse=True)
        return fused

    def _results_to_list(self, results: dict) -> list[dict]:
        """将查询结果转换为列表格式"""
        items = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        distances = results.get("distances", [])

        for i, doc_id in enumerate(ids):
            items.append({
                "id": doc_id,
                "document": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "distance": distances[i] if i < len(distances) else None,
                "similarity": 1 - distances[i] if i < len(distances) and distances[i] is not None else None
            })

        return items


class VectorDBManager:
    """向量数据库管理器（支持备份、恢复、健康检查）"""

    def __init__(self, vector_db: VectorDBService):
        self.vector_db = vector_db

    def backup(self, backup_path: Optional[str] = None) -> str:
        """
        备份向量数据库

        Args:
            backup_path: 备份目标路径，默认在原路径下创建带时间戳的备份

        Returns:
            str: 备份路径
        """
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.vector_db.persist_directory}_backup_{timestamp}"

        try:
            shutil.copytree(
                self.vector_db.persist_directory,
                backup_path,
                dirs_exist_ok=True
            )
            logger.info(f"向量数据库备份成功: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"备份失败: {e}")
            raise

    def restore(self, backup_path: str) -> bool:
        """
        从备份恢复向量数据库

        Args:
            backup_path: 备份路径

        Returns:
            bool: 是否恢复成功
        """
        if not os.path.exists(backup_path):
            logger.error(f"备份路径不存在: {backup_path}")
            return False

        try:
            self.vector_db.reset_collection()

            for item in os.listdir(backup_path):
                src = os.path.join(backup_path, item)
                dst = os.path.join(self.vector_db.persist_directory, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)

            self.vector_db._collection = None
            logger.info(f"向量数据库恢复成功，从: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"恢复失败: {e}")
            return False

    def health_check(self) -> dict:
        """
        健康检查

        Returns:
            dict: 健康状态信息
        """
        status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "checks": {}
        }

        try:
            collection_info = self.vector_db.get_collection_info()
            status["checks"]["collection"] = {
                "status": "ok",
                "name": collection_info.get("name"),
                "document_count": collection_info.get("count", 0)
            }
        except Exception as e:
            status["checks"]["collection"] = {"status": "error", "message": str(e)}
            status["status"] = "degraded"

        try:
            test_path = self.vector_db.persist_directory
            os.makedirs(test_path, exist_ok=True)
            status["checks"]["storage"] = {"status": "ok", "path": test_path}
        except Exception as e:
            status["checks"]["storage"] = {"status": "error", "message": str(e)}
            status["status"] = "unhealthy"

        return status

    def get_stats(self) -> dict:
        """
        获取统计数据

        Returns:
            dict: 统计信息
        """
        try:
            collection_info = self.vector_db.get_collection_info()

            all_data = self.vector_db.collection.get(include=["metadatas"])

            city_stats = {}
            category_stats = {}

            for metadata in all_data.get("metadatas", []):
                if not metadata:
                    continue

                city = metadata.get("city", "unknown")
                category = metadata.get("category", "unknown")

                city_stats[city] = city_stats.get(city, 0) + 1
                category_stats[category] = category_stats.get(category, 0) + 1

            return {
                "total_documents": collection_info.get("count", 0),
                "dimension": self.vector_db.EMBEDDING_DIMENSION,
                "by_city": city_stats,
                "by_category": category_stats,
                "persist_directory": self.vector_db.persist_directory
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}


vector_db_service = VectorDBService()
hybrid_search_engine = HybridSearchEngine(vector_db_service)
vector_db_manager = VectorDBManager(vector_db_service)
