"""
山海拾光（智旅云图） - 高德 POI 候选池 → 大模型提示词 手动测试用例

复刻真实业务链路（TripService._invoke_agent 动态城市分支 + llm_plan_node 提示词组装）：
    1. 输入城市 → 构建 TripRequest
    2. place_candidate_service.build_pool_sync(request)
       拉取高德 POI（景点/餐饮/住宿三池 + 区域聚类 + 过滤打分 + 缓存）
    3. PlaceCandidateService.to_prompt_sections(pool)   # 转成结构化候选数据
    4. build_user_prompt(...) + SYSTEM_PROMPT           # 最终提示词，到 LLM 之前停止

不会调用任何大模型；输出：候选池数据（JSON）+ 最终提示词（system/user）。

两种运行模式：
    [默认]  真实高德 API：自动读取项目根 .env 的 AMAP_API_KEY
    --mock 离线模式：用 httpx.MockTransport 替换高德 HTTP 传输层，
           业务逻辑（搜索计划/多路拉取/去重/过滤打分/聚类/提示词）原样跑通

使用方法：
    cd backend
    python tests/test_poi_pool_to_prompt_manual.py 苏州 --save          # 真实 API
    python tests/test_poi_pool_to_prompt_manual.py 杭州 --mock --save   # 离线 mock
    pytest tests/test_poi_pool_to_prompt_manual.py -s                   # 需 RUN_AMAP_MANUAL=1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

# 保证从 backend/ 或项目根都能 import app
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.agents.trip_planner_agent import (  # noqa: E402
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.config import settings  # noqa: E402
from app.models.schemas import (  # noqa: E402
    BudgetLevel,
    TravelStyle,
    TripRequest,
)
from app.services.place_candidate_service import (  # noqa: E402
    PlaceCandidateService,
    place_candidate_service,
)

DEFAULT_CITY = "杭州"
DEFAULT_DAYS = 3
DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "backend" / "data" / "exports"


# ---------------------------------------------------------------------------
# 1. 构造 TripRequest（与真实入参一致）
# ---------------------------------------------------------------------------

def build_request(city: str, days: int = DEFAULT_DAYS) -> TripRequest:
    """日期从今天起 14 天后，保证通过 TripRequest 的日期校验。"""
    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=days - 1)
    return TripRequest(
        destination=city,
        start_date=start,
        end_date=end,
        travelers=2,
        budget_level=BudgetLevel.STANDARD,
        travel_style=TravelStyle.CULTURAL,
        preferred_keywords=["博物馆", "老字号", "经典"],
        excluded_keywords=["酒吧", "夜店"],
        max_places_per_day=4,
        restaurant_budget_per_meal=80.0,
    )


# ---------------------------------------------------------------------------
# 2. 离线 mock：只替换高德 HTTP 传输层，返回符合高德 v3 结构的真实格式响应
# ---------------------------------------------------------------------------

def _mock_amap_transport(city: str):
    """构造 httpx.MockTransport，按 URL 返回高德 v3 风格 JSON。"""
    from httpx import MockTransport, Request, Response

    def handler(request: Request) -> Response:
        url = str(request.url)
        params = dict(request.url.params)

        # /v3/config/district：城市中心（供周边搜索）
        if "/config/district" in url:
            return Response(
                200,
                json={
                    "status": "1",
                    "info": "OK",
                    "districts": [
                        {
                            "name": city,
                            "adcode": "320500",
                            "level": "city",
                            "center": "120.5853,31.2989",
                            "citycode": "0512",
                            "province": "江苏省",
                        }
                    ],
                },
            )

        # /v3/place/text 与 /v3/place/around：POI 搜索
        if "/place/text" in url or "/place/around" in url:
            pois = _mock_pois(city, params)
            return Response(
                200,
                json={"status": "1", "info": "OK", "count": len(pois), "pois": pois},
            )

        return Response(200, json={"status": "0", "info": "UNSUPPORTED_URL"})

    return MockTransport(handler)


def _mock_pois(city: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """按高德 v3 place/text（extensions=all）结构生成 POI 列表。

    类型码：110000 风景 / 140100 博物馆 / 110101 公园 / 050000 餐饮 / 100000 住宿。
    故意混入非旅游 POI（公司/停车场）与排除词（酒吧），
    用来验证 5.3.4 过滤打分与排除逻辑真实生效。
    """
    types = params.get("types") or ""
    keywords = params.get("keywords") or ""
    base = {
        "cityname": city,
        "pname": "江苏省",
        "adcode": "320500",
        "adname": "姑苏区",
        "business_area": "观前街",
        "tel": "0512-00000000",
        "tag": "热门",
        "location": "120.5853,31.2989",
        "distance": "500",
        "opening_time": "09:00-17:00",
    }

    def poi(
        pid: str, name: str, typ: str, typecode: str,
        *,
        rating: float = 4.5, cost: float | None = None,
        adname: str = "姑苏区", offset: float = 0.01,
    ) -> dict[str, Any]:
        return {
            **base,
            "id": pid,
            "name": name,
            "type": typ,
            "typecode": typecode,
            "adname": adname,
            "location": f"{120.5853 + offset},{31.2989 - offset}",
            "biz_ext": {"rating": str(rating), "cost": str(cost) if cost is not None else ""},
        }

    scenic = [
        poi("MOCK-S1", f"{city}博物馆", "科教文化服务;博物馆", "140100", rating=4.8, cost=0.0),
        poi("MOCK-S2", f"{city}古城景区", "风景名胜;风景名胜", "110000", rating=4.7, cost=80.0, offset=0.02),
        poi("MOCK-S3", f"{city}中央公园", "风景名胜;公园广场", "110101", rating=4.6, cost=0.0, offset=0.03),
        poi("MOCK-S4", f"{city}老街历史街区", "风景名胜;风景名胜", "110000", rating=4.5, cost=0.0, adname="平江区", offset=0.04),
        poi("MOCK-S5", f"{city}湖滨风景区", "风景名胜;风景名胜", "110000", rating=4.4, cost=30.0, adname="吴中区", offset=0.05),
        poi("MOCK-S6", f"{city}寺", "宗教场所;寺庙", "140600", rating=4.3, cost=20.0, adname="姑苏区", offset=0.06),
        # 非旅游干扰项：应被 _is_non_travel 过滤
        poi("MOCK-J1", f"{city}置业有限公司", "公司企业;公司", "170000", rating=3.0, offset=0.07),
        poi("MOCK-J2", f"{city}小区地下停车场", "汽车服务;停车场", "190500", rating=2.0, offset=0.08),
    ]
    food = [
        poi("MOCK-F1", f"{city}老字号苏帮菜馆", "餐饮服务;中餐厅", "050000", rating=4.6, cost=90.0, offset=0.02),
        poi("MOCK-F2", f"{city}特色汤包馆", "餐饮服务;小吃快餐", "050000", rating=4.5, cost=35.0, offset=0.03),
        poi("MOCK-F3", f"{city}夜市烧烤", "餐饮服务;烧烤", "050000", rating=4.0, cost=60.0, offset=0.04),
        poi("MOCK-F4", f"{city}夜色酒吧", "餐饮服务;酒吧", "050301", rating=4.2, cost=120.0, offset=0.05),
    ]
    hotel = [
        poi("MOCK-H1", f"{city}古城度假酒店", "住宿服务;宾馆酒店", "100000", rating=4.7, cost=420.0, offset=0.02),
        poi("MOCK-H2", f"{city}商务连锁酒店", "住宿服务;宾馆酒店", "100000", rating=4.4, cost=260.0, offset=0.03),
        poi("MOCK-H3", f"{city}青年旅舍", "住宿服务;旅馆招待所", "100100", rating=4.1, cost=120.0, offset=0.04),
    ]

    if types.startswith("05"):
        return food
    if types.startswith("10") or types.startswith("11") and "酒店" in keywords:
        return hotel
    if "酒吧" in keywords or "夜店" in keywords:
        return food
    # 景点类（110000/140100/110101/140600 或关键词含 景点/博物馆/古城/经典）
    return scenic


# ---------------------------------------------------------------------------
# 3. 真实链路：拉池 → 结构化 → 提示词（到 LLM 之前停止）
# ---------------------------------------------------------------------------

def run_pipeline(city: str, days: int = DEFAULT_DAYS, mock: bool = False) -> dict[str, Any]:
    """跑真实业务链路，到 LLM 之前停止，返回池子 + 提示词。"""
    if mock:
        import httpx

        # 只替换高德 HTTP 传输层；搜索计划/拉取/过滤/打分/聚类/提示词逻辑全部原样
        from app.services import map_service as map_service_module

        original = httpx.AsyncClient
        httpx.AsyncClient = lambda *a, **k: original(  # noqa: E731
            *a, **k, transport=_mock_amap_transport(city)
        )
        map_service_module.httpx.AsyncClient = httpx.AsyncClient

    request = build_request(city, days=days)

    # 步骤 2：拉取 POI 候选池（同 TripService._invoke_agent 动态城市分支）
    pool = place_candidate_service.build_pool_sync(request)

    # 步骤 3：分类结构化（景点/餐饮/住宿/区域聚类/index），同生产 to_prompt_sections
    sections = PlaceCandidateService.to_prompt_sections(pool)

    # 步骤 4：组装最终提示词，同 llm_plan_node 在 llm.invoke 之前的行为
    user_prompt = build_user_prompt(request, candidate_sections=sections)

    return {
        "request": request,
        "pool": pool,
        "sections": sections,
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }


# ---------------------------------------------------------------------------
# 4. 输出与保存
# ---------------------------------------------------------------------------

def _pool_json(pool: Any) -> dict[str, Any]:
    return pool.model_dump(mode="json")


def print_summary(result: dict[str, Any]) -> None:
    pool = result["pool"]
    sections = result["sections"]
    print("=" * 78)
    print("【1】候选池摘要")
    print("=" * 78)
    print(f"城市        : {pool.city}")
    print(f"拉取时间    : {pool.fetched_at}")
    print(f"高德原始POI : {pool.raw_count} 个（缓存命中 {pool.cache_hits} 次）")
    print(
        f"成池        : 景点 {len(pool.scenic_places)} / "
        f"餐厅 {len(pool.food_places)} / 酒店 {len(pool.hotel_places)}"
    )
    print(f"区域分组    : {len(pool.district_clusters)} 个 -> {list(pool.district_clusters)}")
    print(f"告警        : {pool.warnings or '无'}")
    print()
    print("=" * 78)
    print("【2】候选池完整数据（JSON）")
    print("=" * 78)
    print(json.dumps(_pool_json(pool), ensure_ascii=False, indent=2))
    print()
    print("=" * 78)
    print("【3】最终提示词（LLM 调用前的 system + user，到此停止）")
    print("=" * 78)
    print("----- SYSTEM_PROMPT -----")
    print(result["system_prompt"])
    print()
    print("----- USER PROMPT -----")
    print(result["user_prompt"])
    print()
    print(
        f"【4】统计：sections 景点 {len(sections.get('scenic') or [])} 个，"
        f"餐厅 {len(sections.get('food') or [])} 个，"
        f"酒店 {len(sections.get('hotel') or [])} 个"
    )
    print(f"用户提示词字符数：{len(result['user_prompt'])}")


def save_output(result: dict[str, Any], city: str, save_dir: Path) -> tuple[Path, Path]:
    save_dir.mkdir(parents=True, exist_ok=True)
    pool_path = save_dir / f"poi_pool_{city}.json"
    prompt_path = save_dir / f"prompt_{city}.md"
    pool_path.write_text(
        json.dumps(_pool_json(result["pool"]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prompt_path.write_text(
        "### SYSTEM_PROMPT\n\n"
        + result["system_prompt"]
        + "\n\n### USER PROMPT\n\n"
        + result["user_prompt"]
        + "\n",
        encoding="utf-8",
    )
    return pool_path, prompt_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="高德 POI 候选池 → 大模型提示词 手动测试")
    parser.add_argument("city", nargs="?", default=DEFAULT_CITY, help=f"城市名（默认 {DEFAULT_CITY}）")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="行程天数（默认 3）")
    parser.add_argument("--mock", action="store_true", help="离线模式：mock 高德 HTTP，不打真实 API")
    parser.add_argument("--save", action="store_true", help="把池子 JSON 和提示词写入 backend/data/exports")
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="输出目录")
    args = parser.parse_args(argv)

    if not args.mock and not settings.AMAP_API_KEY:
        print("未找到 AMAP_API_KEY（项目根 .env），无法拉取真实高德 POI。")
        print("可加 --mock 用离线模式跑通业务链路，或先配置 .env。")
        return 2

    mode = "离线 mock（高德 HTTP 已替换为 MockTransport）" if args.mock else "真实高德 API"
    print(f">>> 开始拉取 {args.city} 的 POI 候选池（{mode}）...")
    try:
        result = run_pipeline(args.city, days=args.days, mock=args.mock)
    except Exception as e:  # noqa: BLE001 - 手动测试要兜住并给出可读错误
        print(f">>> 拉取/成池失败: {e!r}")
        return 1

    print_summary(result)
    if args.save:
        pool_path, prompt_path = save_output(result, args.city, args.save_dir)
        print(f">>> 已保存：{pool_path}")
        print(f">>> 已保存：{prompt_path}")
    return 0


def test_poi_pool_to_prompt_manual():
    """pytest 入口：默认离线 mock 快速验证链路；RUN_AMAP_MANUAL=1 时打真实 API。"""
    import pytest

    city = os.environ.get("TEST_CITY", DEFAULT_CITY)
    use_real = os.environ.get("RUN_AMAP_MANUAL") == "1" and bool(settings.AMAP_API_KEY)
    result = run_pipeline(city, mock=not use_real)
    print_summary(result)
    # 断言真实链路产物完整：有景点池、有最终提示词，且提示词里包含【候选POI】
    assert result["sections"].get("scenic")
    assert result["user_prompt"]
    assert "【候选POI】" in result["user_prompt"]


if __name__ == "__main__":
    raise SystemExit(main())
