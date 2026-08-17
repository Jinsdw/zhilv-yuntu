"""
智旅云图 - 意图识别器单独测试
直接运行此文件即可测试 IntentDetector

使用方式：
    # 方式1：在项目根目录运行
    python backend/tests/test_intent_detector.py

    # 方式2：在 backend 目录运行（需设置 PYTHONPATH）
    cd backend
    set PYTHONPATH=.
    python tests/test_intent_detector.py

    # 方式3：命令行参数测试单个查询
    python backend/tests/test_intent_detector.py "北京三天怎么玩"
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
from app.rag.retriever import IntentDetector


def test_intent_detector():
    """测试意图检测器的各种查询"""
    detector = IntentDetector()

    test_queries = [
        # 景点相关
        "北京有什么好玩的地方？",
        "推荐几个打卡景点",
        "去大理必玩的景区有哪些",

        # 餐饮相关
        "成都必吃的美食有哪些？",
        "附近有什么好吃的餐厅",
        "北京烤鸭去哪里吃正宗",

        # 住宿相关
        "住在哪里比较方便？",
        "推荐一家性价比高的酒店",
        "大理民宿哪家好",

        # 行程相关
        "北京三天怎么玩？",
        "帮我规划一个五日游行程",
        "第一次去成都怎么安排",

        # 混合意图
        "去北京玩三天，想看景点也吃美食",
        "周末带娃去哪玩，顺便吃饭",
    ]

    print("=" * 60)
    print("意图识别器测试")
    print("=" * 60)

    results = []
    for i, query in enumerate(test_queries, 1):
        print(f"\n【{i}】查询: {query}")

        result = detector.detect(query)

        print(f"    主意图: {result['primary_intent']}")
        print(f"    置信度: {result['confidence']:.2f}")

        if result.get("secondary_intents"):
            print(f"    次意图: {', '.join(result['secondary_intents'])}")

        if result.get("supplementary_terms"):
            print(f"    扩展词: {', '.join(result['supplementary_terms'])}")

        results.append({
            "query": query,
            "result": result
        })

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

    # 统计意图分布
    intent_count = {}
    for r in results:
        intent = r["result"]["primary_intent"]
        intent_count[intent] = intent_count.get(intent, 0) + 1

    print("\n意图分布统计:")
    for intent, count in sorted(intent_count.items()):
        intent_name = {
            "scenic_spot": "景点推荐",
            "dining": "餐饮推荐",
            "accommodation": "住宿推荐",
            "itinerary": "行程规划"
        }.get(intent, intent)
        print(f"  - {intent_name}: {count} 条")

    return results


def test_single_query(query: str):
    """测试单个查询"""
    detector = IntentDetector()

    print(f"\n查询: {query}")
    result = detector.detect(query)

    print(f"\n识别结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 命令行参数：python test_intent.py "查询内容"
        test_single_query(sys.argv[1])
    else:
        # 运行全部测试
        test_intent_detector()
