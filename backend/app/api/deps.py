"""
智旅云图 - API 依赖（设备标识）

职责：从请求中解析浏览器设备指纹标识（X-Device-Id header）。
项目无登录体系，上线后以该标识做历史记录的数据隔离与归属校验。

设计要点：
    - get_device_id_optional：可选读取，用于行程生成等不读取私有数据的接口
    - require_device_id：强制读取，用于历史列表/详情/编辑/删除/收藏/导出等
      涉及个人数据的接口；缺失或格式非法时抛 400 DEVICE_ID_REQUIRED
    - header 别名对齐前端 axios 拦截器统一附加的 X-Device-Id
"""

from typing import Optional

from fastapi import Header, HTTPException

DEVICE_ID_HEADER = "X-Device-Id"
MAX_DEVICE_ID_LEN = 128


def get_device_id_optional(
    x_device_id: Optional[str] = Header(default=None, alias=DEVICE_ID_HEADER),
) -> Optional[str]:
    """可选读取设备标识；空值返回 None。"""
    value = (x_device_id or "").strip()
    return value or None


def require_device_id(
    x_device_id: Optional[str] = Header(default=None, alias=DEVICE_ID_HEADER),
) -> str:
    """强制读取设备标识；缺失或超长抛 400。"""
    value = (x_device_id or "").strip()
    if not value:
        raise HTTPException(
            status_code=400,
            detail="缺少设备标识头 X-Device-Id",
        )
    if len(value) > MAX_DEVICE_ID_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"设备标识过长（最大 {MAX_DEVICE_ID_LEN} 字符）",
        )
    return value