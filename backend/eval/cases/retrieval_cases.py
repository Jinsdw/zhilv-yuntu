"""
检索质量专项评估用例
验证检索系统对特定查询的召回和排序能力
"""

# 检索质量评估用例
RETRIEVAL_CASES = [
    # Case 1: 精确城市+景点
    {
        "case_id": "ret_001",
        "query": "北京天安门故宫",
        "expected_keywords": ["天安门", "故宫"],
        "city": "北京",
        "category": "景点",
        "difficulty": "easy",
    },

    # Case 2: 模糊景点描述
    {
        "case_id": "ret_002",
        "query": "看日出的地方",
        "expected_keywords": ["日出", "日出", "观景"],
        "city": None,
        "category": "景点",
        "difficulty": "medium",
    },

    # Case 3: 餐饮+地点
    {
        "case_id": "ret_003",
        "query": "成都宽窄巷子附近美食",
        "expected_keywords": ["宽窄巷子", "美食", "小吃"],
        "city": "成都",
        "category": "餐饮",
        "difficulty": "easy",
    },

    # Case 4: 行程规划类
    {
        "case_id": "ret_004",
        "query": "西安三天行程安排",
        "expected_keywords": ["行程", "三天", "西安"],
        "city": "西安",
        "category": "行程",
        "difficulty": "medium",
    },

    # Case 5: 住宿类型
    {
        "case_id": "ret_005",
        "query": "洱海海景房",
        "expected_keywords": ["洱海", "海景", "住宿", "民宿"],
        "city": "大理",
        "category": "住宿",
        "difficulty": "medium",
    },

    # Case 6: 高难度 - 多城市比较
    {
        "case_id": "ret_006",
        "query": "哪个城市适合看海",
        "expected_keywords": ["海", "海边", "沙滩"],
        "city": None,
        "category": "general",
        "difficulty": "hard",
    },

    # Case 7: 高难度 - 反向查询
    {
        "case_id": "ret_007",
        "query": "不想去人多的地方",
        "expected_keywords": ["小众", "人少", "安静"],
        "city": None,
        "category": "景点",
        "difficulty": "hard",
    },

    # Case 8: 特定人群
    {
        "case_id": "ret_008",
        "query": "带老人去北京怎么玩",
        "expected_keywords": ["老人", "北京", "轻松"],
        "city": "北京",
        "category": "行程",
        "difficulty": "medium",
    },

    # Case 9: 同义词扩展
    {
        "case_id": "ret_009",
        "query": "吃午饭的地方",
        "expected_keywords": ["餐厅", "美食", "餐饮", "午餐"],
        "city": None,
        "category": "餐饮",
        "difficulty": "medium",
    },

    # Case 10: 长查询
    {
        "case_id": "ret_010",
        "query": "计划下个月和朋友一起去云南大理旅游，大概玩四五天，有什么推荐的行程和必去的景点？",
        "expected_keywords": ["大理", "行程", "景点", "旅游"],
        "city": "大理",
        "category": "行程",
        "difficulty": "medium",
    },

    # Case 11: 口语化查询
    {
        "case_id": "ret_011",
        "query": "大理古城周边有啥子好耍的",
        "expected_keywords": ["大理古城", "景点", "周边"],
        "city": "大理",
        "category": "景点",
        "difficulty": "medium",
    },

    # Case 12: 特定时间段
    {
        "case_id": "ret_012",
        "query": "夏天去三亚热不热，有什么避暑的地方",
        "expected_keywords": ["三亚", "夏天", "避暑"],
        "city": "三亚",
        "category": "general",
        "difficulty": "hard",
    },

    # Case 13: 费用相关
    {
        "case_id": "ret_013",
        "query": "北京三日游大概需要多少钱",
        "expected_keywords": ["北京", "费用", "预算", "花费"],
        "city": "北京",
        "category": "行程",
        "difficulty": "medium",
    },

    # Case 14: 交通相关
    {
        "case_id": "ret_014",
        "query": "成都到九寨沟怎么去",
        "expected_keywords": ["九寨沟", "交通", "路线"],
        "city": "成都",
        "category": "general",
        "difficulty": "hard",
    },

    # Case 15: 季节性推荐
    {
        "case_id": "ret_015",
        "query": "冬天去厦门好玩吗",
        "expected_keywords": ["厦门", "冬天", "季节"],
        "city": "厦门",
        "category": "general",
        "difficulty": "hard",
    },
]

# 难度等级
DIFFICULTY_LEVELS = ["easy", "medium", "hard"]

# 分类列表
CATEGORIES = ["景点", "餐饮", "住宿", "行程", "general"]
