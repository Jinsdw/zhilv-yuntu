"""
智旅云图 - 行程 API 路由（Phase 7.1）

职责：HTTP 入口，仅调用 TripService，不承载业务编排。

分层定位（与 trip_service.py 的 docstring 对齐）：
    - 校验：依赖 schemas 的 Pydantic 模型（FastAPI 自动 422）
    - 编排：全部委托给 trip_service 单例
    - 错误：领域异常（CityNotSupportedError / TripNotFoundError / TripServiceError /
            DatabaseError）冒泡到 app/api/main.py 的全局异常处理器统一转 HTTP 状态码

设计要点：
    - 路由函数声明为同步 def（非 async def）：trip_service.generate_trip /
      edit_trip_day 是同步阻塞调用（内部含 LangGraph graph.invoke + SQLite +
      通过 _run_async 桥接的 amap/weather 异步 IO）。同步 def 会被 FastAPI 丢进
      线程池（run_in_threadpool）执行，避免阻塞事件循环。
    - router 不携带 prefix，由 main.py include 时统一加 /trip，前缀归入口统一管理。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_device_id_optional, require_device_id

from app.models.schemas import (
    TripBatchDeleteRequest,
    TripBatchFavoriteRequest,
    TripBatchResult,
    TripEditRequest,
    TripHistoryListResponse,
    TripRequest,
    TripResponse,
)
from app.services.trip_service import TripNotFoundError, trip_service

router = APIRouter()


@router.post("/generate", response_model=TripResponse, status_code=200)
def generate_trip(
    request: TripRequest,
    device_id: Optional[str] = Depends(get_device_id_optional),
    user_id: Optional[str] = Query(None, description="可选用户ID"),
) -> TripResponse:
    """生成行程（同步阻塞，走线程池；已持久化并回填 trip_id）。"""
    # 设备指纹标识优先，兼容旧客户端通过 query 传 user_id
    return trip_service.generate_trip(request, user_id=device_id or user_id)


@router.post("/edit", response_model=TripResponse, status_code=200)
def edit_trip(
    body: TripEditRequest,
    device_id: str = Depends(require_device_id),
) -> TripResponse:
    """编辑行程指定天。行程不存在时由全局处理器返回 404。"""
    return trip_service.edit_trip_day(
        body.trip_id,
        body.day_number,
        body.instruction,
        user_id=device_id,
        context=body.context,
    )


@router.get("/history", response_model=TripHistoryListResponse, status_code=200)
def list_history(
    device_id: str = Depends(require_device_id),
    destination: Optional[str] = Query(None, description="按目的地筛选"),
    is_favorite: Optional[bool] = Query(None, description="按收藏状态筛选"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    order_by: str = Query("created_at", description="排序字段"),
    order_desc: bool = Query(True, description="是否降序"),
) -> TripHistoryListResponse:
    """行程历史（分页摘要，不含每日明细）。"""
    items, total = trip_service.list_trips(
        user_id=device_id,
        destination=destination,
        is_favorite=is_favorite,
        limit=limit,
        offset=offset,
        order_by=order_by,
        order_desc=order_desc,
    )
    return TripHistoryListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/history/batch-delete", response_model=TripBatchResult, status_code=200)
def batch_delete_trips(
    body: TripBatchDeleteRequest,
    device_id: str = Depends(require_device_id),
) -> TripBatchResult:
    """批量删除行程历史记录。"""
    affected = trip_service.delete_trips(body.trip_ids, user_id=device_id)
    return TripBatchResult(affected=affected, total=len(body.trip_ids))


@router.post("/history/batch-favorite", response_model=TripBatchResult, status_code=200)
def batch_favorite_trips(
    body: TripBatchFavoriteRequest,
    device_id: str = Depends(require_device_id),
) -> TripBatchResult:
    """批量收藏 / 取消收藏行程历史记录。"""
    affected = trip_service.set_favorites(body.trip_ids, body.is_favorite, user_id=device_id)
    return TripBatchResult(affected=affected, total=len(body.trip_ids))


@router.get("/{trip_id}", response_model=TripResponse, status_code=200)
def get_trip_detail(
    trip_id: str = Path(..., description="行程ID"),
    device_id: str = Depends(require_device_id),
) -> TripResponse:
    """获取行程详情（完整 TripResponse，供历史记录点击回看）。"""
    history = trip_service.get_trip(trip_id, user_id=device_id)
    if not history:
        raise TripNotFoundError(f"行程不存在: {trip_id}")
    return history.response


@router.delete("/history/{trip_id}", status_code=204)
def delete_trip(
    trip_id: str = Path(..., description="行程ID"),
    device_id: str = Depends(require_device_id),
) -> None:
    """删除行程。不存在时抛 TripNotFoundError → 全局处理器返回 404。"""
    ok = trip_service.delete_trip(trip_id, user_id=device_id)
    if not ok:
        raise TripNotFoundError(f"行程不存在: {trip_id}")
    return None
