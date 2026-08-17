"""
智旅云图 - 高德API手动测试脚本

用于测试高德地理编码和逆地理编码接口是否正常工作

使用方法：
    cd backend/tests
    python test_amap_manual.py

脚本会自动从 .env 文件读取 AMAP_API_KEY
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# 加载 .env 文件（项目根目录）
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    if load_dotenv:
        load_dotenv(env_path)
    else:
        # 手动读取
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

# 高德 API Key（从环境变量或 .env 读取）
AMAP_API_KEY: Optional[str] = None

# 高德API地址
GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"


def get_api_key() -> str:
    """获取API Key"""
    global AMAP_API_KEY

    if AMAP_API_KEY:
        return AMAP_API_KEY

    # 尝试从环境变量获取
    env_key = os.environ.get("AMAP_API_KEY")
    if env_key:
        return env_key

    # 交互式输入
    print("=" * 50)
    print("请输入你的高德地图 Web服务 API Key")
    print("(可在 https://lbs.amap.com/dev/key/app 创建)")
    print("=" * 50)
    AMAP_API_KEY = input("请输入 Key: ").strip()
    return AMAP_API_KEY


async def test_geocode(address: str, city: Optional[str] = None) -> dict:
    """
    测试地理编码接口
    将地址转换为经纬度坐标
    """
    import httpx

    params = {
        "key": get_api_key(),
        "address": address,
        "output": "json",
    }
    if city:
        params["city"] = city

    print(f"\n[地理编码] 请求地址: {address}")
    if city:
        print(f"[地理编码] 指定城市: {city}")
    print(f"[地理编码] 请求URL: {GEOCODE_URL}?address={address}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GEOCODE_URL, params=params)
        data = response.json()

        print(f"\n[地理编码] 响应状态: {data.get('status')}")
        print(f"[地理编码] 状态说明: {data.get('info')}")
        print(f"[地理编码] 结果数量: {data.get('count')}")

        if data.get("status") == "1" and data.get("geocodes"):
            geo = data["geocodes"][0]
            print("\n[解析结果]")
            print(f"  国家: {geo.get('country', 'N/A')}")
            print(f"  省份: {geo.get('province', 'N/A')}")
            print(f"  城市: {geo.get('city', 'N/A')}")
            print(f"  城市编码: {geo.get('citycode', 'N/A')}")
            print(f"  区/县: {geo.get('district', 'N/A')}")
            print(f"  行政区划: {geo.get('adcode', 'N/A')}")
            print(f"  街道: {geo.get('street', 'N/A')}")
            print(f"  门牌号: {geo.get('number', 'N/A')}")
            print(f"  经纬度: {geo.get('location', 'N/A')}")
            print(f"  匹配级别: {geo.get('level', 'N/A')}")

            return {
                "success": True,
                "data": geo
            }
        else:
            print("\n[错误] 未找到匹配的地址")
            return {"success": False, "error": data.get("info")}


async def test_regeo(longitude: float, latitude: float, extensions: str = "all") -> dict:
    """
    测试逆地理编码接口
    将经纬度坐标转换为详细地址
    """
    import httpx

    params = {
        "key": get_api_key(),
        "location": f"{longitude},{latitude}",
        "radius": 1000,
        "extensions": extensions,
        "output": "json",
    }

    print(f"\n[逆地理编码] 坐标: {longitude}, {latitude}")
    print(f"[逆地理编码] 搜索半径: 1000米")
    print(f"[逆地理编码] 返回类型: {extensions}")
    print(f"[逆地理编码] 请求URL: {REGEO_URL}?location={longitude},{latitude}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(REGEO_URL, params=params)
        data = response.json()

        print(f"\n[逆地理编码] 响应状态: {data.get('status')}")
        print(f"[逆地理编码] 状态说明: {data.get('info')}")

        if data.get("status") == "1":
            regeocode = data.get("regeocode", {})
            address_component = regeocode.get("addressComponent", {})
            street_number = address_component.get("streetNumber", {})

            print("\n[解析结果]")
            print(f"  国家: {address_component.get('country', 'N/A')}")
            print(f"  省份: {address_component.get('province', 'N/A')}")
            print(f"  城市: {address_component.get('city', 'N/A')}")
            print(f"  城市编码: {address_component.get('citycode', 'N/A')}")
            print(f"  区/县: {address_component.get('district', 'N/A')}")
            print(f"  行政区划: {address_component.get('adcode', 'N/A')}")
            print(f"  乡镇/街道: {address_component.get('township', 'N/A')}")
            print(f"  街道: {street_number.get('street', 'N/A')}")
            print(f"  门牌号: {street_number.get('number', 'N/A')}")
            print(f"  格式化地址: {regeocode.get('formatted_address', 'N/A')}")

            # 商圈信息
            business_areas = address_component.get("businessAreas", [])
            if business_areas and isinstance(business_areas, list) and len(business_areas) > 0:
                print(f"\n  商圈信息 ({len(business_areas)} 个):")
                for i, area in enumerate(business_areas[:5], 1):  # 最多显示5个
                    if isinstance(area, dict):
                        print(f"    {i}. {area.get('name', 'N/A')} - {area.get('location', 'N/A')}")

            # POI信息（如果请求了extensions=all）
            if extensions == "all":
                pois = regeocode.get("pois", [])
                if pois and len(pois) > 0:
                    print(f"\n  附近POI信息 ({len(pois)} 个):")
                    for i, poi in enumerate(pois[:5], 1):  # 最多显示5个
                        if isinstance(poi, dict):
                            print(f"    {i}. {poi.get('name', 'N/A')}")
                            print(f"       类型: {poi.get('type', 'N/A')}")
                            print(f"       地址: {poi.get('address', 'N/A')}")
                            print(f"       距离: {poi.get('distance', 'N/A')}米")

            return {"success": True, "data": regeocode}
        else:
            print("\n[错误] 逆地理编码失败")
            return {"success": False, "error": data.get("info")}


def print_menu():
    """打印菜单"""
    print("\n" + "=" * 50)
    print("高德地图 API 手动测试")
    print("=" * 50)
    print("1. 地理编码 (地址 -> 经纬度)")
    print("2. 逆地理编码 (经纬度 -> 地址)")
    print("3. 测试示例数据")
    print("0. 退出")
    print("=" * 50)


async def run_geocode_test():
    """运行地理编码测试"""
    print("\n" + "-" * 50)
    print("地理编码测试 (地址 -> 经纬度)")
    print("-" * 50)

    address = input("\n请输入地址 (如: 北京市朝阳区阜通东大街6号): ").strip()
    if not address:
        print("[跳过] 未输入地址")
        return

    city = input("指定城市 (直接回车跳过，可填: 北京/杭州/上海等): ").strip()
    city = city if city else None

    await test_geocode(address, city)


async def run_regeo_test():
    """运行逆地理编码测试"""
    print("\n" + "-" * 50)
    print("逆地理编码测试 (经纬度 -> 地址)")
    print("-" * 50)

    coord_str = input("\n请输入经纬度坐标 (格式: 经度,纬度 如: 116.480881,39.989410): ").strip()

    if not coord_str:
        print("[跳过] 未输入坐标")
        return

    try:
        parts = coord_str.split(",")
        if len(parts) != 2:
            raise ValueError("格式错误")
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError:
        print("[错误] 坐标格式错误，请使用 经度,纬度 格式，如: 116.480881,39.989410")
        return

    extensions = input("是否返回POI信息? (all/ base，直接回车默认all): ").strip()
    extensions = extensions if extensions in ["all", "base"] else "all"

    await test_regeo(longitude, latitude, extensions)


async def run_example_tests():
    """运行示例测试"""
    print("\n" + "-" * 50)
    print("示例测试数据")
    print("-" * 50)

    # 示例1: 地理编码 - 天安门
    print("\n>>> 示例1: 地理编码 - 天安门")
    await test_geocode("天安门")



async def main():
    """主函数"""
    print("\n" + "=" * 50)
    print("智旅云图 - 高德API手动测试工具")
    print("=" * 50)

    # 检查API Key
    key = get_api_key()
    if not key:
        print("[错误] 必须提供高德地图 API Key")
        sys.exit(1)

    print(f"\n当前 API Key: {key[:8]}...{key[-4:] if len(key) > 12 else ''}")

    while True:
        print_menu()

        choice = input("\n请选择 (0-3): ").strip()

        if choice == "1":
            await run_geocode_test()
        elif choice == "2":
            await run_regeo_test()
        elif choice == "3":
            await run_example_tests()
        elif choice == "0":
            print("\n感谢使用，再见！")
            break
        else:
            print("\n[错误] 无效选择，请输入 0-3")

        input("\n按回车继续...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n已退出")
