# 山海拾光（智旅云图）全局配置

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from pydantic import model_validator
from pydantic_settings import BaseSettings

load_dotenv()

# 项目根目录（config.py 位于 backend/app/ 下，三级 parent = 项目根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # 项目基础配置
    PROJECT_NAME: str = "山海拾光（智旅云图）"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    # 高德地图 API（从 .env / 环境变量读取）
    AMAP_API_KEY: str = ""
    AMAP_JS_API_KEY: str = ""

    # 大模型平台切换：zhipu（智谱）| zhipu4（智谱 GLM-4 别名）| packycode（PackyAPI，OpenAI 兼容端点）| deepseek（DeepSeek 官方 API）
    # 控制所有"对话/生成"类 LLM 调用：行程生成、JSON 修复、天气建议、意图识别
    LLM_PROVIDER: str = "zhipu"

    # 模型调用超时配置（秒）
    # LLM_TIMEOUT：对话/生成类 LLM 单次请求超时（build_llm 默认值）
    # EMBEDDING_TIMEOUT：Embedding 向量化请求超时（zai SDK）
    LLM_TIMEOUT: float = 60.0
    EMBEDDING_TIMEOUT: float = 30.0

    # LLM_THINKING_ENABLED：是否开启大模型思考（智谱 thinking）并记录思考过程到日志
    # 开启后智谱调用会携带 thinking 参数，返回的 reasoning_content（思考过程）会连同入参写入日志；
    # 若所用模型不支持思考导致报错，可改为 False 关闭。
    LLM_THINKING_ENABLED: bool = True

    # 智谱大模型 API（平台一）
    ZHIPU_API_KEY: str = ""
    ZHIPU_MODEL: str = "glm-4.6v-FlashX"
    LLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    # packycode 大模型 API（平台二，OpenAI 兼容端点）
    PACKY_API_KEY: str = ""
    PACKY_MODEL: str = "deepseek-v4-flash"
    PACKY_BASE_URL: str = "https://www.packyapi.com/v1"

    # DeepSeek 官方 API（平台三，OpenAI 兼容端点）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    # Embedding 配置（从 .env / 环境变量读取；默认 API key 复用 ZHIPU_API_KEY）
    EMBEDDING_MODEL: str = "embedding-3"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    @model_validator(mode="after")
    def _validate_llm_provider(self):
        """LLM_PROVIDER 仅允许 zhipu / zhipu4 / packycode / deepseek。"""
        if self.LLM_PROVIDER not in ("zhipu", "zhipu4", "packycode", "deepseek"):
            raise ValueError(
                f"LLM_PROVIDER 仅支持 'zhipu' / 'zhipu4' / 'packycode' / 'deepseek'，当前为: {self.LLM_PROVIDER!r}"
            )
        return self

    @model_validator(mode="after")
    def _embedding_key_fallback(self):
        """Embedding API Key 为空时，自动复用智谱主 Key。"""
        if not self.EMBEDDING_API_KEY and self.ZHIPU_API_KEY:
            self.EMBEDDING_API_KEY = self.ZHIPU_API_KEY
        return self

    @model_validator(mode="after")
    def _resolve_chroma_path(self):
        """CHROMA_DB_PATH 为相对路径时，基于项目根解析为绝对路径。

        .env 里常写 "./backend/data/chroma_db"，但相对路径依赖进程 CWD：
        从项目根启动 vs 从 backend/ 启动会连到两个不同的库（后者可能是空库），
        导致检索返回空并触发逐级降级。这里统一基于项目根解析。
        """
        p = Path(self.CHROMA_DB_PATH)
        if not p.is_absolute():
            self.CHROMA_DB_PATH = str((_PROJECT_ROOT / p).resolve())
        return self

    # Rerank 模型配置
    RERANK_MODEL: str = "rerank"

    # ChromaDB 配置（绝对路径，避免启动目录不同导致连到不同的库）
    CHROMA_DB_PATH: str = str(_PROJECT_ROOT / "backend" / "data" / "chroma_db")

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./backend/data/trips.db"

    # 缓存配置 (可选，不使用Redis)
    CACHE_ENABLED: bool = False

    # 攻略文档路径
    GUIDE_DOCS_PATH: str = "./backend/data"

    # CORS 来源白名单（逗号分隔；"*" 表示允许所有来源并禁用凭证）
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 日志配置
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        # .env 是前后端共用的，会包含前端专属变量（如 AMAP_SECURITY_JS_CODE）。
        # 未在 Settings 中定义的变量一律忽略，避免启动时因 extra_forbidden 报错。
        extra = "ignore"


settings = Settings()


# ============================================================================
# 大模型平台解析
# ============================================================================
def get_active_llm_config() -> dict:
    """
    返回当前 LLM_PROVIDER 对应的生成模型配置。

    Returns:
        {"provider": ..., "model": ..., "base_url": ..., "api_key": ...}
    """
    if settings.LLM_PROVIDER == "packycode":
        return {
            "provider": "packycode",
            "model": settings.PACKY_MODEL,
            "base_url": settings.PACKY_BASE_URL.rstrip("/"),
            "api_key": settings.PACKY_API_KEY,
        }
    if settings.LLM_PROVIDER == "deepseek":
        return {
            "provider": "deepseek",
            "model": settings.DEEPSEEK_MODEL,
            "base_url": settings.DEEPSEEK_BASE_URL.rstrip("/"),
            "api_key": settings.DEEPSEEK_API_KEY,
        }
    # zhipu / zhipu4 均指向智谱平台（同一组 ZHIPU_* 配置）
    return {
        "provider": settings.LLM_PROVIDER,
        "model": settings.ZHIPU_MODEL,
        "base_url": settings.LLM_BASE_URL.rstrip("/"),
        "api_key": settings.ZHIPU_API_KEY,
    }


# ============================================================================
# 日志配置：全量日志落盘（loguru 文件 sink）
# ============================================================================
# backend 目录：config.py 位于 backend/app/ 下，向上两级即 backend 目录。
# 宿主机与容器内路径一致（容器内为 /app/logs/app.log，对应挂载的 backend/logs）
BASE_DIR = Path(__file__).resolve().parents[1]

# 完整日志文件路径（可用环境变量 LOG_FILE_PATH 覆盖）
LOG_FILE_PATH = os.getenv(
    "LOG_FILE_PATH", str(BASE_DIR / "logs" / "app.log")
)

logger.add(
    LOG_FILE_PATH,
    level=os.getenv("LOG_LEVEL", settings.LOG_LEVEL),
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
    enqueue=True,
    backtrace=True,
    diagnose=False,
)


# ============================================================================
# 启动期必填项校验
# ============================================================================
REQUIRED_KEYS = {"AMAP_API_KEY": "高德地图 API Key"}
if settings.LLM_PROVIDER == "packycode":
    REQUIRED_KEYS["PACKY_API_KEY"] = "packycode API Key"
elif settings.LLM_PROVIDER == "deepseek":
    REQUIRED_KEYS["DEEPSEEK_API_KEY"] = "DeepSeek API Key"
else:
    REQUIRED_KEYS["ZHIPU_API_KEY"] = "智谱大模型 API Key"


missing = []
for key, label in REQUIRED_KEYS.items():
    value = getattr(settings, key, "")
    if not value or not str(value).strip():
        missing.append(f"{label} ({key})")

if missing:
    raise RuntimeError(
        "缺少必要的 API Key，请在 .env 文件或环境变量中配置：\n  - "
        + "\n  - ".join(missing)
    )
