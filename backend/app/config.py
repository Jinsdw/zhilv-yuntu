# 智旅云图全局配置

import os
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # 项目基础配置
    PROJECT_NAME: str = "智旅云图"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    # 高德地图 API（从 .env / 环境变量读取）
    AMAP_API_KEY: str = ""
    AMAP_JS_API_KEY: str = ""

    # 智谱大模型 API（从 .env / 环境变量读取）
    ZHIPU_API_KEY: str = ""
    ZHIPU_MODEL: str = "glm-4.6v-FlashX"

    # LLM API 基础配置
    LLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    # Embedding 配置（从 .env / 环境变量读取；默认 API key 复用 ZHIPU_API_KEY）
    EMBEDDING_MODEL: str = "embedding-3"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    @model_validator(mode="after")
    def _embedding_key_fallback(self):
        """Embedding API Key 为空时，自动复用智谱主 Key。"""
        if not self.EMBEDDING_API_KEY and self.ZHIPU_API_KEY:
            self.EMBEDDING_API_KEY = self.ZHIPU_API_KEY
        return self

    # Rerank 模型配置
    RERANK_MODEL: str = "rerank"

    # ChromaDB 配置
    CHROMA_DB_PATH: str = "./backend/data/chroma_db"

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


settings = Settings()


# ============================================================================
# 启动期必填项校验
# ============================================================================
REQUIRED_KEYS = {
    "AMAP_API_KEY": "高德地图 API Key",
    "ZHIPU_API_KEY": "智谱大模型 API Key",
}

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
