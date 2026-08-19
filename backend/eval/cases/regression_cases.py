"""
回归测试用例 - 确保系统升级后核心功能不受影响
"""

# P0 - 核心路径必须通过
P0_CASES = [
    {
        "case_id": "reg_p0_001",
        "query": "北京三天行程",
        "required_intent": "itinerary",
        "required_city": "北京",
        "min_relevant_docs": 2,
        "max_latency_ms": 2000,
        "priority": "P0",
    },
    {
        "case_id": "reg_p0_002",
        "query": "成都景点推荐",
        "required_intent": "scenic_spot",
        "required_city": "成都",
        "min_relevant_docs": 3,
        "max_latency_ms": 2000,
        "priority": "P0",
    },
    {
        "case_id": "reg_p0_003",
        "query": "大理美食推荐",
        "required_intent": "dining",
        "required_city": "大理",
        "min_relevant_docs": 2,
        "max_latency_ms": 2000,
        "priority": "P0",
    },
    {
        "case_id": "reg_p0_004",
        "query": "厦门住宿推荐",
        "required_intent": "accommodation",
        "required_city": "厦门",
        "min_relevant_docs": 2,
        "max_latency_ms": 2000,
        "priority": "P0",
    },
]

# P1 - 重要功能
P1_CASES = [
    {
        "case_id": "reg_p1_001",
        "query": "西安五日游行程安排",
        "required_intent": "itinerary",
        "required_city": "西安",
        "min_relevant_docs": 2,
        "max_latency_ms": 3000,
        "priority": "P1",
    },
    {
        "case_id": "reg_p1_002",
        "query": "三亚必玩景点",
        "required_intent": "scenic_spot",
        "required_city": "三亚",
        "min_relevant_docs": 2,
        "max_latency_ms": 3000,
        "priority": "P1",
    },
    {
        "case_id": "reg_p1_003",
        "query": "北京烤鸭哪里好吃",
        "required_intent": "dining",
        "required_city": "北京",
        "min_relevant_docs": 2,
        "max_latency_ms": 3000,
        "priority": "P1",
    },
    {
        "case_id": "reg_p1_004",
        "query": "洱海边住宿",
        "required_intent": "accommodation",
        "required_city": "大理",
        "min_relevant_docs": 2,
        "max_latency_ms": 3000,
        "priority": "P1",
    },
    {
        "case_id": "reg_p1_005",
        "query": "成都到乐山大佛怎么玩",
        "required_intent": "itinerary",
        "required_city": "成都",
        "min_relevant_docs": 1,
        "max_latency_ms": 3000,
        "priority": "P1",
    },
]

# P2 - 边界情况
P2_CASES = [
    {
        "case_id": "reg_p2_001",
        "query": "随便逛逛",
        "required_intent": None,  # 允许任意意图
        "required_city": None,
        "min_relevant_docs": 1,
        "max_latency_ms": 3000,
        "priority": "P2",
    },
    {
        "case_id": "reg_p2_002",
        "query": "出去浪",
        "required_intent": "itinerary",
        "required_city": None,
        "min_relevant_docs": 1,
        "max_latency_ms": 3000,
        "priority": "P2",
    },
    {
        "case_id": "reg_p2_003",
        "query": "你好",
        "required_intent": None,
        "required_city": None,
        "min_relevant_docs": 0,
        "max_latency_ms": 3000,
        "priority": "P2",
    },
    {
        "case_id": "reg_p2_004",
        "query": "help",
        "required_intent": None,
        "required_city": None,
        "min_relevant_docs": 0,
        "max_latency_ms": 3000,
        "priority": "P2",
    },
]

# 合并所有回归用例
REGRESSION_CASES = P0_CASES + P1_CASES + P2_CASES

# 优先级列表
PRIORITY_LEVELS = ["P0", "P1", "P2"]

# P0 用例数量
P0_COUNT = len(P0_CASES)

# P1 用例数量
P1_COUNT = len(P1_CASES)

# P2 用例数量
P2_COUNT = len(P2_CASES)
