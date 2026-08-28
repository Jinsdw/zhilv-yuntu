# ============================================
# 智旅云图 - FastAPI 应用入口（Phase 7.4）
# ============================================
"""
本文件是 FastAPI 应用的唯一装配点（Phase 7.4）。

职责边界（入口只做装配，不做业务）：
    - 应用元数据：title / version 统一读自 app.config.settings，与 .env 一致
    - 生命周期：lifespan 启动时初始化数据库表（storage_service.init_database）
    - 路由注册：prefix / tags 统一在入口管理，路由文件不携带 prefix
    - 中间件：CORS（来源白名单）、请求日志
    - 错误处理：领域异常 → HTTP 状态码，响应体对齐 schemas.ErrorResponse
    - 健康检查：/health 附带依赖健康检查，区分 200 / 503
"""

import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.models.schemas import HealthCheckResponse
from app.services.storage_service import DatabaseError, storage_service
from app.services.trip_service import (
    CityNotSupportedError,
    TripNotFoundError,
    TripServiceError,
)

from loguru import logger as _loguru_logger


class _LoguruInterceptHandler(logging.Handler):
    """将标准 logging 记录（含 uvicorn 访问日志）转发到 loguru，统一落盘。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # 从日志实际发起处回溯，跳过 logging 内部帧，保证源码位置正确
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _route_standard_logging_to_file() -> None:
    """根 logger 与 uvicorn 日志接入 loguru（文件 sink 在 config.py 中注册）。"""
    handler = _LoguruInterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False


_route_standard_logging_to_file()

logger = logging.getLogger(__name__)

# 进程启动时间（用于健康检查 uptime）
_START_TIME = time.time()


def _parse_cors_origins() -> List[str]:
    """解析 CORS 来源白名单；空值或 '*' 视为允许所有来源（禁用凭证）。"""
    raw = getattr(settings, "CORS_ORIGINS", "*").strip()
    if not raw:
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


_CORS_ORIGINS = _parse_cors_origins()
# Starlette 规定：携带凭证的跨域不允许通配来源，二者互斥。
_ALLOW_CREDENTIALS = "*" not in _CORS_ORIGINS


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库表，关闭时预留资源释放扩展点。"""
    if not storage_service.init_database():
        logger.error("数据库表初始化失败，服务仍将启动（/health 会标记 unhealthy）")
    logger.info(f"{settings.PROJECT_NAME} 启动完成 (version={settings.VERSION})")
    yield
    logger.info(f"{settings.PROJECT_NAME} 已关闭")


# 创建 FastAPI 应用（元数据读自 settings）
app = FastAPI(
    title=f"{settings.PROJECT_NAME} API",
    description="多Agent协同的智能旅游行程规划助手",
    version=settings.VERSION,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "行程", "description": "行程生成、编辑、历史查询与删除"},
        {"name": "导出", "description": "行程导出为 Markdown / PDF"},
        {"name": "天气", "description": "城市实时天气与未来预报查询"},
        {"name": "系统", "description": "根路径与健康检查"},
    ],
)

# ----------------------------------------
# 中间件：CORS（来源白名单）
# ----------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------
# 中间件：请求日志（method / path / status / 耗时）
# ----------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} -> "
        f"{response.status_code} ({duration_ms:.1f}ms)"
    )
    return response


# ----------------------------------------
# 系统端点：根路径 / 健康检查
# ----------------------------------------
@app.get("/", tags=["系统"])
async def root():
    """根路径：返回服务元信息。"""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health", response_model=HealthCheckResponse, tags=["系统"])
async def health_check(response: Response):
    """
    健康检查端点：附带数据库依赖健康检查。

    数据库连通 → 200 + status=healthy；断开 → 503 + status=unhealthy。
    """
    db = storage_service.health_check()
    db_ok = db.get("database") == "connected"

    response.status_code = 200 if db_ok else 503
    return HealthCheckResponse(
        status="healthy" if db_ok else "unhealthy",
        version=settings.VERSION,
        uptime=time.time() - _START_TIME,
        dependencies={"database": "connected" if db_ok else "disconnected"},
    )


# ----------------------------------------
# 路由注册（Phase 7.2）
# prefix / tags 统一在入口管理，路由文件不携带 prefix。
# ----------------------------------------
from app.api.routes import export, trip, weather

app.include_router(trip.router, prefix="/trip", tags=["行程"])
app.include_router(export.router, prefix="/export", tags=["导出"])
app.include_router(weather.router, prefix="/weather", tags=["天气"])


# ----------------------------------------
# 全局异常处理器（领域异常 → HTTP 状态码）
# 响应体对齐 schemas.ErrorResponse 的 error_code / error_message。
# ----------------------------------------
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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """FastAPI/Starlette 抛出的 HTTPException（含 404 路由未匹配、weather 503）→ 保留状态码并统一响应体。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": "HTTP_ERROR", "error_message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """未捕获异常兜底 → 500，日志记录堆栈，响应体不泄漏内部细节。"""
    logger.exception(f"未捕获异常: {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "error_message": "服务器内部错误"},
    )
