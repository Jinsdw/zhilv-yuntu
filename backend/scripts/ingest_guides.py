"""
智旅云图 - 攻略文档向量化入库脚本
将攻略文档分块、向量化并存储到 ChromaDB
"""

import os
import re
import sys
import json
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime

import httpx
from loguru import logger

# 设置项目根目录和 backend 目录为工作目录
_script_dir = Path(__file__).resolve().parent
_backend_dir = _script_dir.parent  # backend/
_project_root = _backend_dir.parent  # 项目根目录
sys.path.insert(0, str(_backend_dir))
os.chdir(str(_project_root))

from app.config import settings
from app.rag.guide_catalog import guide_catalog
from app.rag.vector_db import VectorDBService


class GuideIngester:
    """攻略文档入库处理器"""

    def __init__(self):
        self.vector_db = VectorDBService()
        # 优先使用配置中的路径，否则使用 backend/data
        config_path = settings.GUIDE_DOCS_PATH
        if config_path and Path(config_path).exists():
            self.guide_docs_path = config_path
        else:
            self.guide_docs_path = str(_backend_dir / "data")
        self.retrieval_rules = self._load_retrieval_rules()

    def _load_retrieval_rules(self) -> dict:
        """加载检索规则配置"""
        rules_path = _backend_dir / "data" / "retrieval_rules.json"
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载检索规则失败: {e}")
            return {}

    def ingest_all(self, force_recreate: bool = False) -> dict:
        """
        入库所有攻略文档

        Args:
            force_recreate: 是否强制重建（先清空再入库）

        Returns:
            dict: 入库统计信息
        """
        logger.info("=" * 60)
        logger.info("开始攻略文档向量化入库")
        logger.info("=" * 60)

        if force_recreate:
            logger.warning("强制重建模式：先清空现有数据")
            self.vector_db.reset_collection()

        guide_files = list(Path(self.guide_docs_path).glob("*_guide.md"))
        logger.info(f"发现 {len(guide_files)} 个攻略文档")

        total_chunks = 0
        total_cities = 0

        for guide_file in guide_files:
            city_name = self._extract_city_name(guide_file.name)
            logger.info(f"\n处理城市: {city_name}")

            chunks = self._parse_guide(guide_file, city_name)
            if not chunks:
                logger.warning(f"  {city_name} 未解析到有效内容")
                continue

            logger.info(f"  解析到 {len(chunks)} 个内容块")

            embeddings = self._generate_embeddings(chunks)
            if not embeddings:
                logger.error(f"  {city_name} 向量化失败，跳过")
                continue

            self._store_chunks(chunks, embeddings)
            total_chunks += len(chunks)
            total_cities += 1

        stats = self.vector_db.get_collection_info()
        result = {
            "status": "success",
            "cities_processed": total_cities,
            "total_chunks": total_chunks,
            "collection_count": stats.get("count", 0)
        }

        logger.info("\n" + "=" * 60)
        logger.info(f"入库完成！处理 {total_cities} 个城市，共 {total_chunks} 个内容块")
        logger.info(f"集合当前文档总数: {result['collection_count']}")
        logger.info("=" * 60)

        return result

    def ingest_single(self, city: str, force_recreate: bool = False) -> dict:
        """
        入库单个城市的攻略文档（用于测试）

        Args:
            city: 城市名（如 beijing、chengdu）
            force_recreate: 是否强制重建

        Returns:
            dict: 入库结果
        """
        logger.info("=" * 60)
        logger.info(f"入库单个城市测试: {city}")
        logger.info("=" * 60)

        # CLI 可能传拼音（beijing），统一映射为中文存 metadata，与检索侧一致
        city_resolved = guide_catalog.resolve_city(city) or city
        guide_file = Path(self.guide_docs_path) / f"{city}_guide.md"

        if not guide_file.exists():
            return {
                "status": "error",
                "message": f"攻略文件不存在: {guide_file}"
            }

        if force_recreate:
            existing_ids = self._get_city_doc_ids(city_resolved)
            if existing_ids:
                self.vector_db.delete_documents(existing_ids)
                logger.info(f"已删除旧数据: {len(existing_ids)} 条")

        chunks = self._parse_guide(guide_file, city_resolved)
        if not chunks:
            return {
                "status": "error",
                "message": "未解析到有效内容"
            }

        logger.info(f"解析到 {len(chunks)} 个内容块")

        embeddings = self._generate_embeddings(chunks)
        if not embeddings:
            return {
                "status": "error",
                "message": "向量化失败"
            }

        self._store_chunks(chunks, embeddings)

        stats = self.vector_db.get_collection_info()
        result = {
            "status": "success",
            "city": city_resolved,
            "chunks_created": len(chunks),
            "collection_count": stats.get("count", 0)
        }

        logger.info("\n" + "=" * 60)
        logger.info(f"入库完成！城市: {city_resolved}，内容块: {len(chunks)}")
        logger.info(f"集合当前文档总数: {result['collection_count']}")
        logger.info("=" * 60)

        return result

    def _extract_city_name(self, filename: str) -> str:
        """
        从文件名提取城市名（拼音 → 中文）。

        攻略文件以拼音命名（beijing_guide.md），但检索侧用中文（'北京'）过滤，
        metadata 必须存中文，否则 where city='北京' 永远匹配不到英文 'beijing'，
        导致检索空结果并触发逐级降级。
        """
        match = re.match(r"(.+?)_guide\.md", filename)
        if match:
            city = match.group(1).replace("_", "")
            resolved = guide_catalog.resolve_city(city)
            return resolved or city
        return "unknown"

    def _parse_guide(self, guide_path: Path, city_name: str) -> list[dict]:
        """
        解析攻略文档，按章节分块

        Returns:
            list[dict]: 分块后的内容列表
        """
        with open(guide_path, "r", encoding="utf-8") as f:
            content = f.read()

        chunks = []
        chunking_rules = self.retrieval_rules.get("chunking", {})
        rules = chunking_rules.get("rules", [])

        current_section = ""
        current_subsection = ""
        current_content = []

        lines = content.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()

            if re.match(r"^## \d+\. ", stripped):
                if current_content:
                    chunk_text = "\n".join(current_content).strip()
                    if chunk_text:
                        chunks.append(self._create_chunk(
                            chunk_text, city_name, current_section,
                            current_subsection, str(guide_path.name)
                        ))

                current_section = re.sub(r"^## \d+\. ", "", stripped)
                current_subsection = ""
                current_content = []

            elif re.match(r"^### \d+\.\d+ ", stripped):
                if current_subsection and current_content:
                    chunk_text = "\n".join(current_content).strip()
                    if chunk_text:
                        chunks.append(self._create_chunk(
                            chunk_text, city_name, current_section,
                            current_subsection, str(guide_path.name)
                        ))

                current_subsection = re.sub(r"^### \d+\.\d+ ", "", stripped)
                current_content = []

            elif stripped.startswith("* **"):
                current_content.append(stripped)

            elif stripped.startswith("- **") or stripped.startswith("* "):
                current_content.append(stripped)

            elif stripped and not stripped.startswith("#"):
                current_content.append(stripped)

        if current_content:
            chunk_text = "\n".join(current_content).strip()
            if chunk_text:
                chunks.append(self._create_chunk(
                    chunk_text, city_name, current_section,
                    current_subsection, str(guide_path.name)
                ))

        return chunks

    def _create_chunk(
        self,
        content: str,
        city_name: str,
        section: str,
        subsection: str,
        source_file: str
    ) -> dict:
        """创建内容块对象"""
        category = self._infer_category(section, subsection, content)

        return {
            "content": content,
            "city": city_name,
            "section": section,
            "subsection": subsection,
            "category": category,
            "source_file": source_file,
            "created_at": datetime.now().isoformat()
        }

    def _infer_category(self, section: str, subsection: str, content: str) -> str:
        """推断内容类别"""
        section_lower = section.lower()
        subsection_lower = subsection.lower()
        content_lower = content.lower()

        if any(keyword in section_lower for keyword in ["景点", "推荐", "打卡"]):
            return "景点"
        elif any(keyword in section_lower for keyword in ["餐饮", "美食", "餐厅", "小吃"]):
            return "餐饮"
        elif any(keyword in section_lower for keyword in ["住宿", "酒店", "民宿"]):
            return "住宿"
        elif any(keyword in section_lower for keyword in ["行程", "路线", "游玩"]):
            return "行程"
        else:
            return "综合"

    def _generate_embeddings(self, chunks: list[dict]) -> list[list[float]]:
        """
        调用智谱 API 生成向量

        Args:
            chunks: 内容块列表

        Returns:
            list[list[float]]: 向量列表
        """
        embeddings = []
        batch_size = 10

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [chunk["content"] for chunk in batch]

            try:
                vectors = self._call_embedding_api(texts)
                embeddings.extend(vectors)
                logger.info(f"  向量化进度: {min(i + batch_size, len(chunks))}/{len(chunks)}")
            except Exception as e:
                logger.error(f"  批量向量化失败: {e}")
                return []

        return embeddings

    def _call_embedding_api(self, texts: list[str]) -> list[list[float]]:
        """
        调用智谱 Embedding API

        Args:
            texts: 文本列表（最多支持 25 条）

        Returns:
            list[list[float]]: 向量列表
        """
        url = f"{settings.EMBEDDING_BASE_URL}/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": settings.EMBEDDING_MODEL,
            "input": texts,
            "dimensions": 256
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()
            embeddings = [item["embedding"] for item in result["data"]]
            return embeddings

    def _store_chunks(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        """存储分块到向量数据库"""
        documents = [chunk["content"] for chunk in chunks]
        ids = [self._generate_chunk_id(chunk) for chunk in chunks]

        metadatas = []
        for chunk in chunks:
            metadatas.append({
                "city": chunk["city"],
                "section": chunk["section"],
                "subsection": chunk["subsection"],
                "category": chunk["category"],
                "source_file": chunk["source_file"],
                "created_at": chunk["created_at"]
            })

        self.vector_db.add_documents(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )

        logger.info(f"  已存储 {len(chunks)} 个内容块")

    def _generate_chunk_id(self, chunk: dict) -> str:
        """生成内容块ID"""
        content = chunk["content"]
        city = chunk["city"]
        section = chunk["section"]
        hash_input = f"{city}:{section}:{content[:100]}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def update_incremental(self, city: Optional[str] = None) -> dict:
        """
        增量更新指定城市的文档

        Args:
            city: 城市名（None 表示更新全部）

        Returns:
            dict: 更新结果
        """
        logger.info("开始增量更新...")

        if city:
            guide_files = [Path(self.guide_docs_path) / f"{city}_guide.md"]
        else:
            guide_files = list(Path(self.guide_docs_path).glob("*_guide.md"))

        updated = 0
        for guide_file in guide_files:
            if not guide_file.exists():
                continue

            city_name = self._extract_city_name(guide_file.name)

            existing_ids = self._get_city_doc_ids(city_name)
            if existing_ids:
                self.vector_db.delete_documents(existing_ids)
                logger.info(f"  已删除 {city_name} 旧数据: {len(existing_ids)} 条")

            chunks = self._parse_guide(guide_file, city_name)
            if chunks:
                embeddings = self._generate_embeddings(chunks)
                if embeddings:
                    self._store_chunks(chunks, embeddings)
                    updated += 1

        return {
            "status": "success",
            "cities_updated": updated
        }

    def _get_city_doc_ids(self, city: str) -> list[str]:
        """获取指定城市的所有文档ID"""
        try:
            all_data = self.vector_db.collection.get(
                where={"city": {"$eq": city}},
                include=[]
            )
            return all_data.get("ids", [])
        except Exception:
            return []


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="智旅云图攻略文档入库工具")
    parser.add_argument("--city", type=str, default="beijing", help="入库指定城市（默认: beijing）")
    parser.add_argument("--all", action="store_true", help="入库所有城市")
    parser.add_argument("--recreate", action="store_true", help="强制重建（清空后重新入库）")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")

    args = parser.parse_args()

    ingester = GuideIngester()

    if args.stats:
        stats = ingester.vector_db.get_collection_info()
        print("\n向量库统计信息:")
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    if args.all:
        result = ingester.ingest_all(force_recreate=args.recreate)
    else:
        result = ingester.ingest_single(args.city, force_recreate=args.recreate)

    print("\n执行结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
