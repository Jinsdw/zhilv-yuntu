"""
智旅云图 - 导出服务

提供行程数据的多格式导出功能：
- JSON: 精简版行程数据导出
- PDF: 精美行程报告文档

功能模块：
- 3.6.1 基础框架：枚举、模型、异常类
- 3.6.2 JSON 导出：精简数据导出
- 3.6.3 文件存储管理：本地文件存储与清理
- 3.6.4 PDF 导出：WeasyPrint 渲染

设计决策：
- 导出格式：JSON（精简版）、PDF（精美报告）
- PDF 技术：WeasyPrint + HTML/CSS 模板（Windows 缺 GTK 时自动降级 reportlab 渲染）
- 存储策略：本地文件系统
- 数据范围：仅导出 TripResponse 核心数据
"""

import io
import json
import logging
import os
import re
import tempfile
import urllib.request
import uuid
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..config import settings
from ..models.schemas import TripResponse, ItineraryDay, ItineraryItem, TripTipCategory
from .storage_service import storage_service

# 配置日志
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_EXPORT_DIR = "backend/exports"
DEFAULT_EXPIRE_HOURS = 24


def _first_image(images: List[str], cover: Optional[str] = None) -> Optional[str]:
    """取第一张可用图片 URL（优先封面），供 Markdown 导出使用。"""
    candidates = ([cover] if cover else []) + list(images or [])
    for url in candidates:
        if url and url.strip():
            return url.strip()
    return None


def _md_image(alt: str, url: Optional[str]) -> Optional[str]:
    """构造 Markdown 图片行；URL 用尖括号包裹以兼容特殊字符。"""
    if not url:
        return None
    return f"![{alt}](<{url}>)"


# ==================== 枚举定义 ====================

class ExportFormat(str, Enum):
    """导出格式枚举"""
    JSON = "json"
    PDF = "pdf"


# ==================== 数据模型 ====================

class ExportOptions(BaseModel):
    """导出选项配置"""
    include_budget: bool = True               # 包含预算信息
    include_weather: bool = True              # 包含天气信息
    include_tips: bool = True                # 包含行程贴士
    include_highlights: bool = True           # 包含行程亮点


class ExportRequest(BaseModel):
    """导出请求模型"""
    trip_id: str = Field(..., description="行程ID")
    format: ExportFormat = Field(..., description="导出格式")
    options: ExportOptions = Field(
        default_factory=ExportOptions,
        description="导出选项"
    )


class ExportFileMetadata(BaseModel):
    """导出文件元数据"""
    file_id: str
    file_name: str
    file_path: str
    file_size: int
    format: ExportFormat
    trip_id: str
    created_at: datetime
    expires_at: datetime


class ExportResponse(BaseModel):
    """导出响应模型"""
    success: bool
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    download_url: Optional[str] = None
    file_size: Optional[int] = None
    created_at: Optional[datetime] = None
    error: Optional[str] = None


# ==================== 异常定义 ====================

class ExportError(Exception):
    """导出服务异常基类"""
    def __init__(self, message: str, code: str = "EXPORT_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class TripNotFoundError(ExportError):
    """行程不存在"""
    def __init__(self, trip_id: str):
        super().__init__(
            message=f"行程不存在: {trip_id}",
            code="TRIP_NOT_FOUND"
        )


class UnsupportedFormatError(ExportError):
    """不支持的导出格式"""
    def __init__(self, format: str):
        super().__init__(
            message=f"不支持的导出格式: {format}",
            code="UNSUPPORTED_FORMAT"
        )


class FileWriteError(ExportError):
    """文件写入失败"""
    def __init__(self, path: str, reason: str):
        super().__init__(
            message=f"文件写入失败 {path}: {reason}",
            code="FILE_WRITE_ERROR"
        )


# ==================== 导出服务 ====================

class ExportService:
    """
    导出服务

    提供行程数据的多格式导出功能，支持 JSON 和 PDF 格式。

    使用示例：
        service = ExportService()
        result = await service.export("TRP-xxx", ExportFormat.JSON)
        result = await service.export("TRP-xxx", ExportFormat.PDF)
    """

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        expire_hours: int = DEFAULT_EXPIRE_HOURS,
    ):
        """
        初始化导出服务

        Args:
            storage_dir: 存储目录路径
            expire_hours: 文件过期时间（小时）
        """
        self._storage_dir = Path(storage_dir or DEFAULT_EXPORT_DIR)
        self._expire_hours = expire_hours
        self._file_registry: Dict[str, ExportFileMetadata] = {}
        self._template_dir = Path(__file__).parent / "templates"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """确保必要的目录存在"""
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._template_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"导出服务初始化完成，存储目录: {self._storage_dir}")

    def _generate_file_id(self) -> str:
        """生成唯一文件ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return f"exp_{timestamp}_{unique_id}"

    def _generate_file_name(
        self,
        trip_name: str,
        format: ExportFormat,
    ) -> str:
        """
        生成文件名

        格式：{目的地}_{日期范围}.{格式}
        示例：北京三日游_20260820-20260822.json
        """
        # 清理特殊字符
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', trip_name)

        ext = "json" if format == ExportFormat.JSON else "pdf"
        return f"{safe_name}.{ext}"

    def _get_file_path(self, file_id: str, file_name: str) -> Path:
        """
        获取文件存储路径

        路径结构：{storage_dir}/{year}/{month}/{file_id}/{file_name}
        示例：backend/exports/2026/08/exp_xxx/北京三日游.pdf
        """
        now = datetime.now()
        date_path = self._storage_dir / str(now.year) / f"{now.month:02d}" / file_id
        date_path.mkdir(parents=True, exist_ok=True)
        return date_path / file_name

    def _register_file(self, metadata: ExportFileMetadata) -> None:
        """注册文件元数据"""
        self._file_registry[metadata.file_id] = metadata

    def _get_file_metadata(self, file_id: str) -> Optional[ExportFileMetadata]:
        """获取文件元数据"""
        return self._file_registry.get(file_id)

    def _is_file_expired(self, metadata: ExportFileMetadata) -> bool:
        """检查文件是否过期"""
        return datetime.now() > metadata.expires_at

    # ==================== 数据转换 ====================

    def _transform_trip_to_export(self, trip_data: TripResponse) -> Dict[str, Any]:
        """
        将 TripResponse 转换为导出数据结构（精简版）

        不包含原始请求数据，仅保留行程核心信息。
        """
        itinerary = []

        for day in trip_data.days:
            day_data = self._transform_day(day)
            itinerary.append(day_data)

        export_data = {
            "trip_id": trip_data.trip_id,
            "name": trip_data.trip_name,
            "destination": trip_data.destination,
            "period": {
                "start": trip_data.start_date.isoformat() if hasattr(trip_data.start_date, 'isoformat') else str(trip_data.start_date),
                "end": trip_data.end_date.isoformat() if hasattr(trip_data.end_date, 'isoformat') else str(trip_data.end_date),
                "days": trip_data.total_days,
            },
            "itinerary": itinerary,
            "generated_at": trip_data.generated_at.isoformat() if hasattr(trip_data.generated_at, 'isoformat') else str(trip_data.generated_at),
            "version": trip_data.version,
        }

        # 预算信息
        if trip_data.budget:
            export_data["budget"] = {
                "total": trip_data.budget.total_budget,
                "breakdown": {
                    "accommodation": trip_data.budget.accommodation_budget,
                    "food": trip_data.budget.food_budget,
                    "transportation": trip_data.budget.transportation_budget,
                    "tickets": trip_data.budget.ticket_budget,
                    "shopping": trip_data.budget.shopping_budget,
                    "other": trip_data.budget.other_budget,
                }
            }

        # 行程亮点
        if trip_data.trip_highlights:
            export_data["highlights"] = trip_data.trip_highlights

        # 行程贴士
        if trip_data.trip_tips:
            export_data["tips"] = trip_data.trip_tips
        if trip_data.trip_tips_grouped:
            export_data["tips_grouped"] = [
                {
                    "category": g.category,
                    "icon": g.icon,
                    "tips": g.tips,
                }
                for g in trip_data.trip_tips_grouped
            ]

        return export_data

    def _transform_day(self, day: ItineraryDay) -> Dict[str, Any]:
        """转换单日行程数据"""
        day_data = {
            "day": day.day_number,
            "date": day.itinerary_date.isoformat() if hasattr(day.itinerary_date, 'isoformat') else str(day.itinerary_date),
            "items": [],
            "daily_cost": day.daily_cost,
        }

        # 日主题
        if day.day_theme:
            day_data["theme"] = day.day_theme

        # 天气信息
        if day.weather:
            weather_str = f"{day.weather.weather_type}" if day.weather.weather_type else ""
            if day.weather.temp_high and day.weather.temp_low:
                weather_str += f" {day.weather.temp_low}-{day.weather.temp_high}℃"
            day_data["weather"] = {
                "type": day.weather.weather_type or "未知",
                "temp": f"{day.weather.temp_low}-{day.weather.temp_high}℃" if day.weather.temp_low and day.weather.temp_high else "",
            }

        # 行程项目
        for item in day.items:
            item_data = self._transform_item(item)
            day_data["items"].append(item_data)

        # 餐饮安排
        if day.breakfast:
            day_data["breakfast"] = {
                "name": day.breakfast.name,
                "address": day.breakfast.address,
            }
        if day.lunch:
            day_data["lunch"] = {
                "name": day.lunch.name,
                "address": day.lunch.address,
            }
        if day.dinner:
            day_data["dinner"] = {
                "name": day.dinner.name,
                "address": day.dinner.address,
            }

        return day_data

    def _transform_item(self, item: ItineraryItem) -> Dict[str, Any]:
        """转换单个行程项目"""
        item_data = {
            "time": f"{item.start_time}-{item.end_time}",
            "place": item.place.name,
            "activity": item.activity,
        }

        # 地址
        if item.place.address:
            item_data["address"] = item.place.address

        # 提示
        if item.tips:
            item_data["tips"] = item.tips

        # 亮点
        if item.highlights:
            item_data["highlights"] = item.highlights

        # 费用
        if item.ticket_price:
            item_data["ticket_price"] = item.ticket_price
        if item.food_cost:
            item_data["food_cost"] = item.food_cost

        return item_data

    # ==================== JSON 导出 ====================

    async def export_to_json(
        self,
        trip_data: TripResponse,
        options: Optional[ExportOptions] = None,
    ) -> str:
        """
        导出为 JSON 格式

        Args:
            trip_data: 行程数据
            options: 导出选项

        Returns:
            导出的 JSON 字符串
        """
        # 转换数据
        export_data = self._transform_trip_to_export(trip_data)

        # 根据选项过滤数据
        if options:
            if not options.include_budget and "budget" in export_data:
                del export_data["budget"]
            if not options.include_highlights and "highlights" in export_data:
                del export_data["highlights"]
            if not options.include_tips and "tips" in export_data:
                del export_data["tips"]

        # 序列化
        return json.dumps(export_data, ensure_ascii=False, indent=2)

    # ==================== Markdown 导出 ====================

    async def export_to_markdown(
        self,
        trip_data: TripResponse,
        options: Optional[ExportOptions] = None,
    ) -> str:
        """
        导出为 Markdown 格式

        Args:
            trip_data: 行程数据
            options: 导出选项

        Returns:
            Markdown 字符串
        """
        # 确保 options 有默认值
        opts = options or ExportOptions()

        lines: List[str] = []

        # 封面/标题
        lines.append(f"# {trip_data.trip_name}")
        lines.append("")
        lines.append(f"- **目的地**: {trip_data.destination}")
        lines.append(f"- **日期**: {trip_data.start_date} 至 {trip_data.end_date}")
        lines.append(f"- **天数**: {trip_data.total_days} 天")
        lines.append("")

        # 预算
        if opts.include_budget and trip_data.budget:
            lines.append(f"- **预算总额**: ¥{trip_data.budget.total_budget:.2f}")
            lines.append("")

        # 行程亮点
        if opts.include_highlights and trip_data.trip_highlights:
            lines.append("## 行程亮点")
            lines.append("")
            for highlight in trip_data.trip_highlights:
                lines.append(f"- {highlight}")
            lines.append("")

        # 每日行程
        for day in trip_data.days:
            lines.append(f"## Day {day.day_number} · {day.itinerary_date}")
            if day.day_theme:
                lines.append(f"**主题**: {day.day_theme}")
            lines.append("")

            # 天气
            if opts.include_weather and day.weather:
                weather_str = day.weather.weather_type or ""
                if day.weather.temp_high and day.weather.temp_low:
                    weather_str += f" {day.weather.temp_low}-{day.weather.temp_high}℃"
                if weather_str:
                    lines.append(f" 天气: {weather_str.strip()}")
                    lines.append("")

            # 行程项目
            for item in day.items:
                lines.append(f"### {item.start_time} - {item.end_time} {item.place.name}")
                lines.append(f"- **活动**: {item.activity}")
                if item.place.address:
                    lines.append(f"- **地址**: {item.place.address}")
                image_line = _md_image(
                    item.place.name,
                    _first_image(item.place.images, item.place.cover_image),
                )
                if image_line:
                    lines.append(image_line)
                if item.tips:
                    for tip in item.tips:
                        lines.append(f"- **贴士**: {tip}")
                if item.highlights:
                    for highlight in item.highlights:
                        lines.append(f"- **亮点**: {highlight}")
                if item.ticket_price:
                    lines.append(f"- **门票**: ¥{item.ticket_price}")
                if item.food_cost:
                    lines.append(f"- **餐饮预算**: ¥{item.food_cost}")
                lines.append("")

            # 餐饮安排
            if day.breakfast:
                lines.append(f"🌅 早餐: {day.breakfast.name}")
                if day.breakfast.address:
                    lines.append(f"   地址: {day.breakfast.address}")
                breakfast_image = _md_image(day.breakfast.name, _first_image(day.breakfast.images))
                if breakfast_image:
                    lines.append(f"   {breakfast_image}")
            if day.lunch:
                lines.append(f"🍜 午餐: {day.lunch.name}")
                if day.lunch.address:
                    lines.append(f"   地址: {day.lunch.address}")
                lunch_image = _md_image(day.lunch.name, _first_image(day.lunch.images))
                if lunch_image:
                    lines.append(f"   {lunch_image}")
            if day.dinner:
                lines.append(f"🍽 晚餐: {day.dinner.name}")
                if day.dinner.address:
                    lines.append(f"   地址: {day.dinner.address}")
                dinner_image = _md_image(day.dinner.name, _first_image(day.dinner.images))
                if dinner_image:
                    lines.append(f"   {dinner_image}")

            # 当日费用
            if opts.include_budget:
                lines.append("")
                lines.append(f"💰 当日费用: ¥{day.daily_cost:.2f}")

            lines.append("")

        # 行程贴士
        if opts.include_tips and trip_data.trip_tips:
            lines.append("## 行程贴士")
            lines.append("")
            if trip_data.trip_tips_grouped:
                for group in trip_data.trip_tips_grouped:
                    lines.append(f"### {group.icon} {group.category}")
                    lines.append("")
                    for tip in group.tips:
                        lines.append(f"- {tip}")
                    lines.append("")
            else:
                for tip in trip_data.trip_tips:
                    lines.append(f"- {tip}")
                lines.append("")

        # 页脚
        lines.append("---")
        lines.append("*智旅云图 · 智能行程规划*")
        lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

        return "\n".join(lines)

    # ==================== PDF 导出 ====================

    def _load_template(self, template_name: str = "trip_report.html") -> str:
        """加载 HTML 模板"""
        template_path = self._template_dir / template_name
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        return self._get_default_template()

    def _get_default_template(self) -> str:
        """获取默认 HTML 模板"""
        return """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>行程规划报告</title>
</head>
<body>
    {{content}}
</body>
</html>"""

    def _render_html(self, trip_data: TripResponse, options: Optional[ExportOptions] = None) -> str:
        """
        渲染 HTML 内容

        Args:
            trip_data: 行程数据
            options: 导出选项

        Returns:
            渲染后的 HTML 字符串
        """
        # 构建 HTML 内容
        html_parts = []

        # 封面
        html_parts.append(self._render_cover(trip_data))

        # 概览
        html_parts.append(self._render_overview(trip_data, options))

        # 每日行程
        for day in trip_data.days:
            html_parts.append(self._render_day(day, options))

        # 行程贴士
        if options and options.include_tips and trip_data.trip_tips:
            if trip_data.trip_tips_grouped:
                html_parts.append(self._render_tips_grouped(trip_data.trip_tips_grouped))
            else:
                html_parts.append(self._render_tips(trip_data.trip_tips))

        # 页脚
        html_parts.append(self._render_footer())

        return "\n".join(html_parts)

    def _render_cover(self, trip_data: TripResponse) -> str:
        """渲染封面"""
        return f"""
<div class="cover">
    <div class="cover-title">智旅云图</div>
    <div class="cover-subtitle">行程规划报告</div>
    <div class="cover-trip-name">{trip_data.trip_name}</div>
    <div class="cover-meta">
        <span>📍 {trip_data.destination}</span>
        <span>📅 {trip_data.start_date} 至 {trip_data.end_date}</span>
        <span>🗓 {trip_data.total_days}天</span>
    </div>
</div>
<div class="page-break"></div>
"""

    def _render_overview(self, trip_data: TripResponse, options: Optional[ExportOptions]) -> str:
        """渲染行程概览"""
        html = '<div class="section">'
        html += '<h2 class="section-title">📋 行程概览</h2>'
        html += '<table class="overview-table">'
        html += f'<tr><td>目的地</td><td>{trip_data.destination}</td></tr>'
        html += f'<tr><td>行程时间</td><td>{trip_data.start_date} 至 {trip_data.end_date}</td></tr>'
        html += f'<tr><td>行程天数</td><td>{trip_data.total_days} 天</td></tr>'

        if options and options.include_budget and trip_data.budget:
            html += f'<tr><td>预算总额</td><td>¥{trip_data.budget.total_budget:.2f}</td></tr>'

        if trip_data.trip_highlights and options and options.include_highlights:
            highlights = "、".join(trip_data.trip_highlights[:5])
            html += f'<tr><td>行程亮点</td><td>{highlights}</td></tr>'

        html += '</table></div>'
        return html

    def _render_day(self, day: ItineraryDay, options: Optional[ExportOptions]) -> str:
        """渲染单日行程"""
        html = f'''
<div class="section day-section">
    <h2 class="section-title">📅 Day {day.day_number} · {day.itinerary_date}'''
        
        if day.weather and options and options.include_weather:
            weather_str = day.weather.weather_type or ""
            if day.weather.temp_high and day.weather.temp_low:
                weather_str += f" {day.weather.temp_low}-{day.weather.temp_high}℃"
            if weather_str:
                html += f' <span class="weather">{weather_str}</span>'

        html += '</h2>'

        if day.day_theme:
            html += f'<div class="day-theme">主题：{day.day_theme}</div>'

        # 行程项目
        for item in day.items:
            html += self._render_item(item)

        # 餐饮安排
        if day.breakfast:
            html += self._render_restaurant("🌅 早餐", day.breakfast)
        if day.lunch:
            html += self._render_restaurant("🍜 午餐", day.lunch)
        if day.dinner:
            html += self._render_restaurant("🍽 晚餐", day.dinner)

        # 费用统计
        if options and options.include_budget:
            html += f'''
<div class="daily-cost">
    <span>当日费用：</span>
    <span class="cost-value">¥{day.daily_cost:.2f}</span>
</div>
'''

        html += '</div>'
        return html

    def _render_item(self, item: ItineraryItem) -> str:
        """渲染单个行程项目"""
        html = f'''
<div class="itinerary-item">
    <div class="item-time">{item.start_time} - {item.end_time}</div>
    <div class="item-content">
        <div class="item-place">📍 {item.place.name}</div>
        <div class="item-activity">{item.activity}</div>
'''

        if item.tips:
            for tip in item.tips[:2]:
                html += f'<div class="item-tip">💡 {tip}</div>'

        image_url = _first_image(item.place.images, item.place.cover_image)
        if image_url:
            safe_url = image_url.replace("&", "&amp;").replace('"', "&quot;")
            html += f'<img class="item-image" src="{safe_url}" alt="{item.place.name}"/>'

        html += '</div></div>'
        return html

    def _render_restaurant(self, meal_type: str, restaurant) -> str:
        """渲染餐厅信息"""
        html = f'''
<div class="meal-section">
    <div class="meal-type">{meal_type}</div>
    <div class="meal-content">
        <div class="meal-name">🍴 {restaurant.name}</div>
        <div class="meal-address">📌 {restaurant.address}</div>
'''
        if hasattr(restaurant, 'cuisine_type'):
            html += f'<div class="meal-cuisine">🍜 {restaurant.cuisine_type}</div>'
        if hasattr(restaurant, 'avg_price'):
            html += f'<div class="meal-price">💰 人均 ¥{restaurant.avg_price:.0f}</div>'

        image_url = _first_image(getattr(restaurant, "images", None))
        if image_url:
            safe_url = image_url.replace("&", "&amp;").replace('"', "&quot;")
            html += f'<img class="meal-image" src="{safe_url}" alt="{restaurant.name}"/>'

        html += '</div></div>'
        return html

    def _render_tips(self, tips: List[str]) -> str:
        """渲染行程贴士"""
        html = '''
<div class="section tips-section">
    <h2 class="section-title">💡 行程贴士</h2>
    <ul class="tips-list">
'''
        for tip in tips:
            html += f'<li>{tip}</li>'

        html += '''
    </ul>
</div>
'''
        return html

    def _render_tips_grouped(self, tips_grouped: List[TripTipCategory]) -> str:
        """渲染结构化分类行程贴士"""
        html = '''
<div class="section tips-section">
    <h2 class="section-title">💡 行程贴士</h2>
'''
        for group in tips_grouped:
            html += f'''
    <div class="tips-category">
        <h3 class="tips-category-title">{group.icon} {group.category}</h3>
        <ul class="tips-list">
'''
            for tip in group.tips:
                html += f'<li>{tip}</li>'
            html += '''
        </ul>
    </div>
'''

        html += '''
</div>
'''
        return html

    def _render_footer(self) -> str:
        """渲染页脚"""
        return '''
<div class="footer">
    <div class="footer-line"></div>
    <div class="footer-text">智旅云图 · 智能行程规划</div>
    <div class="footer-time">Generated at ''' + datetime.now().strftime("%Y-%m-%d %H:%M") + '''</div>
</div>
'''

    async def export_to_pdf(
        self,
        trip_data: TripResponse,
        options: Optional[ExportOptions] = None,
    ) -> bytes:
        """
        导出为 PDF 格式

        Args:
            trip_data: 行程数据
            options: 导出选项

        Returns:
            PDF 文件二进制数据

        Raises:
            ExportError: PDF 渲染依赖（WeasyPrint 与 reportlab 均不可用）未就绪
        """
        # 延迟导入 WeasyPrint：其依赖 GTK/GLib/Pango 等原生库，缺失时
        # 不影响其它功能；本机缺少 GTK 时自动降级到纯 Python 的 reportlab。
        try:
            from weasyprint import HTML, CSS

            html_content = self._render_html(trip_data, options)
            css_content = self._get_stylesheet()
            pdf_bytes = HTML(string=html_content).write_pdf(
                stylesheets=[CSS(string=css_content)]
            )
            return pdf_bytes
        except (ImportError, OSError) as e:
            logger.warning("WeasyPrint/GTK 不可用，降级到 reportlab 渲染 PDF: %s", e)
            return await self._export_to_pdf_reportlab(trip_data, options)

    async def _export_to_pdf_reportlab(
        self,
        trip_data: TripResponse,
        options: Optional[ExportOptions] = None,
    ) -> bytes:
        """
        使用 reportlab 渲染 PDF（纯 Python，不依赖 GTK 原生库）。

        在 Windows 缺少 GTK 时作为 WeasyPrint 的降级方案，
        并内嵌景点 / 餐饮图片（图片下载失败时自动跳过，不影响导出）。
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.lib.utils import ImageReader
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.platypus import (
                Image,
                KeepTogether,
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as e:
            raise ExportError(
                message=f"PDF 渲染依赖未就绪（WeasyPrint 与 reportlab 均不可用）: {e}",
                code="PDF_DEPENDENCY_MISSING",
            ) from e

        opts = options or ExportOptions()
        font_name = "STSong-Light"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))

        def make_style(name: str, **kwargs) -> ParagraphStyle:
            defaults = {"fontName": font_name, "wordWrap": "CJK"}
            defaults.update(kwargs)
            return ParagraphStyle(name, **defaults)

        title_style = make_style("cover-title", fontSize=26, leading=34, alignment=1, textColor=colors.HexColor("#2563eb"))
        subtitle_style = make_style("cover-subtitle", fontSize=14, leading=20, alignment=1, textColor=colors.HexColor("#666666"))
        trip_name_style = make_style("cover-trip-name", fontSize=22, leading=30, alignment=1)
        cover_meta_style = make_style("cover-meta", fontSize=11, leading=18, alignment=1, textColor=colors.HexColor("#666666"))
        section_title_style = make_style("section-title", fontSize=15, leading=22, textColor=colors.HexColor("#2563eb"), spaceBefore=14, spaceAfter=8)
        day_title_style = make_style("day-title", fontSize=13, leading=20, textColor=colors.HexColor("#2563eb"), spaceBefore=10, spaceAfter=4)
        theme_style = make_style("day-theme", fontSize=10.5, leading=16, textColor=colors.HexColor("#666666"), spaceAfter=6)
        item_title_style = make_style("item-title", fontSize=11, leading=16, spaceBefore=8, spaceAfter=2)
        body_style = make_style("body", fontSize=10, leading=15, spaceAfter=2)
        small_style = make_style("small", fontSize=9.5, leading=14, textColor=colors.HexColor("#666666"), spaceAfter=1)
        tip_style = make_style("tip", fontSize=9.5, leading=14, textColor=colors.HexColor("#16a34a"), leftIndent=12, spaceAfter=1)
        meal_title_style = make_style("meal-title", fontSize=11, leading=16, textColor=colors.HexColor("#92400e"), spaceBefore=8, spaceAfter=2)
        cost_style = make_style("cost", fontSize=11, leading=16, alignment=2, textColor=colors.HexColor("#2563eb"), spaceBefore=8)
        tips_category_style = make_style("tips-category", fontSize=11.5, leading=16, textColor=colors.HexColor("#166534"), spaceBefore=8, spaceAfter=3)
        footer_style = make_style("footer", fontSize=9, leading=14, alignment=1, textColor=colors.HexColor("#999999"), spaceAfter=2)

        story: List[Any] = []

        # ---- 封面 ----
        story.append(Spacer(1, 2.6 * cm))
        story.append(Paragraph("智旅云图", title_style))
        story.append(Spacer(1, 0.35 * cm))
        story.append(Paragraph("行程规划报告", subtitle_style))
        story.append(Spacer(1, 2.4 * cm))
        story.append(Paragraph(self._escape_pdf_text(trip_data.trip_name), trip_name_style))
        story.append(Spacer(1, 1.4 * cm))
        story.append(Paragraph(f"目的地：{self._escape_pdf_text(trip_data.destination)}", cover_meta_style))
        story.append(Paragraph(f"日期：{trip_data.start_date} 至 {trip_data.end_date}", cover_meta_style))
        story.append(Paragraph(f"天数：{trip_data.total_days} 天", cover_meta_style))

        cover_url = self._trip_cover_image(trip_data)
        with tempfile.TemporaryDirectory(prefix="zhilv_pdf_") as tmp_dir:
            if cover_url:
                cover_img = self._pdf_image_flowable(cover_url, 12.5 * cm, 7.5 * cm, tmp_dir)
                if cover_img:
                    story.append(Spacer(1, 1 * cm))
                    story.append(cover_img)
            story.append(PageBreak())

            # ---- 概览 ----
            story.append(Paragraph("行程概览", section_title_style))
            rows: List[List[Any]] = [
                ["目的地", self._escape_pdf_text(trip_data.destination)],
                ["行程时间", f"{trip_data.start_date} 至 {trip_data.end_date}"],
                ["行程天数", f"{trip_data.total_days} 天"],
            ]
            if opts.include_budget and trip_data.budget:
                rows.append(["预算总额", f"¥{trip_data.budget.total_budget:.2f}"])
            if opts.include_highlights and trip_data.trip_highlights:
                rows.append(["行程亮点", "、".join(str(h) for h in trip_data.trip_highlights[:5])])
            overview = Table(rows, colWidths=[4.2 * cm, None])
            overview.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.append(overview)
            story.append(Spacer(1, 0.5 * cm))

            # ---- 每日行程 ----
            for day in trip_data.days:
                weather_text = ""
                if opts.include_weather and day.weather:
                    parts = [day.weather.weather_type or ""]
                    if day.weather.temp_low is not None and day.weather.temp_high is not None:
                        parts.append(f"{day.weather.temp_low}-{day.weather.temp_high}℃")
                    weather_text = " ".join(p for p in parts if p)
                day_header = f"Day {day.day_number} · {day.itinerary_date}"
                if weather_text:
                    day_header += f"（{weather_text}）"
                header_block = [Paragraph(day_header, day_title_style)]
                if day.day_theme:
                    header_block.append(Paragraph(f"主题：{self._escape_pdf_text(day.day_theme)}", theme_style))
                story.append(KeepTogether(header_block))

                for item in day.items:
                    block: List[Any] = []
                    place_name = self._escape_pdf_text(item.place.name)
                    block.append(Paragraph(
                        f"{item.start_time} - {item.end_time}　{place_name}",
                        item_title_style,
                    ))
                    if item.activity:
                        block.append(Paragraph(f"活动：{self._escape_pdf_text(item.activity)}", body_style))
                    if item.place.address:
                        block.append(Paragraph(f"地址：{self._escape_pdf_text(item.place.address)}", small_style))
                    for tip in (item.tips or [])[:2]:
                        block.append(Paragraph(f"贴士：{self._escape_pdf_text(tip)}", tip_style))
                    image_url = _first_image(item.place.images, item.place.cover_image)
                    if image_url:
                        image_flowable = self._pdf_image_flowable(image_url, 10.5 * cm, 6.5 * cm, tmp_dir)
                        if image_flowable:
                            block.append(Spacer(1, 0.15 * cm))
                            block.append(image_flowable)
                    story.append(KeepTogether(block))

                # 餐饮
                for meal_type, meal in (("早餐", day.breakfast), ("午餐", day.lunch), ("晚餐", day.dinner)):
                    if meal is None:
                        continue
                    block = []
                    block.append(Paragraph(f"{meal_type}：{self._escape_pdf_text(meal.name)}", meal_title_style))
                    if getattr(meal, "address", None):
                        block.append(Paragraph(f"地址：{self._escape_pdf_text(meal.address)}", small_style))
                    if getattr(meal, "cuisine_type", None):
                        block.append(Paragraph(f"菜系：{self._escape_pdf_text(meal.cuisine_type)}", small_style))
                    if getattr(meal, "avg_price", None):
                        block.append(Paragraph(f"人均：¥{meal.avg_price:.0f}", small_style))
                    image_url = _first_image(getattr(meal, "images", None))
                    if image_url:
                        image_flowable = self._pdf_image_flowable(image_url, 7.5 * cm, 4.5 * cm, tmp_dir)
                        if image_flowable:
                            block.append(Spacer(1, 0.15 * cm))
                            block.append(image_flowable)
                    story.append(KeepTogether(block))

                if opts.include_budget:
                    story.append(Paragraph(f"当日费用：¥{day.daily_cost:.2f}", cost_style))
                story.append(Spacer(1, 0.4 * cm))

            # ---- 行程贴士 ----
            if opts.include_tips and trip_data.trip_tips:
                story.append(Paragraph("行程贴士", section_title_style))
                if trip_data.trip_tips_grouped:
                    for group in trip_data.trip_tips_grouped:
                        story.append(Paragraph(
                            f"{self._escape_pdf_text(group.icon)} {self._escape_pdf_text(group.category)}",
                            tips_category_style,
                        ))
                        for tip in group.tips:
                            story.append(Paragraph(f"· {self._escape_pdf_text(tip)}", tip_style))
                else:
                    for tip in trip_data.trip_tips:
                        story.append(Paragraph(f"· {self._escape_pdf_text(tip)}", tip_style))

            # ---- 页脚 ----
            story.append(Spacer(1, 1.2 * cm))
            story.append(Paragraph("—— 智旅云图 · 智能行程规划 ——", footer_style))
            story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", footer_style))

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                leftMargin=2 * cm,
                rightMargin=2 * cm,
                topMargin=2 * cm,
                bottomMargin=2 * cm,
                title=f"{trip_data.trip_name} - 智旅云图行程报告",
                author="智旅云图",
            )
            doc.build(
                story,
                onFirstPage=self._reportlab_page_callback,
                onLaterPages=self._reportlab_page_callback,
            )
            return buffer.getvalue()

    @staticmethod
    def _escape_pdf_text(text: Any) -> str:
        """转义 reportlab Paragraph 中的 XML 特殊字符。"""
        return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _trip_cover_image(self, trip_data: TripResponse) -> Optional[str]:
        """挑选行程中首张可用图片作为封面图。"""
        for day in trip_data.days:
            for item in day.items:
                url = _first_image(item.place.images, item.place.cover_image)
                if url:
                    return url
            for meal in (day.breakfast, day.lunch, day.dinner):
                if meal:
                    url = _first_image(getattr(meal, "images", None))
                    if url:
                        return url
        return None

    def _pdf_image_flowable(
        self,
        url: str,
        max_width: float,
        max_height: float,
        tmp_dir: str,
    ) -> Optional[Any]:
        """
        下载图片并构造 reportlab Image flowable。

        图片下载 / 解码失败时记录告警并返回 None，不阻塞 PDF 导出。
        """
        try:
            from reportlab.lib.utils import ImageReader
            from reportlab.platypus import Image

            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(request, timeout=8) as resp:
                raw = resp.read()
            reader = ImageReader(io.BytesIO(raw))
            width, height = reader.getSize()
            if not width or not height:
                return None
            ext = Path(url.lower()).suffix
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                ext = ".img"
            image_path = Path(tmp_dir) / f"img_{uuid.uuid4().hex[:8]}{ext}"
            image_path.write_bytes(raw)
            scale = min(max_width / width, max_height / height, 1.0)
            return Image(str(image_path), width=width * scale, height=height * scale)
        except Exception as e:
            logger.warning("PDF 图片下载失败，已跳过: %s (%s)", url, e)
            return None

    def _reportlab_page_callback(self, canvas, doc) -> None:
        """在每页底部绘制页码。"""
        from reportlab.lib.units import cm

        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillColorRGB(0.6, 0.6, 0.6)
        canvas.drawCentredString(doc.pagesize[0] / 2, 1 * cm, f"- {canvas.getPageNumber()} -")
        canvas.restoreState()

    def _get_stylesheet(self) -> str:
        """获取 CSS 样式表"""
        return """
@page {
    size: A4;
    margin: 2cm;
    @bottom-center {
        content: counter(page);
        font-size: 10pt;
        color: #999;
    }
}

body {
    font-family: "Source Han Sans CN", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #333;
}

.cover {
    text-align: center;
    padding: 100px 0;
    page-break-after: always;
}

.cover-title {
    font-size: 28pt;
    font-weight: bold;
    color: #2563eb;
    margin-bottom: 10px;
}

.cover-subtitle {
    font-size: 14pt;
    color: #666;
    margin-bottom: 50px;
}

.cover-trip-name {
    font-size: 24pt;
    font-weight: bold;
    margin-bottom: 30px;
}

.cover-meta {
    font-size: 12pt;
    color: #666;
}

.cover-meta span {
    margin: 0 15px;
}

.page-break {
    page-break-after: always;
}

.section {
    margin-bottom: 30px;
}

.section-title {
    font-size: 16pt;
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 8px;
    margin-bottom: 15px;
}

.day-section {
    background: #f8fafc;
    padding: 15px;
    border-radius: 8px;
    margin-bottom: 20px;
}

.day-theme {
    color: #666;
    font-size: 10pt;
    margin-bottom: 15px;
}

.weather {
    font-size: 10pt;
    color: #16a34a;
    font-weight: normal;
}

.overview-table {
    width: 100%;
    border-collapse: collapse;
}

.overview-table td {
    padding: 8px 12px;
    border: 1px solid #e5e7eb;
}

.overview-table td:first-child {
    width: 120px;
    background: #f3f4f6;
    font-weight: bold;
}

.itinerary-item {
    display: flex;
    margin-bottom: 12px;
    padding: 10px;
    background: white;
    border-radius: 6px;
}

.item-time {
    width: 100px;
    font-weight: bold;
    color: #2563eb;
    font-size: 10pt;
}

.item-content {
    flex: 1;
}

.item-place {
    font-weight: bold;
    margin-bottom: 4px;
}

.item-activity {
    color: #666;
    font-size: 10pt;
}

.item-tip {
    color: #16a34a;
    font-size: 9pt;
    margin-top: 4px;
}

.item-image {
    display: block;
    max-width: 70%;
    max-height: 220px;
    margin: 8px 0;
    border-radius: 6px;
    object-fit: cover;
}

.meal-section {
    margin: 10px 0;
    padding: 8px;
    background: #fef3c7;
    border-radius: 6px;
}

.meal-image {
    display: block;
    max-width: 60%;
    max-height: 160px;
    margin: 6px 0;
    border-radius: 6px;
    object-fit: cover;
}

.meal-type {
    font-weight: bold;
    color: #92400e;
    margin-bottom: 4px;
}

.meal-content {
    font-size: 10pt;
}

.daily-cost {
    text-align: right;
    padding: 10px;
    background: #dbeafe;
    border-radius: 6px;
    margin-top: 10px;
}

.cost-value {
    font-weight: bold;
    color: #2563eb;
    font-size: 14pt;
}

.tips-section {
    background: #f0fdf4;
    padding: 15px;
    border-radius: 8px;
}

.tips-category {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px dashed #bbf7d0;
}

.tips-category:last-child {
    border-bottom: none;
}

.tips-category-title {
    font-size: 13pt;
    font-weight: bold;
    color: #166534;
    margin-bottom: 8px;
}

.tips-list {
    margin: 0;
    padding-left: 20px;
}

.tips-list li {
    margin-bottom: 8px;
}

.footer {
    text-align: center;
    margin-top: 50px;
    padding-top: 20px;
}

.footer-line {
    border-top: 1px solid #e5e7eb;
    margin-bottom: 15px;
}

.footer-text {
    color: #2563eb;
    font-weight: bold;
}

.footer-time {
    color: #999;
    font-size: 9pt;
    margin-top: 5px;
}
"""

    # ==================== 主导出接口 ====================

    async def export(
        self,
        trip_id: str,
        format: ExportFormat,
        options: Optional[ExportOptions] = None,
    ) -> ExportResponse:
        """
        主导出方法

        Args:
            trip_id: 行程ID
            format: 导出格式
            options: 导出选项

        Returns:
            导出响应
        """
        try:
            # Step 1: 获取行程数据
            trip_dict = storage_service.get_trip(trip_id)
            if not trip_dict:
                raise TripNotFoundError(trip_id)

            # 转换为 TripResponse
            trip_data = TripResponse(**trip_dict["response_data"])

            # Step 2: 生成文件
            file_id = self._generate_file_id()
            file_name = self._generate_file_name(trip_data.trip_name, format)

            if format == ExportFormat.JSON:
                content = await self.export_to_json(trip_data, options)
                file_path = self._get_file_path(file_id, file_name)
                file_path.write_text(content, encoding="utf-8")
                file_size = file_path.stat().st_size
            else:
                pdf_bytes = await self.export_to_pdf(trip_data, options)
                file_path = self._get_file_path(file_id, file_name)
                file_path.write_bytes(pdf_bytes)
                file_size = len(pdf_bytes)

            # Step 3: 注册文件
            now = datetime.now()
            metadata = ExportFileMetadata(
                file_id=file_id,
                file_name=file_name,
                file_path=str(file_path),
                file_size=file_size,
                format=format,
                trip_id=trip_id,
                created_at=now,
                expires_at=now + timedelta(hours=self._expire_hours),
            )
            self._register_file(metadata)

            # Step 4: 更新行程导出记录
            storage_service.update_trip(
                trip_id,
                exported_formats=(trip_dict.get("exported_formats") or []) + [format.value]
            )

            logger.info(f"导出成功: {file_id} -> {file_path}")

            return ExportResponse(
                success=True,
                file_id=file_id,
                file_name=file_name,
                download_url=f"/api/export/{file_id}/download",
                file_size=file_size,
                created_at=now,
            )

        except ExportError:
            raise
        except Exception as e:
            logger.error(f"导出失败: {e}")
            return ExportResponse(
                success=False,
                error=str(e),
            )

    def get_download_info(self, file_id: str) -> Optional[ExportResponse]:
        """
        获取下载信息

        Args:
            file_id: 文件ID

        Returns:
            下载信息或 None
        """
        metadata = self._get_file_metadata(file_id)
        if not metadata:
            return None

        if self._is_file_expired(metadata):
            self.delete_export(file_id)
            return None

        return ExportResponse(
            success=True,
            file_id=metadata.file_id,
            file_name=metadata.file_name,
            download_url=f"/api/export/{metadata.file_id}/download",
            file_size=metadata.file_size,
            created_at=metadata.created_at,
        )

    def get_file_path(self, file_id: str) -> Optional[Path]:
        """
        获取文件路径

        Args:
            file_id: 文件ID

        Returns:
            文件路径或 None
        """
        metadata = self._get_file_metadata(file_id)
        if not metadata:
            return None

        if self._is_file_expired(metadata):
            self.delete_export(file_id)
            return None

        path = Path(metadata.file_path)
        if not path.exists():
            return None

        return path

    def delete_export(self, file_id: str) -> bool:
        """
        删除导出文件

        Args:
            file_id: 文件ID

        Returns:
            是否删除成功
        """
        metadata = self._get_file_metadata(file_id)
        if not metadata:
            return False

        try:
            path = Path(metadata.file_path)
            if path.exists():
                # 删除整个目录
                path.parent.rmdir()
                # 尝试删除父目录
                try:
                    path.parent.parent.rmdir()
                except OSError:
                    pass

            # 从注册表移除
            if file_id in self._file_registry:
                del self._file_registry[file_id]

            logger.info(f"删除导出文件: {file_id}")
            return True

        except Exception as e:
            logger.error(f"删除导出文件失败: {e}")
            return False

    def cleanup_expired(self) -> int:
        """
        清理过期文件

        Returns:
            清理的文件数量
        """
        count = 0
        expired_ids = []

        for file_id, metadata in self._file_registry.items():
            if self._is_file_expired(metadata):
                expired_ids.append(file_id)

        for file_id in expired_ids:
            if self.delete_export(file_id):
                count += 1

        if count > 0:
            logger.info(f"清理了 {count} 个过期导出文件")

        return count

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        获取存储统计信息

        Returns:
            统计信息
        """
        total_files = len(self._file_registry)
        total_size = sum(m.file_size for m in self._file_registry.values())
        expired_count = sum(1 for m in self._file_registry.values() if self._is_file_expired(m))

        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "expired_files": expired_count,
            "storage_dir": str(self._storage_dir),
        }


# 全局导出服务实例
export_service = ExportService()
