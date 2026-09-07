"""
智旅云图 - llm_plan_node "Request timed out." 专项诊断脚本

背景
----
生产日志常见：`app.agents.nodes:llm_plan_node:190 - llm_plan_node 调用失败: Request timed out.`
这是 llm_plan_node 内 `llm.invoke(...)`（backend/app/agents/nodes.py:186）抛出的
openai APITimeoutError。单次超时阈值来自 build_llm() 的 timeout=60（llm_factory.py:27），
且 ChatOpenAI 默认 max_retries=2，因此一条 ERROR 日志实际可能已等待约 3 次超时。

本脚本把"超时可能来源"拆成 5 个阶段逐一定位：
  A. 网络层：DNS / TCP 连接 / TLS 握手 / HTTP 首字节(TTFB)，并检查代理环境变量
  B. 小请求直连：确认账号/模型/端点可用性与基线延迟
  C. 生产规模请求：带 RAG 上下文 + POI 候选池 + 多日行程的大 prompt
  D. 直接调用 llm_plan_node：1:1 复刻生产调用路径（同一函数、同一 LLM 工厂）
  E. 强制短超时复现（可选，--force-timeout）：确认错误类型/文案与生产日志一致

更换模型 / 端点 / Key
---------------------
默认使用项目 .env 中 LLM_PROVIDER 对应的配置（zhipu / packycode / deepseek）；
两种方式可覆盖（命令行参数优先级最高，其次文件顶部"手动填写区"）：
  1. 直接编辑本文件顶部【手动填写区】的 DIAG_MODEL / DIAG_BASE_URL / DIAG_API_KEY
  2. 命令行传参：
     python tests/test_llm_timeout_diagnose.py ^
         --model 新模型名 --base-url https://xxx/v1 --api-key xxx --max-retries 0

用法
----
    cd backend
    venv\\Scripts\\python.exe tests\\test_llm_timeout_diagnose.py                  # 全阶段（默认 .env 配置）
    venv\\Scripts\\python.exe tests\\test_llm_timeout_diagnose.py --timeout 30     # 自定义单次超时(秒)
    venv\\Scripts\\python.exe tests\\test_llm_timeout_diagnose.py --timeout 30 --max-retries 0  # 快速失败，不等重试
    venv\\Scripts\\python.exe tests\\test_llm_timeout_diagnose.py --phases a,c     # 只跑 A、C 阶段
    venv\\Scripts\\python.exe tests\\test_llm_timeout_diagnose.py --with-tools     # D 阶段模拟沉淀城市(绑定 RAG 工具)
    venv\\Scripts\\python.exe tests\\test_llm_timeout_diagnose.py --force-timeout  # 额外用 5s 短超时尝试复现

注意：本脚本会真实调用所选模型 API（消耗少量 token），故意不写成 pytest 用例，
避免 `pytest tests/` 在 CI/离线环境误触发真实外部请求。
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Tuple
from unittest.mock import patch
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 【手动填写区】更换模型/端点/Key 时在这里改（默认留空，使用 .env 中当前 LLM_PROVIDER 对应配置）
#   优先级：命令行参数 --model/--base-url/--api-key > 下方字段 > .env
# ---------------------------------------------------------------------------
DIAG_MODEL: str = ""      # 模型名称，如 "glm-4.6v-FlashX" / "deepseek-chat"；留空用 .env 当前平台的模型
DIAG_BASE_URL: str = ""   # OpenAI 兼容端点，如 "https://open.bigmodel.cn/api/paas/v4"；留空用 .env 当前平台的端点
DIAG_API_KEY: str = ""    # API Key；留空用 .env 当前平台的 Key
# ---------------------------------------------------------------------------

# 解析后的诊断配置（main 里赋值，各阶段共用）
_CFG: dict = {"model": "", "base_url": "", "api_key": "", "max_retries": 2}

# ---------------------------------------------------------------------------
# 路径与环境准备（与 test_llm.py 一致：从项目根 .env 读配置）
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def load_env() -> None:
    """加载项目根目录 .env 到环境变量（必须先于 app.config 导入执行）。"""
    if not _ENV_PATH.exists():
        return
    if load_dotenv:
        load_dotenv(_ENV_PATH)
    else:
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


load_env()

from loguru import logger  # noqa: E402

try:
    from app.agents.nodes import llm_plan_node
    from app.agents.trip_planner_agent import SYSTEM_PROMPT, build_user_prompt
    from app.config import get_active_llm_config, settings
    from app.models.schemas import BudgetLevel, TravelStyle, TripRequest
except RuntimeError as exc:
    print("=" * 50)
    print("错误：应用配置加载失败（多为缺少 API Key）")
    print(str(exc))
    print("=" * 50)
    sys.exit(1)

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

_LOG_DIR = _BACKEND_DIR / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / f"llm_diagnose_{datetime.now():%Y%m%d_%H%M%S}.log"

# ---------------------------------------------------------------------------
# 日志：控制台 INFO + 落盘 DEBUG（详细，方便事后比对）
# ---------------------------------------------------------------------------

logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <7}</level> | {message}",
    enqueue=False,
)
logger.add(
    _LOG_FILE,
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} - {message}",
    encoding="utf-8",
    enqueue=False,
    backtrace=True,
    diagnose=True,
)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _ms(sec: float) -> str:
    """秒 → 可读字符串（毫秒级精度）。"""
    if sec < 1:
        return f"{sec * 1000:.1f} ms"
    return f"{sec:.2f} s"


def _mask_key(key: str) -> str:
    """API Key 打码，避免日志泄露。"""
    if not key:
        return "<空>"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _est_tokens(text: Any) -> int:
    """中文场景粗估 token 数（约 3 字符/token）；传入 int 时视为字符数。"""
    if isinstance(text, int):
        return max(1, text // 3)
    return max(1, len(text) // 3)


def _build_diag_llm(timeout: float) -> ChatOpenAI:
    """按解析后的模型/端点/Key 构造 LLM 客户端（可自定义 max_retries）。"""
    return ChatOpenAI(
        model=_CFG["model"],
        api_key=_CFG["api_key"],
        base_url=_CFG["base_url"],
        temperature=0.3,
        max_tokens=4096,
        streaming=False,
        timeout=timeout,
        max_retries=int(_CFG["max_retries"]),
    )


def _make_request(days: int = 5) -> TripRequest:
    """构造一个偏"大"的真实请求：5 天、4 人、带儿童、关键词偏好。"""
    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=days - 1)
    return TripRequest(
        destination="成都",
        start_date=start,
        end_date=end,
        travelers=4,
        budget_level=BudgetLevel.STANDARD,
        travel_style=TravelStyle.FOODIE,
        max_places_per_day=4,
        preferred_keywords=["火锅", "博物馆", "亲子", "夜景"],
        excluded_keywords=["夜店"],
        with_kids=True,
        include_indoor=True,
        include_outdoor=True,
        restaurant_budget_per_meal=80,
    )


def _make_rag_context(chars: int = 2500) -> str:
    """生成一份接近真实攻略长度的 RAG 上下文（纯本地拼装，不打检索）。"""
    blocks = [
        ("成都概况", "成都位于四川盆地西部，四季分明，美食与休闲文化浓厚。市区景点集中，地铁 1/2/3/4 号线覆盖主要区域。"),
        ("经典景点", "武侯祠与锦里相邻，建议 2 小时；宽窄巷子适合傍晚游览；杜甫草堂环境清幽，约需 1.5 小时。大熊猫繁育研究基地建议早上 7:30 前到，熊猫上午活动多，下午多在睡觉。"),
        ("美食推荐", "火锅推荐本地老店，微辣起步；串串香、钵钵鸡、甜水面、蛋烘糕都是特色。人民公园鹤鸣茶社可体验盖碗茶。"),
        ("亲子提示", "带儿童建议每天不超过 3 个景点，注意午休；熊猫基地和成都博物馆适合亲子；天府广场附近有购物中心可休整。"),
        ("交通与住宿", "住宿建议选一环内地铁口，春熙路/太古里片区交通最方便。市内打车约 15-30 元，地铁单程 2-6 元。"),
        ("门票与预约", "多数博物馆周一闭馆，热门景点建议提前 1-3 天在官方平台预约门票，节假日需更早。"),
        ("天气与穿着", "成都夏季湿热，带伞防阵雨；冬季湿冷，建议羽绒服。春秋温差大，洋葱式穿搭。"),
    ]
    text = "\n\n".join(f"【{title}】{body}" for title, body in blocks)
    while len(text) < chars:
        text += f"\n【补充】{blocks[0][1]}"
    return text[:chars]


def _make_candidate_sections() -> dict:
    """构造接近 PlaceCandidateService.to_prompt_sections 输出的候选池（不打高德）。"""
    scenic_names = [
        "武侯祠", "锦里古街", "宽窄巷子", "杜甫草堂", "大熊猫繁育研究基地",
        "青城山", "都江堰", "人民公园", "文殊院", "东郊记忆",
        "成都博物馆", "金沙遗址博物馆", "天府广场", "春熙路", "太古里",
        "望江楼公园", "九眼桥", "合江亭", "环球中心", "凤凰山体育公园",
    ]
    food_names = [
        "小龙坎老火锅", "蜀大侠火锅", "马路边边串串", "冒椒火辣", "陈麻婆豆腐",
        "龙抄手", "钟水饺", "甜水面老店", "烤匠烤鱼", "夫妻肺片总店",
    ]
    hotel_names = [
        "成都群光君悦酒店", "宽窄巷子亚朵酒店", "春熙路全季酒店", "锦江宾馆", "成都瑞吉酒店",
    ]
    scenic = [
        {
            "place_id": f"SC{1000 + i}",
            "name": name,
            "rating": round(4.2 + (i % 5) * 0.1, 1),
            "cost": 0 if i % 4 == 0 else 50 + i * 5,
            "coordinate": {"latitude": round(30.55 + i * 0.01, 4), "longitude": round(104.05 + i * 0.01, 4)},
            "district": "青羊区" if i % 2 == 0 else "武侯区",
            "address": f"成都市{['青羊区', '武侯区'][i % 2]}示例路{i + 1}号",
        }
        for i, name in enumerate(scenic_names)
    ]
    food = [
        {
            "place_id": f"FD{2000 + i}",
            "name": name,
            "rating": round(4.0 + (i % 5) * 0.15, 1),
            "cost": 60 + i * 10,
            "coordinate": {"latitude": round(30.60 + i * 0.005, 4), "longitude": round(104.06 + i * 0.005, 4)},
            "district": "锦江区",
            "address": f"成都市锦江区示例巷{i + 1}号",
        }
        for i, name in enumerate(food_names)
    ]
    hotel = [
        {
            "place_id": f"HT{3000 + i}",
            "name": name,
            "rating": round(4.5 - i * 0.1, 1),
            "cost": 300 + i * 120,
            "coordinate": {"latitude": round(30.62 + i * 0.003, 4), "longitude": round(104.07, 4)},
            "district": "锦江区",
            "address": f"成都市锦江区示例大道{i + 1}号",
        }
        for i, name in enumerate(hotel_names)
    ]
    clusters = {
        "武侯祠-锦里片区": ["SC1000", "SC1001", "SC1015", "SC1017"],
        "宽窄巷子-人民公园片区": ["SC1002", "SC1008", "SC1010"],
        "大熊猫基地片区": ["SC1004"],
        "金沙-杜甫草堂片区": ["SC1003", "SC1009"],
    }
    return {"scenic": scenic, "food": food, "hotel": hotel, "clusters": clusters}


def _log_llm_info(llm: Any, tag: str) -> None:
    """把 LLM 客户端的可调参数打出来，方便核对超时/重试配置。"""
    model = getattr(llm, "model_name", None) or getattr(llm, "model", "?")
    root = getattr(llm, "root_client", None)  # timeout/max_retries 在底层 openai client 上
    timeout = getattr(root, "timeout", None) or getattr(llm, "timeout", None)
    max_retries = getattr(root, "max_retries", None) or getattr(llm, "max_retries", None)
    base_url = getattr(root, "base_url", None) or getattr(llm, "openai_api_base", None)
    logger.info(
        f"[{tag}] model={model} base_url={base_url} "
        f"timeout={timeout}s max_retries={max_retries} "
        f"api_key={_mask_key(_CFG['api_key'])}"
    )


def _log_usage(ai: Any, tag: str) -> None:
    """记录 token 用量（若响应元数据里带）。"""
    meta = getattr(ai, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or {}
    if usage:
        logger.info(
            f"[{tag}] token 用量: prompt={usage.get('prompt_tokens', '?')} "
            f"completion={usage.get('completion_tokens', '?')} "
            f"total={usage.get('total_tokens', '?')}"
        )
    else:
        logger.debug(f"[{tag}] 响应元数据未含 token_usage: {meta}")


# ---------------------------------------------------------------------------
# 阶段 A：网络层诊断
# ---------------------------------------------------------------------------


def _phase_a_network() -> Tuple[bool, str]:
    logger.info("=" * 72)
    logger.info("阶段 A：网络层诊断（DNS / TCP / TLS / HTTP 首字节）")
    logger.info("=" * 72)
    base = _CFG["base_url"]
    parsed = urlparse(base)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    logger.info(f"目标端点: {base}（host={host} port={port}）")

    proxies = {
        k: os.environ.get(k)
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy")
    }
    active_proxies = {k: v for k, v in proxies.items() if v}
    if active_proxies:
        logger.warning(f"检测到代理环境变量（httpx 会跟随；下方原始 socket 探测会绕过）: {active_proxies}")
    else:
        logger.info("未设置 http(s)_proxy / ALL_PROXY 环境变量")

    # 1) DNS
    dns_ms: Optional[float] = None
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        ip = infos[0][4][0]
        dns_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"DNS 解析成功: {host} -> {ip}（{dns_ms:.1f} ms）")
    except Exception as exc:
        logger.error(f"DNS 解析失败: {type(exc).__name__}: {exc}")
        return False, "DNS 解析失败"

    # 2) TCP 连接 + TLS 握手（绕过代理的原始探测）
    tcp_ms: Optional[float] = None
    tls_ms: Optional[float] = None
    sock: Optional[Any] = None
    try:
        t0 = time.perf_counter()
        sock = socket.create_connection((host, port), timeout=10.0)
        tcp_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"TCP 连接成功: {tcp_ms:.1f} ms")
        if port == 443:
            t0 = time.perf_counter()
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
            tls_ms = (time.perf_counter() - t0) * 1000
            logger.info(f"TLS 握手成功: {tls_ms:.1f} ms（协议 {sock.version()}）")
    except Exception as exc:
        logger.error(f"TCP/TLS 原始探测失败: {type(exc).__name__}: {exc}")
        logger.warning("若配置了代理，原始 socket 绕过代理失败属正常，以下方 HTTP 探测为准")
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    # 3) HTTP 请求（httpx，跟随代理）——测真实链路的首字节/总耗时
    try:
        import httpx

        logger.info(f"httpx 版本: {httpx.__version__}")
        url = base.rstrip("/") + "/models"
        t0 = time.perf_counter()
        with httpx.Client(timeout=httpx.Timeout(15.0), follow_redirects=False) as client:
            resp = client.get(url)
        total_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"HTTP GET {url} -> status={resp.status_code}（总耗时 {total_ms:.1f} ms）")
        if resp.status_code == 401:
            logger.info("返回 401 属预期（未带 Key），说明链路可达、服务在线")
        ok = True
        note = f"HTTP {resp.status_code}，总耗时 {_ms(total_ms / 1000)}"
    except Exception as exc:
        logger.error(f"HTTP 请求失败: {type(exc).__name__}: {exc}")
        return False, f"HTTP 请求失败: {exc}"

    # 阶段结论
    slow_marks = []
    if dns_ms is not None and dns_ms > 200:
        slow_marks.append(f"DNS {dns_ms:.0f}ms")
    if tcp_ms is not None and tcp_ms > 500:
        slow_marks.append(f"TCP {tcp_ms:.0f}ms")
    if tls_ms is not None and tls_ms > 500:
        slow_marks.append(f"TLS {tls_ms:.0f}ms")
    if total_ms > 2000:
        slow_marks.append(f"HTTP {total_ms:.0f}ms")
    if slow_marks:
        logger.warning(f"网络层存在偏慢环节: {'、'.join(slow_marks)}（>1-2s 可能是代理/链路问题）")
    else:
        logger.success("网络层各项耗时正常")
    return ok, note


# ---------------------------------------------------------------------------
# 阶段 B：小请求直连（基线）
# ---------------------------------------------------------------------------


def _phase_b_small_llm(timeout: float) -> Tuple[bool, str]:
    logger.info("=" * 72)
    logger.info(f"阶段 B：小请求直连（单次超时 {timeout}s，含内部重试需乘 max_retries+1）")
    logger.info("=" * 72)
    llm = _build_diag_llm(timeout)
    _log_llm_info(llm, "小请求")

    messages = [HumanMessage(content="请用一句话介绍北京。")]
    logger.info(f"请求消息数: {len(messages)}，总字符: {sum(len(str(m.content)) for m in messages)}")
    t0 = time.perf_counter()
    try:
        ai = llm.invoke(messages)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.error(f"小请求失败（耗时 {_ms(elapsed)}）: {type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - t0
    content = str(ai.content or "")
    logger.success(f"小请求成功（耗时 {_ms(elapsed)}，返回 {len(content)} 字符）")
    _log_usage(ai, "小请求")
    if elapsed > timeout * 0.8:
        logger.warning(f"耗时已达超时阈值的 80%（{timeout * 0.8:.0f}s），大请求很容易超时")
    return True, f"OK {_ms(elapsed)}"


# ---------------------------------------------------------------------------
# 阶段 C：生产规模请求
# ---------------------------------------------------------------------------


def _build_production_messages() -> Tuple[list, str]:
    """构造与生产等价的大 prompt：RAG 上下文 + POI 候选池 + 多日行程要求。"""
    request = _make_request(days=5)
    rag_context = _make_rag_context(2500)
    sections = _make_candidate_sections()
    prompt = build_user_prompt(
        request,
        context=rag_context,
        candidate_sections=sections,
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    total_chars = sum(len(str(m.content)) for m in messages)
    logger.info(
        f"构造生产规模请求: 消息数={len(messages)} 总字符={total_chars} "
        f"（估算 tokens ≈ {_est_tokens(total_chars)}，prompt 部分 {len(prompt)} 字符）"
    )
    return messages, rag_context


def _phase_c_production_llm(timeout: float) -> Tuple[bool, str]:
    logger.info("=" * 72)
    logger.info(f"阶段 C：生产规模请求（单次超时 {timeout}s）")
    logger.info("=" * 72)
    llm = _build_diag_llm(timeout)
    _log_llm_info(llm, "生产规模")

    messages, _ = _build_production_messages()
    t0 = time.perf_counter()
    try:
        ai = llm.invoke(messages)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.error(f"生产规模请求失败（耗时 {_ms(elapsed)}）: {type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - t0
    content = str(ai.content or "")
    logger.success(f"生产规模请求成功（耗时 {_ms(elapsed)}，返回 {len(content)} 字符）")
    _log_usage(ai, "生产规模")
    if elapsed > timeout * 0.8:
        logger.warning(f"耗时已达超时阈值 80%，与生产日志中的超时高度相关：请求规模就是瓶颈")
    return True, f"OK {_ms(elapsed)}"


# ---------------------------------------------------------------------------
# 阶段 D：直接调用 llm_plan_node（1:1 复刻生产路径）
# ---------------------------------------------------------------------------


def _phase_d_llm_plan_node(timeout: float, with_tools: bool) -> Tuple[bool, str]:
    logger.info("=" * 72)
    logger.info(f"阶段 D：直接调用 llm_plan_node（use_tools={with_tools}，单次超时 {timeout}s）")
    logger.info("=" * 72)

    _, rag_context = _build_production_messages()
    request = _make_request(days=5)
    sections = _make_candidate_sections()
    state: dict = {
        "request": request,
        "rag_context": rag_context,
        "candidate_sections": sections,
        "use_tools": with_tools,
        "meta": {"tool_rounds": 0, "path": "llm"},
    }
    logger.debug(f"state 键: {sorted(state.keys())}；request: 目的地={request.destination} "
                 f"天数={(request.end_date - request.start_date).days + 1} 人数={request.travelers}")

    # 生产里 llm_plan_node 用 build_llm() 默认 60s；这里临时 patch 成诊断配置，
    # 其余参数与生产完全一致（同一节点函数、同一消息构造）。
    def _build_diag(**kwargs: Any):
        return _build_diag_llm(timeout)

    t0 = time.perf_counter()
    with patch("app.agents.nodes.build_llm", side_effect=_build_diag):
        result = llm_plan_node(state)
    elapsed = time.perf_counter() - t0

    error = result.get("error")
    if error:
        logger.error(f"llm_plan_node 返回 error（耗时 {_ms(elapsed)}）: {error}")
        lowered = str(error).lower()
        if "timed out" in lowered or "timeout" in lowered:
            logger.error(
                "★ 已在 llm_plan_node 上复现与生产日志完全同源的问题："
                "`llm_plan_node 调用失败: Request timed out.`（openai APITimeoutError）"
            )
        return False, f"{error}（{_ms(elapsed)}）"

    ai = result.get("messages", [])[-1]
    tool_calls = getattr(ai, "tool_calls", None)
    content = str(ai.content or "")
    meta = result.get("meta", {})
    logger.success(f"llm_plan_node 调用成功（耗时 {_ms(elapsed)}，返回 {len(content)} 字符，"
                   f"tool_calls={len(tool_calls) if tool_calls else 0}）")
    if tool_calls:
        logger.info(f"本轮产出 {len(tool_calls)} 个 tool_call：生产环境还会再回 llm_plan_node 一次，"
                    f"总耗时为多轮之和，每轮独立 60s 超时")
    logger.debug(f"node 返回 meta: {meta}")
    return True, f"OK {_ms(elapsed)}（tool_calls={len(tool_calls) if tool_calls else 0}）"


# ---------------------------------------------------------------------------
# 阶段 E：短超时强制复现（可选）
# ---------------------------------------------------------------------------


def _phase_e_force_timeout() -> Tuple[bool, str]:
    logger.info("=" * 72)
    logger.info("阶段 E：用 5s 短超时尝试强制复现超时（验证错误文案与生产一致）")
    logger.info("=" * 72)
    llm = _build_diag_llm(5.0)
    _log_llm_info(llm, "强制超时")
    messages, _ = _build_production_messages()

    t0 = time.perf_counter()
    try:
        ai = llm.invoke(messages)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.error(f"强制超时复现成功（{_ms(elapsed)} 后失败）: {type(exc).__name__}: {exc}")
        if str(exc).strip() == "Request timed out.":
            logger.error("★ 错误文案与生产日志完全一致: `Request timed out.`（openai APITimeoutError）")
        return False, f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - t0
    logger.success(f"5s 超时未触发（{_ms(elapsed)} 内完成），说明当前服务端响应快，超时属偶发/负载波动")
    return True, f"未复现（{_ms(elapsed)} 内完成）"


# ---------------------------------------------------------------------------
# 汇总与结论
# ---------------------------------------------------------------------------


def _print_summary(rows: list[Tuple[str, bool, Optional[str], str]]) -> None:
    logger.info("=" * 72)
    logger.info("诊断汇总")
    logger.info("=" * 72)
    for phase, ok, elapsed, note in rows:
        status = "PASS" if ok else "FAIL"
        logger.info(f"  [{phase}] {status} | 耗时 {elapsed or '-'} | {note}")

    a_ok = rows[0][1]
    b_ok = rows[1][1]
    c_ok = rows[2][1]
    d_ok = rows[3][1]

    logger.info("─" * 72)
    if not a_ok:
        logger.error("结论：问题出在【网络层】——连端点都不通/很慢，llm_plan_node 自然超时。"
                     "先修网络：代理、DNS、容器出网，或用 curl/Test-NetConnection 复核。")
    elif not b_ok:
        logger.error("结论：问题出在【账号/模型/端点】——最小请求都失败。"
                     "核对 API Key / 模型名 / 端点地址，以及服务商控制台余额与限流。")
    elif not c_ok:
        logger.error("结论：问题出在【请求规模】——小请求正常，一旦带上 RAG 上下文 + 候选池 + 多日要求就超时。"
                     "建议压缩 prompt、降低 max_tokens，或把 timeout 调大并加重试；也可换更快的模型验证。")
    elif not d_ok:
        logger.error("结论：问题在【llm_plan_node 生产路径】复现（与日志同源）。"
                     "建议在 llm_plan_node 内加耗时/消息大小日志 + 重试，确认具体是哪一轮、多大请求超时。")
    elif len(rows) > 4 and not rows[4][1]:
        logger.warning("结论：当前链路与请求规模都正常，但短超时能复现错误文案——生产超时更可能是偶发波动/服务端负载。"
                       "建议加指数退避重试 + 把 timeout 提为配置项。")
    else:
        logger.success("结论：当前全部阶段通过，未复现超时。若线上仍偶发，建议加耗时日志持续观测，"
                       "并在 llm_plan_node 增加重试以吸收偶发波动。")
    logger.info("─" * 72)


def _resolve_config(args: argparse.Namespace) -> None:
    """解析诊断配置：命令行参数 > 文件顶部手动填写区 > .env。"""
    active = get_active_llm_config()
    model = args.model or DIAG_MODEL or active["model"]
    base_url = (args.base_url or DIAG_BASE_URL or active["base_url"]).rstrip("/")
    api_key = args.api_key or DIAG_API_KEY or active["api_key"]
    _CFG.update(model=model, base_url=base_url, api_key=api_key, max_retries=args.max_retries)

    sources = []
    sources.append(f"模型: {model}（{'参数' if args.model else '手动填写区' if DIAG_MODEL else '.env'}）")
    sources.append(f"端点: {base_url}（{'参数' if args.base_url else '手动填写区' if DIAG_BASE_URL else '.env'}）")
    sources.append(f"Key: {_mask_key(api_key)}（{'参数' if args.api_key else '手动填写区' if DIAG_API_KEY else '.env'}）")
    sources.append(f"max_retries: {args.max_retries}")

    # 同步到 settings，保证阶段 A 网络探测与日志展示用的是同一套配置
    if settings.LLM_PROVIDER == "packycode":
        settings.PACKY_MODEL = model
        settings.PACKY_BASE_URL = base_url
        settings.PACKY_API_KEY = api_key
    elif settings.LLM_PROVIDER == "deepseek":
        settings.DEEPSEEK_MODEL = model
        settings.DEEPSEEK_BASE_URL = base_url
        settings.DEEPSEEK_API_KEY = api_key
    else:
        settings.ZHIPU_MODEL = model
        settings.LLM_BASE_URL = base_url
        settings.ZHIPU_API_KEY = api_key
    logger.info("诊断配置: " + " | ".join(sources))


def main() -> None:
    parser = argparse.ArgumentParser(description="llm_plan_node 超时诊断脚本（可换模型/端点/Key）")
    parser.add_argument("--model", default=None, help="模型名称，覆盖手动填写区与 .env，如 glm-4.6v-FlashX")
    parser.add_argument("--base-url", default=None, help="OpenAI 兼容端点地址，如 https://open.bigmodel.cn/api/paas/v4")
    parser.add_argument("--api-key", default=None, help="API Key（也可在文件顶部手动填写区填写）")
    parser.add_argument("--max-retries", type=int, default=2, help="失败重试次数（默认 2，与生产一致；快速失败可设 0）")
    parser.add_argument("--timeout", type=float, default=60.0, help="单次 LLM 请求超时（秒），默认 60 与生产一致")
    parser.add_argument("--phases", default="a,b,c,d", help="要执行的阶段，逗号分隔，如 a,b,c,d,e")
    parser.add_argument("--with-tools", action="store_true", help="D 阶段模拟沉淀城市：绑定 RAG 工具")
    parser.add_argument("--force-timeout", action="store_true", help="追加 E 阶段：5s 短超时强制复现")
    args = parser.parse_args()

    _resolve_config(args)

    if not _CFG["api_key"].strip():
        logger.error("未找到 API Key：请通过 --api-key、文件顶部手动填写区或项目 .env 配置后重试")
        sys.exit(1)

    logger.info("=" * 72)
    logger.info("llm_plan_node 超时诊断开始")
    logger.info("=" * 72)
    logger.info(
        f"环境: python {sys.version.split()[0]} | {sys.platform} | "
        f"模型 {_CFG['model']} | 端点 {_CFG['base_url']} | Key {_mask_key(_CFG['api_key'])}"
    )
    logger.info(f"详细日志已落盘: {_LOG_FILE}")

    phases = [p.strip().lower() for p in args.phases.split(",") if p.strip()]
    if args.force_timeout and "e" not in phases:
        phases.append("e")

    rows: list[Tuple[str, bool, Optional[str], str]] = []
    for phase in phases:
        t0 = time.perf_counter()
        if phase == "a":
            ok, note = _phase_a_network()
        elif phase == "b":
            ok, note = _phase_b_small_llm(args.timeout)
        elif phase == "c":
            ok, note = _phase_c_production_llm(args.timeout)
        elif phase == "d":
            ok, note = _phase_d_llm_plan_node(args.timeout, args.with_tools)
        elif phase == "e":
            ok, note = _phase_e_force_timeout()
        else:
            logger.warning(f"未知阶段: {phase}，跳过")
            continue
        elapsed = time.perf_counter() - t0
        rows.append((phase, ok, _ms(elapsed), note))
        logger.info(f"── 阶段 {phase.upper()} 结束，耗时 {_ms(elapsed)} ──")

    if not rows:
        logger.error("没有执行任何阶段，请检查 --phases 参数")
        sys.exit(1)

    _print_summary(rows)
    logger.info(f"详细日志文件: {_LOG_FILE}")


if __name__ == "__main__":
    main()
