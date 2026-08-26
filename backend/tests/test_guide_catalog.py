"""
智旅云图 - 攻略目录管理单元测试 (Phase 6.2)

验证 GuideCatalog 的核心能力：
- 文件扫描：data/*_guide.md → 沉淀城市白名单
- 白名单校验：resolve_city / is_preset_city
- 文件映射：get_guide_file
- 动态正则：build_city_pattern
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.rag.guide_catalog import GuideCatalog, guide_catalog, _FILENAME_CITY_MAP


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_catalog(tmp_path):
    """用临时目录构造 catalog，不依赖真实 data/ 目录。"""
    # 创建测试攻略文件
    for pinyin, city in _FILENAME_CITY_MAP.items():
        f = tmp_path / f"{pinyin}_guide.md"
        f.write_text(f"# {city}攻略\n## 1. 简介\n{city}是一个旅游城市。\n", encoding="utf-8")

    return GuideCatalog(docs_path=str(tmp_path))


@pytest.fixture
def empty_catalog(tmp_path):
    """空目录的 catalog（无攻略文件）。"""
    return GuideCatalog(docs_path=str(tmp_path))


# ============================================================================
# 6.2.1 GuideCatalog 初始化与扫描
# ============================================================================

class TestCatalogScan:
    """文件扫描 → 城市白名单"""

    def test_scans_all_six_cities(self, temp_catalog):
        cities = temp_catalog.list_preset_cities()
        assert len(cities) == 6
        assert "北京" in cities
        assert "大理" in cities
        assert "成都" in cities
        assert "西安" in cities
        assert "厦门" in cities
        assert "三亚" in cities

    def test_empty_directory_yields_no_cities(self, empty_catalog):
        assert len(empty_catalog.list_preset_cities()) == 0

    def test_global_singleton_has_cities(self):
        """模块级单例应扫描到真实 data/ 目录的 6 个城市。"""
        cities = guide_catalog.list_preset_cities()
        assert len(cities) >= 6
        assert "北京" in cities


# ============================================================================
# 6.2.2 攻略文件 → 目的地映射
# ============================================================================

class TestResolveCity:
    """resolve_city：白名单校验 + 轻量归一化"""

    def test_direct_match(self, temp_catalog):
        assert temp_catalog.resolve_city("北京") == "北京"
        assert temp_catalog.resolve_city("成都") == "成都"

    def test_contains_match(self, temp_catalog):
        """"成都市" 包含 "成都" → "成都" """
        assert temp_catalog.resolve_city("成都市") == "成都"
        assert temp_catalog.resolve_city("北京市") == "北京"
        assert temp_catalog.resolve_city("大理白族自治州") == "大理"

    def test_pinyin_match(self, temp_catalog):
        """模型偶发拼音输出 → 标准城市名"""
        assert temp_catalog.resolve_city("beijing") == "北京"
        assert temp_catalog.resolve_city("chengdu") == "成都"
        assert temp_catalog.resolve_city("ChengDu") == "成都"

    def test_unknown_city_returns_none(self, temp_catalog):
        """非沉淀城市 → None（调用方按 B 级处理）"""
        assert temp_catalog.resolve_city("纽约") is None
        assert temp_catalog.resolve_city("杭州") is None

    def test_none_and_empty(self, temp_catalog):
        assert temp_catalog.resolve_city(None) is None
        assert temp_catalog.resolve_city("") is None
        assert temp_catalog.resolve_city("   ") is None

    def test_strips_whitespace(self, temp_catalog):
        assert temp_catalog.resolve_city("  北京  ") == "北京"


class TestIsPresetCity:
    """is_preset_city：A 级判定"""

    def test_preset_cities_are_true(self, temp_catalog):
        for city in ["北京", "大理", "成都", "西安", "厦门", "三亚"]:
            assert temp_catalog.is_preset_city(city) is True

    def test_dynamic_cities_are_false(self, temp_catalog):
        for city in ["杭州", "上海", "丽江", "青岛"]:
            assert temp_catalog.is_preset_city(city) is False

    def test_alias_is_true(self, temp_catalog):
        """"成都市" → resolve → "成都" ∈ preset → True"""
        assert temp_catalog.is_preset_city("成都市") is True
        assert temp_catalog.is_preset_city("北京市") is True


class TestGetGuideFile:
    """城市 → 攻略文件路径"""

    def test_returns_path_for_preset(self, temp_catalog):
        f = temp_catalog.get_guide_file("北京")
        assert f is not None
        assert f.name == "beijing_guide.md"
        assert f.exists()

    def test_returns_path_for_alias(self, temp_catalog):
        f = temp_catalog.get_guide_file("成都市")
        assert f is not None
        assert f.name == "chengdu_guide.md"

    def test_returns_none_for_unknown(self, temp_catalog):
        assert temp_catalog.get_guide_file("纽约") is None
        assert temp_catalog.get_guide_file("杭州") is None


# ============================================================================
# 6.2.3 动态城市正则生成
# ============================================================================

class TestBuildCityPattern:
    """build_city_pattern：供 QueryPreprocessor 使用"""

    def test_contains_all_preset_cities(self, temp_catalog):
        pattern = temp_catalog.build_city_pattern()
        for city in ["北京", "大理", "成都", "西安", "厦门", "三亚"]:
            assert city in pattern

    def test_contains_dynamic_cities(self, temp_catalog):
        pattern = temp_catalog.build_city_pattern()
        for city in ["上海", "广州", "深圳", "杭州"]:
            assert city in pattern

    def test_pattern_is_valid_regex(self, temp_catalog):
        import re
        pattern = temp_catalog.build_city_pattern()
        # 能编译
        compiled = re.compile(pattern)
        # 能匹配
        assert compiled.search("我想去北京旅游")
        assert compiled.search("成都美食推荐")
        assert compiled.search("杭州西湖")

    def test_pattern_captures_city_name(self, temp_catalog):
        import re
        pattern = temp_catalog.build_city_pattern()
        compiled = re.compile(pattern)
        m = compiled.search("我想去成都旅游")
        assert m is not None
        assert m.group(1) == "成都"


# ============================================================================
# 杂项
# ============================================================================

class TestMisc:
    """refresh / get_catalog_info"""

    def test_get_catalog_info(self, temp_catalog):
        info = temp_catalog.get_catalog_info()
        assert "docs_path" in info
        assert "preset_cities" in info
        assert "guide_files" in info
        assert len(info["preset_cities"]) == 6
        assert info["guide_files"]["北京"] == "beijing_guide.md"

    def test_refresh_rebuilds(self, temp_catalog, tmp_path):
        # 新增一个城市文件
        new_file = tmp_path / "lijiang_guide.md"
        new_file.write_text("# 丽江攻略\n## 1. 简介\n丽江古城。\n", encoding="utf-8")

        # refresh 前不含丽江
        assert "丽江" not in temp_catalog.list_preset_cities()

        # 需要在 _FILENAME_CITY_MAP 中注册才能识别
        with patch.dict("app.rag.guide_catalog._FILENAME_CITY_MAP", {"lijiang": "丽江"}):
            temp_catalog.refresh()
            assert "丽江" in temp_catalog.list_preset_cities()
