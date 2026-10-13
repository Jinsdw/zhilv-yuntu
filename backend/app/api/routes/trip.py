"""
山海拾光（智旅云图） - 行程 API 路由（Phase 7.1）

职责：HTTP 入口，仅调用 TripService，不承载业务编排。

分层定位（与 trip_service.py 的 docstring 对齐）：
    - 校验：依赖 schemas 的 Pydantic 模型（FastAPI 自动 422）
    - 编排：全部委托给 trip_service 单例
    - 错误：领域异常（CityNotSupportedError / TripNotFoundError / TripServiceError /
            DatabaseError）冒泡到 app/api/main.py 的全局异常处理器统一转 HTTP 状态码

设计要点：
    - generate / preview 声明为同步 def（阻塞调用走 FastAPI 线程池）
    - generate/stream 为 async def → StreamingResponse：线程池执行生成，
      事件经 asyncio.Queue 桥接为 SSE 帧（status / poi / draft / final / error）
    - router 不携带 prefix，由 main.py include 时统一加 /trip，前缀归入口统一管理。
"""

import asyncio
import json
from typing import AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from app.api.deps import get_device_id_optional, require_device_id

from app.models.schemas import (
    TripBatchDeleteRequest,
    TripBatchFavoriteRequest,
    TripBatchResult,
    TripHistoryListResponse,
    TripRequest,
    TripResponse,
    TripPreviewResponse,
)
from app.services.trip_service import (
    CityNotSupportedError,
    TripNotFoundError,
    trip_service,
)

router = APIRouter()


def _format_sse_event(event: Dict[str, Any]) -> str:
    """把事件 dict 格式化为 SSE 帧（event: <type> + data: JSON）。"""
    event_type = event.get("type", "message")
    payload = json.dumps(event, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/generate", response_model=TripResponse, status_code=200)
def generate_trip(
    request: TripRequest,
    device_id: Optional[str] = Depends(get_device_id_optional),
    user_id: Optional[str] = Query(None, description="可选用户ID"),
) -> TripResponse:
    """生成行程（同步阻塞，走线程池；已持久化并回填 trip_id）。"""
    # 设备指纹标识优先，兼容旧客户端通过 query 传 user_id
    return trip_service.generate_trip(request, user_id=device_id or user_id)


@router.post("/preview", response_model=TripPreviewResponse, status_code=200)
def preview_trip(
    request: TripRequest,
    device_id: Optional[str] = Depends(get_device_id_optional),
    user_id: Optional[str] = Query(None, description="可选用户ID"),
) -> TripPreviewResponse:
    """行程预览（12.1 方案 A）：快速返回 POI 候选图片池，供生成等待期展示图片墙。

    说明：同步 def 走 FastAPI 线程池（内部 build_pool_sync 为同步阻塞），
    不调用 Agent / LLM，秒级返回；失败由 service 降级为空池，不抛错。
    """
    return trip_service.build_preview(request, user_id=device_id or user_id)


@router.post("/generate/stream")
async def generate_trip_stream(
    request: TripRequest,
    device_id: Optional[str] = Depends(get_device_id_optional),
    user_id: Optional[str] = Query(None, description="可选用户ID"),
) -> StreamingResponse:
    """12.2 方案 B：SSE 流式生成行程。

    事件序列（text/event-stream，每帧 event + data JSON）：
        status(poi_pool/planning) → poi(按类别分批) → draft → status(enrich/weather/finalize) → final
    缓存命中时：status(cache_hit) → final；生成失败：error 帧。
    空闲 15s 发送 `: ping` 心跳注释行保活。
    """
    queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    user = device_id or user_id

    async def run_generate() -> None:
        """线程池执行同步 generate_trip，事件经 call_soon_threadsafe 入队。"""

        def sink(event: Dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        try:
            trip = await asyncio.to_thread(
                trip_service.generate_trip,
                request,
                user_id=user,
                use_cache=True,
                on_event=sink,
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "final", "trip": trip.model_dump(mode="json")},
            )
        except Exception as e:
            logger.warning(f"流式生成失败: {e}")
            code = (
                "CITY_NOT_SUPPORTED"
                if isinstance(e, CityNotSupportedError)
                else "TRIP_SERVICE_ERROR"
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "error_code": code, "message": str(e)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # 结束哨兵

    task = asyncio.create_task(run_generate())

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield _format_sse_event(event)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
