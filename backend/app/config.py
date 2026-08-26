# 智旅云图全局配置

import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # 项目基础配置
    PROJECT_NAME: str = "智旅云图"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    # 高德地图 API
    AMAP_API_KEY: str = "5438fb4d2e66f6bddb30d6d2cfb59dc3"
    AMAP_JS_API_KEY: str = "5438fb4d2e66f6bddb30d6d2cfb59dc3"

    # 智谱大模型 API
    ZHIPU_API_KEY: str = "2335902c7a604d2e836d418f661921ce.w1YJkoCPq7p7HQLG"
    ZHIPU_MODEL: str = "glm-4.6v-FlashX"

    # LLM API 基础配置
    LLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    # Embedding 配置
    EMBEDDING_MODEL: str = "embedding-3"
    EMBEDDING_API_KEY: str = ZHIPU_API_KEY
    EMBEDDING_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

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
