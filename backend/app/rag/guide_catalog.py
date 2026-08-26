"""
智旅云图 - 攻略目录管理 (Phase 6.2)

职责：
    扫描 backend/data/*_guide.md，构建沉淀城市白名单 + 城市→文件映射。
    不负责别名/关键词归一化（交给 LLM），只管文件系统事实。

设计原则：
    - 文件系统是唯一事实来源：有什么攻略文件 = 支持哪些沉淀城市
    - 文件名→中文城市名映射不可省略（文件用拼音命名，系统用中文）
    - 语义归一化（"帝都"→"北京"）交给 LLM，代码侧只做白名单校验

对外接口：
    - resolve_city(name): 白名单校验 + 轻量归一化（直接/包含/拼音匹配）
    - get_guide_file(city): 城市 → 攻略文件路径
    - list_preset_cities(): 所有有攻略的沉淀城市（A级）
    - is_preset_city(city): 是否为沉淀城市
    - build_city_pattern(): 动态生成 retriever 用的城市正则
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

from app.config import settings


# ---------------------------------------------------------------------------
# 文件名 → 中文城市名映射
#
# 这是不可省略的唯一静态数据：攻略文件以拼音命名（beijing_guide.md），
# 但系统内部使用中文城市名。catalog 必须知道哪个文件对应哪个城市。
#
# 这不是"别名索引"（别名索引处理用户输入变体如"北京市"→"北京"），
# 而是文件身份映射——属于文件系统事实的一部分。
#
# 新增沉淀城市时，只需：
#   1. 在 data/ 下新增 {pinyin}_guide.md
#   2. 在此表新增 {pinyin}: "中文名"
# ---------------------------------------------------------------------------

_FILENAME_CITY_MAP: dict[str, str] = {
    "beijing": "北京",
    "dali": "大理",
    "chengdu": "成都",
    "xian": "西安",
    "xiamen": "厦门",
    "sanya": "三亚",
}

# 常见动态城市（B 级），用于 query 预处理的城市提取正则。
# 这些城市没有本地攻略，走高德 POI 候选池。
_DYNAMIC_CITIES: list[str] = [
    "上海", "广州", "深圳", "杭州",
    "苏州", "重庆", "青岛", "武汉", "南京",
]


class GuideCatalog:
    """
    攻略目录管理器。

    启动时扫描 data/*_guide.md，构建：
    - cities: 有攻略文件的沉淀城市集合（白名单）
    - city_files: 城市名 → 攻略文件路径

    对外提供白名单校验、文件查找、动态正则生成。
    """

    def __init__(self, docs_path: Optional[str] = None):
        self._docs_path: Path = self._resolve_docs_path(docs_path)
        self._cities: frozenset[str] = frozenset()
        self._city_files: dict[str, Path] = {}
        self._scan()

    # ------------------------------------------------------------------
    # 路径解析
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_docs_path(override: Optional[str]) -> Path:
        """解析攻略文档目录路径，支持配置覆盖与多级回退。

        路径解析优先级：
        1. 显式 override 参数（测试注入）
        2. __file__ 推导路径（最可靠，不依赖 CWD）
        3. settings 配置（可能相对于项目根目录或 CWD）
        4. 最终回退到 __file__ 推导路径

        每个候选路径都必须包含 *_guide.md 文件才算有效。
        """
        # 1. 显式覆盖
        if override:
            p = Path(override)
            if p.exists():
                return p
            logger.warning(f"指定的攻略目录不存在，回退到默认: {override}")

        # 2. __file__ 推导（最可靠，不依赖 CWD）
        # guide_catalog.py 位于 backend/app/rag/，三级 parent = backend/
        backend_data = Path(__file__).resolve().parent.parent.parent / "data"
        if backend_data.exists() and list(backend_data.glob("*_guide.md")):
            return backend_data

        # 3. settings 配置（Docker / 部署环境可能挂载到别处）
        cfg = settings.GUIDE_DOCS_PATH
        if cfg:
            # 相对于 CWD
            p_cwd = Path(cfg)
            if p_cwd.exists() and list(p_cwd.glob("*_guide.md")):
                return p_cwd
            # 相对于项目根目录（cfg = "./backend/data" → project_root/backend/data）
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            p_root = project_root / cfg
            if p_root.exists() and list(p_root.glob("*_guide.md")):
                return p_root

        # 4. 最终回退
        return backend_data

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------

    def _scan(self) -> None:
        """扫描 data/*_guide.md，构建城市白名单和文件映射。"""
        guide_files = list(self._docs_path.glob("*_guide.md"))
        cities: set[str] = set()
        city_files: dict[str, Path] = {}

        for f in guide_files:
            # beijing_guide.md → beijing
            stem = f.stem.replace("_guide", "")
            city = self._resolve_city_from_filename(stem, f)
            if not city:
                logger.warning(f"无法识别攻略文件对应城市，跳过: {f.name}")
                continue
            cities.add(city)
            city_files[city] = f
            logger.debug(f"攻略目录注册: {city} → {f.name}")

        self._cities = frozenset(cities)
        self._city_files = city_files
        logger.info(
            f"攻略目录扫描完成: {len(self._cities)} 个沉淀城市 "
            f"({', '.join(sorted(self._cities))})"
        )

    @staticmethod
    def _resolve_city_from_filename(stem: str, guide_path: Path) -> Optional[str]:
        """
        从文件名拼音推导中文城市名。

        优先查 _FILENAME_CITY_MAP（显式映射），
        兜底从文件内容首行提取中文城市名。
        """
        # 1. 显式映射
        city = _FILENAME_CITY_MAP.get(stem.lower())
        if city:
            return city

        # 2. 兜底：从文件内容首行提取已知城市名
        try:
            with open(guide_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    for known_city in _FILENAME_CITY_MAP.values():
                        if known_city in line:
                            return known_city
                    break  # 只看第一个非空行
        except Exception as e:
            logger.warning(f"读取攻略文件失败: {guide_path.name}: {e}")

        return None

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def resolve_city(self, name: Optional[str]) -> Optional[str]:
        """
        白名单校验 + 轻量归一化。

        检查顺序:
        1. 直接匹配（"北京" ∈ cities）
        2. 包含匹配（"成都市" contains "成都"）
        3. 拼音匹配（"chengdu" → "成都"，模型偶发拼音输出）
        4. 未命中 → None（调用方按 B 级/动态城市处理）

        注意: 不做语义别名解析（如"帝都"→"北京"），交给 LLM。
        """
        if not name:
            return None
        name = name.strip()
        if not name:
            return None

        # 1. 直接匹配
        if name in self._cities:
            return name

        # 2. 包含匹配（"成都市" → "成都"，"北京" → "北京"）
        for city in self._cities:
            if city in name or name in city:
                return city

        # 3. 拼音匹配（"chengdu" → "成都"）
        name_lower = name.lower()
        if name_lower in _FILENAME_CITY_MAP:
            return _FILENAME_CITY_MAP[name_lower]

        return None

    def get_guide_file(self, city: str) -> Optional[Path]:
        """获取城市的攻略文件路径。"""
        resolved = self.resolve_city(city)
        if resolved:
            return self._city_files.get(resolved)
        return None

    def list_preset_cities(self) -> frozenset[str]:
        """返回所有有攻略的沉淀城市（A 级）。"""
        return self._cities

    def is_preset_city(self, city: str) -> bool:
        """判断是否为沉淀城市（A 级，走 RAG 检索）。"""
        return self.resolve_city(city) is not None

    def build_city_pattern(self) -> str:
        """
        动态生成城市匹配正则，供 QueryPreprocessor 使用。

        包含沉淀城市 + 常见动态城市，按长度降序排列避免短城市名先匹配。
        """
        preset = sorted(self._cities, key=len, reverse=True)
        dynamic = [c for c in _DYNAMIC_CITIES if c not in self._cities]
        # 动态城市也按长度降序
        dynamic.sort(key=len, reverse=True)
        all_cities = preset + dynamic
        return f"({'|'.join(all_cities)})"

    def refresh(self) -> None:
        """重新扫描目录（运行时新增攻略文件后调用）。"""
        self._scan()

    def get_catalog_info(self) -> dict:
        """返回目录摘要信息。"""
        return {
            "docs_path": str(self._docs_path),
            "preset_cities": sorted(self._cities),
            "guide_files": {c: f.name for c, f in self._city_files.items()},
        }


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

guide_catalog = GuideCatalog()
