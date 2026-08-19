"""
基础评估用例 - 覆盖核心检索场景
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class BaseEvaluationCase:
    """评估用例基类"""

    case_id: str
    query: str
    expected_intent: Optional[str] = None
    expected_city: Optional[str] = None
    expected_days: Optional[int] = None
    relevant_doc_ids: List[str] = field(default_factory=list)
    expected_keywords: List[str] = field(default_factory=list)
    category: str = "general"
    difficulty: str = "medium"
    priority: str = "P1"


# 基础评估用例库
BASE_CASES = [
    # === 城市+天数+景点类 ===
    BaseEvaluationCase(
        case_id="base_001",
        query="北京三天怎么玩？",
        expected_intent="itinerary",
        expected_city="北京",
        expected_days=3,
        category="行程规划",
        difficulty="easy",
    ),
    BaseEvaluationCase(
        case_id="base_002",
        query="大理玩两天，有什么推荐",
        expected_intent="itinerary",
        expected_city="大理",
        expected_days=2,
        category="行程规划",
        difficulty="easy",
    ),
    BaseEvaluationCase(
        case_id="base_003",
        query="去厦门五日游怎么安排",
        expected_intent="itinerary",
        expected_city="厦门",
        expected_days=5,
        category="行程规划",
        difficulty="medium",
    ),
    BaseEvaluationCase(
        case_id="base_004",
        query="西安四天三晚行程",
        expected_intent="itinerary",
        expected_city="西安",
        expected_days=4,
        category="行程规划",
        difficulty="easy",
    ),

    # === 景点推荐类 ===
    BaseEvaluationCase(
        case_id="base_005",
        query="成都必去的景点有哪些？",
        expected_intent="scenic_spot",
        expected_city="成都",
        category="景点推荐",
        difficulty="easy",
        expected_keywords=["景点", "推荐", "游玩"],
    ),
    BaseEvaluationCase(
        case_id="base_006",
        query="西安有什么打卡的地方",
        expected_intent="scenic_spot",
        expected_city="西安",
        category="景点推荐",
        difficulty="easy",
        expected_keywords=["打卡", "景点", "推荐"],
    ),
    BaseEvaluationCase(
        case_id="base_007",
        query="大理好玩的景点推荐",
        expected_intent="scenic_spot",
        expected_city="大理",
        category="景点推荐",
        difficulty="easy",
        expected_keywords=["景点", "游玩", "推荐"],
    ),
    BaseEvaluationCase(
        case_id="base_008",
        query="厦门哪些景点值得去",
        expected_intent="scenic_spot",
        expected_city="厦门",
        category="景点推荐",
        difficulty="easy",
        expected_keywords=["景点", "值得", "推荐"],
    ),
    BaseEvaluationCase(
        case_id="base_009",
        query="三亚有什么好玩的",
        expected_intent="scenic_spot",
        expected_city="三亚",
        category="景点推荐",
        difficulty="easy",
        expected_keywords=["好玩", "景点", "游玩"],
    ),

    # === 餐饮推荐类 ===
    BaseEvaluationCase(
        case_id="base_010",
        query="厦门有什么好吃的？",
        expected_intent="dining",
        expected_city="厦门",
        category="餐饮推荐",
        difficulty="easy",
        expected_keywords=["美食", "好吃", "餐厅"],
    ),
    BaseEvaluationCase(
        case_id="base_011",
        query="三亚海鲜去哪吃正宗",
        expected_intent="dining",
        expected_city="三亚",
        category="餐饮推荐",
        difficulty="medium",
        expected_keywords=["海鲜", "正宗", "美食"],
    ),
    BaseEvaluationCase(
        case_id="base_012",
        query="成都必吃的美食有哪些",
        expected_intent="dining",
        expected_city="成都",
        category="餐饮推荐",
        difficulty="easy",
        expected_keywords=["美食", "小吃", "推荐"],
    ),
    BaseEvaluationCase(
        case_id="base_013",
        query="大理的特色美食",
        expected_intent="dining",
        expected_city="大理",
        category="餐饮推荐",
        difficulty="easy",
        expected_keywords=["美食", "特色", "小吃"],
    ),
    BaseEvaluationCase(
        case_id="base_014",
        query="西安回民街有什么好吃的",
        expected_intent="dining",
        expected_city="西安",
        category="餐饮推荐",
        difficulty="medium",
        expected_keywords=["回民街", "美食", "小吃"],
    ),

    # === 住宿推荐类 ===
    BaseEvaluationCase(
        case_id="base_015",
        query="在北京住哪里比较方便游玩",
        expected_intent="accommodation",
        expected_city="北京",
        category="住宿推荐",
        difficulty="easy",
        expected_keywords=["住宿", "方便", "位置"],
    ),
    BaseEvaluationCase(
        case_id="base_016",
        query="大理的民宿推荐",
        expected_intent="accommodation",
        expected_city="大理",
        category="住宿推荐",
        difficulty="easy",
        expected_keywords=["民宿", "推荐", "住宿"],
    ),
    BaseEvaluationCase(
        case_id="base_017",
        query="成都春熙路附近酒店",
        expected_intent="accommodation",
        expected_city="成都",
        category="住宿推荐",
        difficulty="medium",
        expected_keywords=["酒店", "春熙路", "住宿"],
    ),
    BaseEvaluationCase(
        case_id="base_018",
        query="厦门鼓浪屿住宿推荐",
        expected_intent="accommodation",
        expected_city="厦门",
        category="住宿推荐",
        difficulty="medium",
        expected_keywords=["住宿", "鼓浪屿", "民宿"],
    ),

    # === 边界/模糊查询类 ===
    BaseEvaluationCase(
        case_id="base_019",
        query="随便逛逛",
        expected_intent=None,
        expected_city=None,
        category="模糊查询",
        difficulty="hard",
    ),
    BaseEvaluationCase(
        case_id="base_020",
        query="出去浪几天",
        expected_intent="itinerary",
        expected_city=None,
        expected_days=None,
        category="模糊查询",
        difficulty="medium",
    ),
    BaseEvaluationCase(
        case_id="base_021",
        query="周末去哪儿玩",
        expected_intent="itinerary",
        expected_city=None,
        expected_days=2,
        category="模糊查询",
        difficulty="medium",
    ),
    BaseEvaluationCase(
        case_id="base_022",
        query="带老人孩子去哪好",
        expected_intent="itinerary",
        expected_city=None,
        category="特殊人群",
        difficulty="hard",
        expected_keywords=["老人", "孩子", "适合"],
    ),
    BaseEvaluationCase(
        case_id="base_023",
        query="亲子游推荐",
        expected_intent="itinerary",
        expected_city=None,
        category="特殊人群",
        difficulty="hard",
        expected_keywords=["亲子", "适合", "孩子"],
    ),
    BaseEvaluationCase(
        case_id="base_024",
        query="情侣出行去哪好",
        expected_intent="itinerary",
        expected_city=None,
        category="特殊人群",
        difficulty="hard",
        expected_keywords=["情侣", "浪漫", "适合"],
    ),
]
