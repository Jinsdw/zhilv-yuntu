# ============================================
# 智旅云图 - FastAPI 应用入口
# ============================================
"""
本文件是 FastAPI 应用的入口点。

在第七阶段（API路由层）将完善：
- 路由注册
- 中间件配置
- 健康检查端点
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 创建 FastAPI 应用
app = FastAPI(
    title="智旅云图 API",
    description="多Agent协同的智能旅游行程规划助手",
    version="1.0.0",
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "智旅云图",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"}


# ----------------------------------------
# 路由将在第七阶段添加
# ----------------------------------------
# from app.api.routes import trip, export, weather
# app.include_router(trip.router, prefix="/trip", tags=["行程"])
# app.include_router(export.router, prefix="/export", tags=["导出"])
# app.include_router(weather.router, prefix="/weather", tags=["天气"])
