"""
智旅云图 - 高德POI图片获取测试脚本

测试流程：
    1. 关键词搜索 POI（v3 place/text）
    2. 查询 POI 详情，提取图片列表（v3 place/detail，失败时回退 v5 place/detail）
    3. 下载图片验证 URL 可访问性

使用方法：
    cd backend/tests
    python test_amap_photos_manual.py --keyword "故宫博物院" --city 北京 --download
    python test_amap_photos_manual.py --poi 2 --download        # 取第2个POI
    python test_amap_photos_manual.py                            # 交互模式

脚本会自动从项目根目录 .env 读取 AMAP_API_KEY
注意：高德 v3 的 place/detail 接口已标记废弃，本脚本在 v3 无图/失败时自动回退到 v5 接口。
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# ---------------------------------------------------------------------------
# 环境与配置
# ---------------------------------------------------------------------------

# 加载 .env 文件（项目根目录）
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    if load_dotenv:
        load_dotenv(env_path)
    else:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

# 高德API地址
AMAP_BASE_URL = "https://restapi.amap.com/v3"
PLACE_TEXT_URL_V3 = f"{AMAP_BASE_URL}/place/text"        # v3 关键字搜索
PLACE_DETAIL_URL_V3 = f"{AMAP_BASE_URL}/place/detail"    # v3 详情（已废弃，兼容保留）
PLACE_DETAIL_URL_V5 = "https://restapi.amap.com/v5/place/detail"  # v5 详情（推荐）

# 下载图片时的请求头（部分图源会校验 UA）
DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}


def get_api_key() -> Optional[str]:
    """获取API Key：环境变量 AMAP_API_KEY -> 交互式输入"""
    key = os.environ.get("AMAP_API_KEY")
    if key:
        return key.strip()
    print("=" * 50)
    print("未找到 AMAP_API_KEY 环境变量")
    print("请输入你的高德地图 Web服务 API Key")
    print("(可在 https://lbs.amap.com/dev/key/app 创建)")
    print("=" * 50)
    return input("请输入 Key: ").strip()


# ---------------------------------------------------------------------------
# 高德接口调用
# ---------------------------------------------------------------------------

async def search_pois(client: httpx.AsyncClient, keyword: str, city: str = "") -> List[Dict[str, Any]]:
    """
    调用 v3 place/text 关键字搜索接口，返回 POI 列表。
    每个 POI 包含 id / name / location / address / type 等字段。
    """
    params = {
        "key": get_api_key(),
        "keywords": keyword,
        "offset": 10,        # 每页数量
        "page": 1,
        "extensions": "base",
        "output": "json",
    }
    if city:
        params["city"] = city

    print(f"\n[搜索POI] 关键字: {keyword}" + (f"  城市: {city}" if city else ""))
    print(f"[搜索POI] 请求URL: {PLACE_TEXT_URL_V3}")

    resp = await client.get(PLACE_TEXT_URL_V3, params=params)
    data = resp.json()

    print(f"[搜索POI] 响应状态: {data.get('status')}  说明: {data.get('info')}")

    if data.get("status") != "1":
        print(f"[搜索POI] 失败: {data.get('info')}")
        return []

    pois = data.get("pois", [])
    print(f"[搜索POI] 命中数量: {data.get('count')}  返回数量: {len(pois)}")
    return pois


async def get_poi_detail_v3(client: httpx.AsyncClient, poi_id: str) -> Optional[Dict[str, Any]]:
    """
    调用 v3 place/detail 接口获取 POI 详情（含 photos 字段）。
    注意：该接口已废弃，仅作兼容尝试。
    """
    params = {"key": get_api_key(), "id": poi_id, "output": "json"}
    try:
        resp = await client.get(PLACE_DETAIL_URL_V3, params=params)
        data = resp.json()
        if data.get("status") == "1" and data.get("pois"):
            return data["pois"][0]
    except Exception as exc:  # noqa: BLE001
        print(f"[详情v3] 请求异常: {exc}")
    print("[详情v3] 未取到数据（接口可能已废弃），尝试 v5 详情接口...")
    return None


async def get_poi_detail_v5(client: httpx.AsyncClient, poi_id: str) -> Optional[Dict[str, Any]]:
    """
    调用 v5 place/detail 接口获取 POI 详情（推荐接口，含 photos 字段）。
    v5 返回结构: {"status":"1","pois":[{"id":...,"photos":[...]}]}
    """
    params = {"key": get_api_key(), "id": poi_id}
    try:
        resp = await client.get(PLACE_DETAIL_URL_V5, params=params)
        data = resp.json()
        print(f"[详情v5] 响应状态: {data.get('status')}  说明: {data.get('info')}")
        if data.get("status") == "1" and data.get("pois"):
            return data["pois"][0]
    except Exception as exc:  # noqa: BLE001
        print(f"[详情v5] 请求异常: {exc}")
    return None


# ---------------------------------------------------------------------------
# 图片提取与下载
# ---------------------------------------------------------------------------

def extract_photos_v3(poi: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    从 v3 POI 详情中提取图片列表。
    v3 的 photos 结构: [{"title":..., "url":大图, "preurl":小图}]
    """
    photos: List[Dict[str, str]] = []
    for photo in poi.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        photos.append({
            "title": photo.get("title", ""),
            "url": photo.get("url", ""),          # 大图
            "preurl": photo.get("preurl", ""),    # 压缩小图
        })
    return photos


def extract_photos_v5(poi: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    从 v5 POI 详情中提取图片列表。
    v5 的 photos 结构: [{"title":..., "description":..., "url":...}]（只有大图）
    """
    photos: List[Dict[str, str]] = []
    for photo in poi.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        photos.append({
            "title": photo.get("title", "") or photo.get("description", ""),
            "url": photo.get("url", ""),
            "preurl": "",
        })
    return photos


async def download_image(client: httpx.AsyncClient, url: str, save_path: Path) -> bool:
    """
    下载图片并校验响应确实是图片，返回是否成功。
    """
    try:
        async with client.stream("GET", url, headers=DOWNLOAD_HEADERS,
                                 follow_redirects=True, timeout=30.0) as resp:
            content_type = resp.headers.get("content-type", "")
            if resp.status_code != 200:
                print(f"[下载] HTTP {resp.status_code}，跳过")
                return False
            if not content_type.startswith("image/"):
                print(f"[下载] 响应类型不是图片: {content_type}，跳过")
                return False
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)
        size = save_path.stat().st_size
        print(f"[下载] 成功: {save_path.name} ({size/1024:.1f} KB) 类型: {content_type}")
        return size > 0
    except Exception as exc:  # noqa: BLE001
        print(f"[下载] 异常: {exc}")
        return False


# ---------------------------------------------------------------------------
# 打印与主流程
# ---------------------------------------------------------------------------

def print_poi_list(pois: List[Dict[str, Any]]) -> None:
    """打印POI列表"""
    print("\n" + "-" * 60)
    print(f"共 {len(pois)} 个POI：")
    for i, poi in enumerate(pois, 1):
        print(f"  {i}. {poi.get('name', 'N/A')}")
        print(f"     类型: {poi.get('type', 'N/A')}")
        print(f"     地址: {poi.get('address', 'N/A')}")
        print(f"     坐标: {poi.get('location', 'N/A')}")
        print(f"     ID: {poi.get('id', 'N/A')}")


def print_photos(photos: List[Dict[str, str]]) -> None:
    """打印图片列表"""
    if not photos:
        print("\n[结果] 该POI没有图片（部分POI无图片数据属正常现象）")
        return
    print(f"\n[结果] 共找到 {len(photos)} 张图片：")
    for i, photo in enumerate(photos, 1):
        print(f"  {i}. {photo['title'] or '(无标题)'}")
        print(f"     大图 url:    {photo['url']}")
        if photo["preurl"]:
            print(f"     缩略 preurl: {photo['preurl']}")


async def run_test(args: argparse.Namespace) -> int:
    """执行测试主流程"""
    api_key = get_api_key()
    if not api_key:
        print("[错误] 必须提供高德地图 API Key")
        return 1
    print(f"\n当前 API Key: {api_key[:6]}...{api_key[-4:] if len(api_key) > 10 else ''}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. 搜索POI
        pois = await search_pois(client, args.keyword, args.city)
        if not pois:
            print("[错误] 未找到任何POI")
            return 1

        print_poi_list(pois)

        # 2. 选择POI（命令行指定或交互选择）
        if args.poi:
            index = args.poi
        else:
            if sys.stdin.isatty():
                try:
                    index = int(input(f"\n请选择POI序号 (1-{len(pois)}，回车默认1): ").strip() or "1")
                except ValueError:
                    index = 1
            else:
                index = 1

        if not (1 <= index <= len(pois)):
            print(f"[错误] 序号越界，使用第1个")
            index = 1

        poi = pois[index - 1]
        print(f"\n>>> 已选择: {poi.get('name')} (ID: {poi.get('id')})")

        # 3. 获取详情图片（v3 优先，失败回退 v5）
        photos: List[Dict[str, str]] = []
        detail = await get_poi_detail_v3(client, poi["id"])
        if detail:
            photos = extract_photos_v3(detail)

        if not photos:
            detail = await get_poi_detail_v5(client, poi["id"])
            if detail:
                photos = extract_photos_v5(detail)

        print_photos(photos)

        # 4. 下载图片验证（默认下载大图 url）
        if args.download and photos:
            target_url = photos[0]["url"] or photos[0]["preurl"]
            if not target_url:
                print("[下载] 图片URL为空，跳过")
                return 0
            out_dir = Path(args.output_dir)
            safe_name = "".join(c for c in poi.get("name", "poi") if c not in r'\/:*?"<>|')
            save_path = out_dir / f"{safe_name}_{poi['id']}_{1}{Path(target_url).suffix or '.jpg'}"
            print(f"\n[下载] 保存到: {save_path}")
            await download_image(client, target_url, save_path)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="高德POI图片获取测试脚本")
    parser.add_argument("--keyword", default="故宫博物院", help="搜索关键字（默认: 故宫博物院）")
    parser.add_argument("--city", default="北京", help="城市（默认: 北京，可留空）")
    parser.add_argument("--poi", type=int, default=0, help="自动选择第N个POI（默认交互选择，非终端时取第1个）")
    parser.add_argument("--download", action="store_true", help="下载第一张图片验证可访问性")
    parser.add_argument("--output-dir", default="amap_photos", help="图片保存目录（默认: amap_photos）")
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run_test(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n已退出")
        sys.exit(130)


if __name__ == "__main__":
    main()
