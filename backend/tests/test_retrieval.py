"""
智旅云图 - 向量库检索测试脚本
"""

import os
import sys
from pathlib import Path
from typing import Optional

# 设置项目路径
_script_dir = Path(__file__).resolve().parent
_backend_dir = _script_dir.parent
_project_root = _backend_dir.parent
sys.path.insert(0, str(_backend_dir))
os.chdir(str(_project_root))

import httpx
from app.rag.vector_db import VectorDBService, HybridSearchEngine
from app.config import settings


def get_embedding(text: str) -> Optional[list[float]]:
    """调用智谱 Embedding API 获取文本向量"""
    url = f"{settings.EMBEDDING_BASE_URL}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": text,
        "dimensions": 256
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return result["data"][0]["embedding"]
    except Exception as e:
        print(f"获取向量失败: {e}")
        return None


def test_search(query: str, city: Optional[str] = None, top_k: int = 5):
    """
    测试向量检索

    Args:
        query: 查询文本
        city: 可选，限定城市
        top_k: 返回结果数量
    """
    vector_db = VectorDBService()

    print("=" * 60)
    print(f"查询: {query}")
    if city:
        print(f"限定城市: {city}")
    print(f"返回数量: {top_k}")
    print("=" * 60)

    # 先获取查询向量
    query_embedding = get_embedding(query)
    if not query_embedding:
        print("获取查询向量失败")
        return

    # 构建过滤条件
    where_filter = None
    if city:
        where_filter = {"city": city}

    # 使用 query_by_vector（需要手动传入向量）
    results = vector_db.query_by_vector(
        query_embedding=query_embedding,
        n_results=top_k,
        where=where_filter
    )

    if not results.get("documents") or not results["documents"][0]:
        print("\n未找到匹配结果")
        return

    documents = results["documents"]
    metadatas = results["metadatas"]
    distances = results["distances"]

    # 确保是列表格式
    if not isinstance(documents, list):
        documents = [documents]
    if not isinstance(metadatas, list):
        metadatas = [metadatas]
    if not isinstance(distances, list):
        distances = [distances]

    print(f"\n找到 {len(documents)} 条结果:\n")

    for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances), 1):
        print(f"【结果 {i}】")
        print(f"  距离: {dist:.4f}")
        print(f"  城市: {meta.get('city', 'N/A') if meta else 'N/A'}")
        print(f"  分类: {meta.get('category', 'N/A') if meta else 'N/A'}")
        print(f"  章节: {meta.get('section', 'N/A') if meta else 'N/A'}")
        print(f"  内容: {doc[:200]}...")
        print()


def test_hybrid_search(query: str, city: Optional[str] = None, top_k: int = 5):
    """
    测试混合检索（向量 + 关键词 + RRF融合）

    Args:
        query: 查询文本
        city: 可选，限定城市
        top_k: 返回结果数量
    """
    vector_db = VectorDBService()
    hybrid_engine = HybridSearchEngine(vector_db)

    print("=" * 60)
    print(f"混合检索查询: {query}")
    if city:
        print(f"限定城市: {city}")
    print(f"返回数量: {top_k}")
    print("=" * 60)

    # 获取查询向量
    query_embedding = get_embedding(query)
    if not query_embedding:
        print("获取查询向量失败")
        return

    results = hybrid_engine.search(
        query=query,
        query_embedding=query_embedding,
        city=city,
        top_k=top_k
    )

    if not results:
        print("\n未找到匹配结果")
        return

    print(f"\n找到 {len(results)} 条结果:\n")

    for i, result in enumerate(results, 1):
        print(f"【结果 {i}】")
        print(f"  城市: {result.get('city', 'N/A')}")
        print(f"  分类: {result.get('category', 'N/A')}")
        print(f"  章节: {result.get('section', 'N/A')}")
        print(f"  内容: {result.get('content', '')[:200]}...")
        print()


def show_collection_stats():
    """显示向量库统计信息"""
    vector_db = VectorDBService()
    stats = vector_db.get_collection_info()

    print("=" * 60)
    print("向量库统计信息")
    print("=" * 60)
    print(f"集合名称: {stats.get('name', 'N/A')}")
    print(f"文档总数: {stats.get('count', 0)}")
    print(f"向量维度: {stats.get('dimension', 'N/A')}")
    print()


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="智旅云图向量库检索测试")
    parser.add_argument("--query", type=str, help="查询文本")
    parser.add_argument("--city", type=str, help="限定城市")
    parser.add_argument("--top-k", type=int, default=5, help="返回数量")
    parser.add_argument("--hybrid", action="store_true", help="使用混合检索")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")

    args = parser.parse_args()

    if args.stats:
        show_collection_stats()
        return

    if args.query:
        if args.hybrid:
            test_hybrid_search(args.query, args.city, args.top_k)
        else:
            test_search(args.query, args.city, args.top_k)
    else:
        # 默认测试查询
        show_collection_stats()
        print("\n运行示例:")
        print("  python backend/tests/test_retrieval.py --query '北京有哪些好吃的餐厅'")
        print("  python backend/tests/test_retrieval.py --query '景点推荐' --city beijing")
        print("  python backend/tests/test_retrieval.py --query '成都美食' --hybrid")


if __name__ == "__main__":
    main()
