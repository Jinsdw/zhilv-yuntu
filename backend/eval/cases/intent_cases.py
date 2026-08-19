"""
意图识别专项评估用例
验证不同表达方式下的意图识别准确性
"""

# 景点推荐类意图用例
SCENIC_SPOT_CASES = [
    # 标准问法
    {"query": "北京有什么景点", "case_id": "intent_spot_001"},
    {"query": "推荐景点", "case_id": "intent_spot_002"},
    {"query": "有哪些好玩的地方", "case_id": "intent_spot_003"},

    # 口语化表达
    {"query": "去哪玩", "case_id": "intent_spot_004"},
    {"query": "有啥好玩的", "case_id": "intent_spot_005"},
    {"query": "溜达的地方", "case_id": "intent_spot_006"},
    {"query": "逛逛的地方", "case_id": "intent_spot_007"},

    # 带地点限定
    {"query": "成都周边景点推荐", "case_id": "intent_spot_008"},
    {"query": "第一次去西安去哪", "case_id": "intent_spot_009"},
    {"query": "大理城里有什么好玩的", "case_id": "intent_spot_010"},

    # 特定类型景点
    {"query": "博物馆推荐", "case_id": "intent_spot_011"},
    {"query": "适合拍照的地方", "case_id": "intent_spot_012"},
    {"query": "看风景的地方", "case_id": "intent_spot_013"},
    {"query": "古迹遗址有哪些", "case_id": "intent_spot_014"},
    {"query": "网红打卡地推荐", "case_id": "intent_spot_015"},
]

# 餐饮推荐类意图用例
DINING_CASES = [
    {"query": "成都美食", "case_id": "intent_dining_001"},
    {"query": "有啥好吃的", "case_id": "intent_dining_002"},
    {"query": "正宗北京烤鸭", "case_id": "intent_dining_003"},
    {"query": "夜市小吃", "case_id": "intent_dining_004"},
    {"query": "网红餐厅", "case_id": "intent_dining_005"},
    {"query": "当地特色菜", "case_id": "intent_dining_006"},
    {"query": "去哪吃火锅", "case_id": "intent_dining_007"},
    {"query": "必吃的美食", "case_id": "intent_dining_008"},
    {"query": "好吃不贵的餐厅", "case_id": "intent_dining_009"},
    {"query": "美食街推荐", "case_id": "intent_dining_010"},
    {"query": "下午茶去哪", "case_id": "intent_dining_011"},
    {"query": "夜宵推荐", "case_id": "intent_dining_012"},
]

# 住宿推荐类意图用例
ACCOMMODATION_CASES = [
    {"query": "住哪方便", "case_id": "intent_hotel_001"},
    {"query": "性价比高的酒店", "case_id": "intent_hotel_002"},
    {"query": "大理洱海边民宿", "case_id": "intent_hotel_003"},
    {"query": "亲子游住宿推荐", "case_id": "intent_hotel_004"},
    {"query": "推荐住哪里", "case_id": "intent_hotel_005"},
    {"query": "酒店推荐", "case_id": "intent_hotel_006"},
    {"query": "民宿推荐", "case_id": "intent_hotel_007"},
    {"query": "交通方便的住宿", "case_id": "intent_hotel_008"},
    {"query": "海景房推荐", "case_id": "intent_hotel_009"},
    {"query": "适合情侣的酒店", "case_id": "intent_hotel_010"},
    {"query": "青年旅舍", "case_id": "intent_hotel_011"},
    {"query": "五星级酒店推荐", "case_id": "intent_hotel_012"},
]

# 行程规划类意图用例
ITINERARY_CASES = [
    {"query": "北京三日游攻略", "case_id": "intent_itin_001"},
    {"query": "行程怎么安排", "case_id": "intent_itin_002"},
    {"query": "玩几天合适", "case_id": "intent_itin_003"},
    {"query": "路线怎么走", "case_id": "intent_itin_004"},
    {"query": "五天四晚推荐", "case_id": "intent_itin_005"},
    {"query": "周末两天怎么玩", "case_id": "intent_itin_006"},
    {"query": "自由行攻略", "case_id": "intent_itin_007"},
    {"query": "第一次去怎么玩", "case_id": "intent_itin_008"},
    {"query": "七天时间够吗", "case_id": "intent_itin_009"},
    {"query": "行程规划", "case_id": "intent_itin_010"},
    {"query": "有什么值得玩的", "case_id": "intent_itin_011"},
    {"query": "经典路线推荐", "case_id": "intent_itin_012"},
]

# 意图用例字典，按意图类型索引
INTENT_CASES = {
    "scenic_spot": SCENIC_SPOT_CASES,
    "dining": DINING_CASES,
    "accommodation": ACCOMMODATION_CASES,
    "itinerary": ITINERARY_CASES,
}

# 意图名称映射
INTENT_NAMES = {
    "scenic_spot": "景点推荐",
    "dining": "餐饮推荐",
    "accommodation": "住宿推荐",
    "itinerary": "行程规划",
}
