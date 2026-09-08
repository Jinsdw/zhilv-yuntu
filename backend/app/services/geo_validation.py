"""
智旅云图 - 地图坐标/行政区校验工具

拦截高德返回的越界坐标（定位到其他省份或国外）：
- 中国境内粗边界校验（经纬度范围）
- adcode 行政区归属校验（省/市/区前缀匹配）
- 城市名兜底匹配（adcode 缺失时用省/市名做包含判断）

纯函数、无 IO，便于单测。调用方（POI 候选池 / geocode 补全）在坐标写入行程前过滤。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# 中国境内粗略经纬度边界（含南海诸岛，比国界略宽松）
CHINA_MIN_LNG = 73.0
CHINA_MAX_LNG = 136.0
CHINA_MIN_LAT = 3.0
CHINA_MAX_LAT = 54.0

# 城市名常见行政区后缀（用于名称兜底匹配时归一化）
_CITY_SUFFIX_RE = re.compile(r"(自治州|自治县|地区|特别行政区|市|州|盟|县|区|旗)$")


def is_valid_coordinate(longitude, latitude) -> bool:
    """基础合法性：有限数值且在经纬度范围内。"""
    if longitude is None or latitude is None:
        return False
    try:
        lng = float(longitude)
        lat = float(latitude)
    except (TypeError, ValueError):
        return False
    return -180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0


def is_within_china(longitude, latitude) -> bool:
    """中国境内粗边界校验（拦截明显定位到国外的坐标）。"""
    if not is_valid_coordinate(longitude, latitude):
        return False
    lng = float(longitude)
    lat = float(latitude)
    return CHINA_MIN_LNG <= lng <= CHINA_MAX_LNG and CHINA_MIN_LAT <= lat <= CHINA_MAX_LAT


def _strip_adcode(adcode: str) -> str:
    """去掉 adcode 尾部补零，得到行政区有效前缀。"""
    return (adcode or "").strip().rstrip("0")


def adcodes_belong(candidate_adcode: str, city_adcode: str) -> bool:
    """
    判断 candidate_adcode 是否属于 city_adcode 的行政区范围。

    规则（按有效前缀逐级匹配）：
    - 直辖市/省级目标（如 110000 → "11"）：区县 adcode 以省前缀开头即可
    - 地级市目标（如 532900 → "5329"）：区县 adcode 以市前缀开头即可
    - 区县级目标（如 110105）：需前缀一致
    """
    cand = _strip_adcode(candidate_adcode)
    city = _strip_adcode(city_adcode)
    if not cand or not city:
        return False
    return cand.startswith(city)


def _normalize_city_name(name: str) -> str:
    """去掉常见行政区后缀，用于名称兜底匹配。"""
    if not name:
        return ""
    return _CITY_SUFFIX_RE.sub("", name.strip())


def city_names_match(expected_city: str, actual_city: str) -> bool:
    """城市名兜底匹配：任意方向包含即算匹配（如 大理 ↔ 大理白族自治州）。"""
    expected = _normalize_city_name(expected_city)
    actual = _normalize_city_name(actual_city)
    if not expected or not actual:
        return False
    return expected in actual or actual in expected


def validate_coordinate_for_city(
    *,
    longitude,
    latitude,
    adcode: str = "",
    province: str = "",
    city: str = "",
    expected_city_adcode: Optional[str] = None,
    expected_city: str = "",
) -> Tuple[bool, str]:
    """
    综合校验坐标是否可用于目标城市行程。

    判定顺序：
    1. 基础合法性（缺失/非法 → 拒绝）
    2. 中国境内粗边界（国外坐标 → 拒绝）
    3. adcode 归属（目标城市与候选 adcode 都非空时严格校验）
    4. 城市名兜底（adcode 缺失时用省/市名做包含匹配）

    返回 (是否通过, 不通过原因)。
    """
    if not is_valid_coordinate(longitude, latitude):
        return False, "坐标非法（缺失或越界）"

    if not is_within_china(longitude, latitude):
        return False, f"坐标不在中国境内 ({longitude},{latitude})"

    cand_adcode = (adcode or "").strip()
    target_adcode = (expected_city_adcode or "").strip()

    if cand_adcode and target_adcode:
        if adcodes_belong(cand_adcode, target_adcode):
            return True, ""
        return False, f"行政区不匹配（期望 {target_adcode}，实际 {cand_adcode}）"

    # 拿不到 adcode 时用城市名兜底；双方都缺失则放行（fail-open）
    if expected_city and city:
        if city_names_match(expected_city, city):
            return True, ""
        return False, f"城市不匹配（期望 {expected_city}，实际 {city}）"

    return True, ""
