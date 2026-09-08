"""
智旅云图 - 坐标/行政区校验工具测试

覆盖 geo_validation 纯函数：中国境内边界、adcode 归属、城市名兜底、综合校验。
"""

from __future__ import annotations

from app.services.geo_validation import (
    adcodes_belong,
    city_names_match,
    is_valid_coordinate,
    is_within_china,
    validate_coordinate_for_city,
)


class TestBounds:
    def test_valid_coordinate(self):
        assert is_valid_coordinate(104.06, 30.67) is True
        assert is_valid_coordinate("104.06", "30.67") is True
        assert is_valid_coordinate(None, 30.67) is False
        assert is_valid_coordinate(104.06, None) is False
        assert is_valid_coordinate(181.0, 0.0) is False
        assert is_valid_coordinate(0.0, 91.0) is False

    def test_china_bounds(self):
        assert is_within_china(104.06, 30.67) is True   # 成都
        assert is_within_china(116.4, 39.9) is True     # 北京
        assert is_within_china(-73.985, 40.758) is False  # 纽约
        assert is_within_china(139.7, 35.6) is False      # 东京
        assert is_within_china(100.0, 2.0) is False       # 南海更南


class TestAdcode:
    def test_municipality_matches_districts(self):
        # 北京 110000（直辖市），区县 110101/110105 以省前缀开头即可
        assert adcodes_belong("110101", "110000") is True
        assert adcodes_belong("110105", "110000") is True

    def test_prefecture_city_matches_districts(self):
        # 成都 510100，锦江区 510104 / 青羊区 510105
        assert adcodes_belong("510104", "510100") is True
        assert adcodes_belong("510105", "510100") is True

    def test_cross_city_rejected(self):
        # 杭州西湖区 330106 不属于成都 510100；昆明 530100 不属于大理 532900
        assert adcodes_belong("330106", "510100") is False
        assert adcodes_belong("530100", "532900") is False

    def test_empty_adcode(self):
        assert adcodes_belong("", "510100") is False
        assert adcodes_belong("510104", "") is False
        assert adcodes_belong("", "") is False


class TestNameMatch:
    def test_suffix_variants(self):
        assert city_names_match("大理", "大理白族自治州") is True
        assert city_names_match("北京", "北京市") is True
        assert city_names_match("成都", "成都市") is True

    def test_cross_city_rejected(self):
        assert city_names_match("成都", "杭州市") is False
        assert city_names_match("大理", "昆明市") is False


class TestValidateCoordinateForCity:
    def test_ok_matching(self):
        ok, reason = validate_coordinate_for_city(
            longitude=104.06,
            latitude=30.67,
            adcode="510104",
            expected_city_adcode="510100",
            city="成都市",
            expected_city="成都",
        )
        assert ok is True
        assert reason == ""

    def test_foreign_rejected(self):
        ok, reason = validate_coordinate_for_city(
            longitude=-73.985,
            latitude=40.758,
            adcode="360111",
            expected_city_adcode="510100",
        )
        assert ok is False
        assert "中国境内" in reason

    def test_wrong_city_rejected(self):
        ok, reason = validate_coordinate_for_city(
            longitude=120.15,
            latitude=30.25,
            adcode="330106",
            expected_city_adcode="510100",
        )
        assert ok is False
        assert "行政区不匹配" in reason

    def test_fail_open_without_any_hint(self):
        ok, _ = validate_coordinate_for_city(
            longitude=104.06,
            latitude=30.67,
            adcode="",
            expected_city_adcode=None,
            city="",
            expected_city="成都",
        )
        assert ok is True

    def test_name_fallback_ok(self):
        ok, _ = validate_coordinate_for_city(
            longitude=104.06,
            latitude=30.67,
            adcode="",
            expected_city_adcode=None,
            city="成都市",
            expected_city="成都",
        )
        assert ok is True

    def test_name_mismatch_rejected(self):
        ok, reason = validate_coordinate_for_city(
            longitude=104.06,
            latitude=30.67,
            adcode="",
            expected_city_adcode=None,
            city="杭州市",
            expected_city="成都",
        )
        assert ok is False
        assert "城市不匹配" in reason

    def test_placeholder_zero_rejected(self):
        ok, _ = validate_coordinate_for_city(
            longitude=0.0,
            latitude=0.0,
            adcode="",
            expected_city_adcode=None,
        )
        assert ok is False
