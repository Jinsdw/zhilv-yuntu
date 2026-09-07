"""
智旅云图 - 智谱大模型连通性手动测试脚本

用于测试智谱大模型（glm-4.6v-FlashX）是否正常工作，包含视觉理解（图生文）。

使用方法：
    cd backend
    python tests/test_llm.py

脚本自动从项目根目录 .env 读取 ZHIPU_API_KEY（与 .env 绑定，无需硬编码）。
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# 项目根目录（tests/ 的上级的上级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# 测试用图片与问题（视觉定位任务）
_IMAGE_URL = (
    "https://cloudcovert-1305175928.cos.ap-guangzhou.myqcloud.com/"
    "%E5%9B%BE%E7%89%87grounding.PNG"
)
_QUESTION ="你好"


def load_env() -> None:
    """加载项目根目录 .env 到环境变量。"""
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


def get_api_key() -> str:
    """从环境变量 / .env 获取智谱 API Key，未配置时给出明确提示。"""
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        print("=" * 50)
        print("错误：未找到 ZHIPU_API_KEY")
        print(f"请在项目根目录 .env 中配置 ZHIPU_API_KEY（当前读取路径：{_ENV_PATH}）")
        print("=" * 50)
        sys.exit(1)
    return api_key


def main() -> None:
    load_env()
    api_key = get_api_key()
    model = os.environ.get("ZHIPU_MODEL", "glm-4.6v-FlashX").strip()

    print(f"使用模型：{model}")
    print(f"API Key：{api_key[:6]}...{api_key[-4:]}（来自 .env）")
    print("正在调用智谱大模型，请稍候...\n")

    from zai import ZhipuAiClient

    client = ZhipuAiClient(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "content": [
                        {"type": "text", "text": _QUESTION},
                    ],
                    "role": "user",
                }
            ],
            thinking={"type": "enabled"},
        )
    except Exception as exc:
        print(f"调用失败：{type(exc).__name__}: {exc}")
        sys.exit(1)

    message = response.choices[0].message
    print("=" * 50)
    print("模型返回内容：")
    print(message.content if message.content is not None else message)
    print("=" * 50)

    usage = getattr(response, "usage", None)
    if usage is not None:
        print(
            "Token 用量："
            f"prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, "
            f"total={usage.total_tokens}"
        )
    print("模型调用成功")


if __name__ == "__main__":
    main()
