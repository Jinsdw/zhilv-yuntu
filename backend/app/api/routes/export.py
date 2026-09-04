"""
智旅云图 - 导出 API 路由（Phase 7.2）

职责：提供行程导出能力，支持 Markdown / PDF 格式下载。

分层定位：
    - 校验：依赖 Path 参数与 ExportOptions 默认值
    - 编排：读取 storage_service，调用 export_service 生成内容
    - 响应：直接返回文件字节流，前端可触发下载

设计要点：
    - 路由函数声明为 async def，与 export_service 的 async 接口对齐
    - 行程不存在时抛出 TripNotFoundError，由全局异常处理器返回 404
    - 文件名基于 trip_name 生成并清理非法字符
"""

import re
from urllib.parse import quote

from fastapi import APIRouter, Path, Response

from app.models.schemas import TripResponse
from app.services.export_service import ExportOptions, export_service
from app.services.storage_service import storage_service
from app.services.trip_service import TripNotFoundError

router = APIRouter()


def _get_trip_response(trip_id: str) -> TripResponse:
    """从存储层读取行程并转换为 TripResponse。"""
    trip_dict = storage_service.get_trip(trip_id)
    if not trip_dict:
        raise TripNotFoundError(trip_id)
    return TripResponse(**trip_dict["response_data"])


def _safe_filename(name: str) -> str:
    """生成安全的文件名字符串。"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def _content_disposition(filename: str) -> str:
    """生成 Content-Disposition 头，支持中文文件名（RFC 5987）。"""
    ascii_name = filename.encode("ascii", errors="replace").decode("ascii") or "export"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/markdown/{trip_id}")
async def export_markdown(trip_id: str = Path(..., description="行程ID")) -> Response:
    """导出行程为 Markdown 文档。"""
    trip_data = _get_trip_response(trip_id)
    options = ExportOptions()
    markdown_content = await export_service.export_to_markdown(trip_data, options)

    filename = f"{_safe_filename(trip_data.trip_name)}.md"

    return Response(
        content=markdown_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": _content_disposition(filename)
        }
    )


@router.get("/pdf/{trip_id}")
async def export_pdf(trip_id: str = Path(..., description="行程ID")) -> Response:
    """导出行程为 PDF 文档。"""
    trip_data = _get_trip_response(trip_id)
    options = ExportOptions()
    pdf_bytes = await export_service.export_to_pdf(trip_data, options)

    filename = f"{_safe_filename(trip_data.trip_name)}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition(filename)
        }
    )

