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
# 路由注册（第七阶段）
# ----------------------------------------
from app.api.routes import export, trip

app.include_router(trip.router, prefix="/trip", tags=["行程"])
app.include_router(export.router, prefix="/export", tags=["导出"])

# weather 路由将在 7.3 阶段注册
# from app.api.routes import weather
# app.include_router(weather.router, prefix="/weather", tags=["天气"])


# ----------------------------------------
# 全局异常处理器（领域异常 → HTTP 状态码）
# 错误码与 schemas.ErrorResponse 的 error_code / error_message 对齐。
# ----------------------------------------
from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.storage_service import DatabaseError
from app.services.trip_service import (
    CityNotSupportedError,
    TripNotFoundError,
    TripServiceError,
)


@app.exception_handler(CityNotSupportedError)
async def city_not_supported_handler(request: Request, exc: CityNotSupportedError):
    """C 级目的地（如省级目的地）→ 400。"""
    return JSONResponse(
        status_code=400,
        content={"error_code": "CITY_NOT_SUPPORTED", "error_message": str(exc)},
    )


@app.exception_handler(TripNotFoundError)
async def trip_not_found_handler(request: Request, exc: TripNotFoundError):
    """行程不存在 → 404。"""
    return JSONResponse(
        status_code=404,
        content={"error_code": "TRIP_NOT_FOUND", "error_message": str(exc)},
    )


@app.exception_handler(TripServiceError)
async def trip_service_error_handler(request: Request, exc: TripServiceError):
    """编排服务通用错误（兜底）→ 500。"""
    return JSONResponse(
        status_code=500,
        content={"error_code": "TRIP_SERVICE_ERROR", "error_message": str(exc)},
    )


@app.exception_handler(DatabaseError)
async def database_error_handler(request: Request, exc: DatabaseError):
    """数据库错误 → 500。"""
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "error_message": str(exc)},
    )
