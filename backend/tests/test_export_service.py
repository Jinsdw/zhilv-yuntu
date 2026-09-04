"""
智旅云图 - 导出服务测试（3.6.1-3.6.4）

JSON / Markdown 导出与文件管理；PDF 依赖缺失路径。
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import (
    BudgetInfo,
    Coordinate,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    RestaurantInfo,
    TripResponse,
    WeatherInfo,
)
from app.services.export_service import (
    ExportError,
    ExportFormat,
    ExportOptions,
    ExportService,
    TripNotFoundError,
    UnsupportedFormatError,
)


def _sample_trip() -> TripResponse:
    """构造一个最小完整的 TripResponse 用于导出测试"""
    return TripResponse(
        trip_id="TRP-TEST-001",
        destination="北京",
        trip_name="北京测试行程",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        total_days=3,
        days=[
            ItineraryDay(
                day_number=1,
                itinerary_date=date(2026, 9, 1),
                items=[
                    ItineraryItem(
                        start_time="09:00",
                        end_time="11:00",
                        place=PlaceInfo(
                            place_id="p1",
                            name="故宫",
                            address="东城区景山前街4号",
                            coordinate=Coordinate(latitude=39.9163, longitude=116.3972),
                            category="景点",
                            ticket_price=60.0,
                            images=["https://example.com/gugong.jpg"],
                            cover_image="https://example.com/gugong-cover.jpg",
                        ),
                        activity="游览",
                        ticket_price=60.0,
                    )
                ],
                total_places=1,
                lunch=RestaurantInfo(
                    place_id="r1",
                    name="四季民福烤鸭店",
                    coordinate=Coordinate(latitude=39.9150, longitude=116.3960),
                    address="东城区灯市口西街32号",
                    cuisine_type="烤鸭",
                    price_range="100-200元",
                    avg_price=150.0,
                    images=["https://example.com/restaurant.jpg"],
                ),
                weather=WeatherInfo(
                    forecast_date=date(2026, 9, 1),
                    temp_high=30,
                    temp_low=20,
                    temp_avg=25,
                    weather_type="晴",
                ),
                daily_cost=60.0,
            )
        ],
        budget=BudgetInfo(
            total_budget=2000.0,
            daily_avg_budget=666.67,
            budget_per_person=1000.0,
            accommodation_budget=600.0,
            food_budget=300.0,
            transportation_budget=200.0,
            ticket_budget=60.0,
        ),
        trip_highlights=["文化体验"],
        trip_tips=["提前预约"],
    )


@pytest.fixture
def service(tmp_path):
    """导出服务实例（使用临时目录）"""
    return ExportService(storage_dir=str(tmp_path / "exports"), expire_hours=24)


@pytest.fixture
def sample_trip():
    """示例行程数据"""
    return _sample_trip()


@pytest.mark.asyncio
class TestExportToJson:
    """3.6.2 JSON 导出"""

    async def test_core_fields(self, service, sample_trip):
        """核心字段完整"""
        content = await service.export_to_json(sample_trip)
        data = json.loads(content)
        assert data["trip_id"] == "TRP-TEST-001"
        assert data["name"] == "北京测试行程"
        assert data["destination"] == "北京"
        assert data["period"]["days"] == 3
        assert len(data["itinerary"]) == 1
        assert data["itinerary"][0]["items"][0]["place"] == "故宫"
        assert data["budget"]["total"] == 2000.0
        assert data["highlights"] == ["文化体验"]
        assert data["tips"] == ["提前预约"]

    async def test_options_exclude_budget(self, service, sample_trip):
        """排除预算选项"""
        options = ExportOptions(include_budget=False)
        content = await service.export_to_json(sample_trip, options)
        data = json.loads(content)
        assert "budget" not in data

    async def test_options_exclude_highlights_and_tips(self, service, sample_trip):
        """排除亮点与贴士"""
        options = ExportOptions(include_highlights=False, include_tips=False)
        content = await service.export_to_json(sample_trip, options)
        data = json.loads(content)
        assert "highlights" not in data
        assert "tips" not in data

    async def test_ensure_ascii_false(self, service, sample_trip):
        """中文不转义"""
        content = await service.export_to_json(sample_trip)
        assert "故宫" in content


@pytest.mark.asyncio
class TestExportToMarkdown:
    """3.6.2 Markdown 导出"""

    async def test_title_and_meta(self, service, sample_trip):
        """标题与元信息"""
        content = await service.export_to_markdown(sample_trip)
        assert "# 北京测试行程" in content
        assert "**目的地**: 北京" in content
        assert "**天数**: 3 天" in content
        assert "## Day 1" in content
        assert "故宫" in content

    async def test_budget_section(self, service, sample_trip):
        """预算章节"""
        content = await service.export_to_markdown(sample_trip)
        assert "¥2000.00" in content

    async def test_options_exclude_budget(self, service, sample_trip):
        """排除预算"""
        options = ExportOptions(include_budget=False)
        content = await service.export_to_markdown(sample_trip, options)
        assert "预算总额" not in content

    async def test_weather_section(self, service, sample_trip):
        """天气信息"""
        content = await service.export_to_markdown(sample_trip)
        assert "晴" in content

    async def test_place_image(self, service, sample_trip):
        """行程项目包含封面图片"""
        content = await service.export_to_markdown(sample_trip)
        assert "![故宫](<https://example.com/gugong-cover.jpg>)" in content

    async def test_restaurant_image(self, service, sample_trip):
        """餐饮安排包含图片"""
        content = await service.export_to_markdown(sample_trip)
        assert "![四季民福烤鸭店](<https://example.com/restaurant.jpg>)" in content

    async def test_missing_image_skipped(self, service):
        """无图片时正常导出且不出现空图片行"""
        trip = _sample_trip()
        trip.days[0].items[0].place.images = []
        trip.days[0].items[0].place.cover_image = None
        trip.days[0].lunch = None
        content = await service.export_to_markdown(trip)
        assert "](<" not in content
        assert "故宫" in content


@pytest.mark.asyncio
class TestExportToPdf:
    """3.6.4 PDF 导出"""

    async def test_dependency_missing(self, service, sample_trip):
        """WeasyPrint 缺失时抛出 ExportError"""
        with patch.dict(sys.modules, {"weasyprint": None, "weasyprint.html": None, "weasyprint.css": None}):
            with pytest.raises(ExportError) as exc_info:
                await service.export_to_pdf(sample_trip)
            assert "PDF" in str(exc_info.value) or "WeasyPrint" in str(exc_info.value)

    async def test_renders_pdf_bytes(self, service, sample_trip):
        """正常渲染返回 PDF 字节（mock 整个 weasyprint，避免依赖本机 GTK 原生库）"""
        from types import ModuleType

        fake_weasyprint = ModuleType("weasyprint")
        fake_html_class = MagicMock()
        fake_html_class.return_value.write_pdf.return_value = b"%PDF-1.4 mock"
        fake_weasyprint.HTML = fake_html_class
        fake_weasyprint.CSS = MagicMock()

        with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
            pdf = await service.export_to_pdf(sample_trip)
        assert pdf == b"%PDF-1.4 mock"
        fake_html_class.assert_called_once()


class TestFileNaming:
    """文件名生成"""

    def test_sanitizes_special_chars(self, service):
        name = service._generate_file_name('北京<>:"/\\|?*行程', ExportFormat.JSON)
        assert "<" not in name and ">" not in name and ":" not in name
        assert name.endswith(".json")

    def test_pdf_extension(self, service):
        name = service._generate_file_name("北京行程", ExportFormat.PDF)
        assert name.endswith(".pdf")

    def test_file_id_format(self, service):
        file_id = service._generate_file_id()
        assert file_id.startswith("exp_")
        assert len(file_id) > 10

    def test_get_file_path_creates_dirs(self, service):
        path = service._get_file_path("exp_1", "x.json")
        assert path.parent.exists()
        assert path.name == "x.json"


class TestExport:
    """3.6.3 主导出流程"""

    @pytest.mark.asyncio
    async def test_json_export_success(self, service, sample_trip, tmp_path):
        """JSON 主导出成功并注册文件"""
        trip_dict = {"response_data": sample_trip.model_dump(mode="json")}
        with patch("app.services.export_service.storage_service.get_trip", return_value=trip_dict), \
             patch("app.services.export_service.storage_service.update_trip", return_value=True):
            response = await service.export("TRP-TEST-001", ExportFormat.JSON)
        assert response.success is True
        assert response.file_id is not None
        assert response.file_name.endswith(".json")
        assert response.download_url.endswith("/download")
        assert response.file_size > 0

        # 文件真实落盘
        path = service.get_file_path(response.file_id)
        assert path is not None
        assert path.exists()

    @pytest.mark.asyncio
    async def test_trip_not_found(self, service):
        """行程不存在抛 TripNotFoundError"""
        with patch("app.services.export_service.storage_service.get_trip", return_value=None):
            with pytest.raises(TripNotFoundError):
                await service.export("NOPE", ExportFormat.JSON)

    def test_get_download_info_unknown(self, service):
        """未知文件 ID 返回 None"""
        assert service.get_download_info("unknown") is None

    def test_get_file_path_unknown(self, service):
        """未知文件 ID 返回 None"""
        assert service.get_file_path("unknown") is None

    def test_delete_export_unknown(self, service):
        """删除未知文件返回 False"""
        assert service.delete_export("unknown") is False

    def test_get_storage_stats(self, service):
        """存储统计"""
        stats = service.get_storage_stats()
        assert stats["total_files"] == 0
        assert stats["total_size_bytes"] == 0
        assert "storage_dir" in stats


class TestCleanupExpired:
    """过期文件清理"""

    def test_cleanup_expired_removes(self, service, sample_trip):
        """过期文件被清理"""
        from datetime import datetime
        from app.services.export_service import ExportFileMetadata

        expired = ExportFileMetadata(
            file_id="expired-1",
            file_name="x.json",
            file_path=str(Path(service._storage_dir) / "x.json"),
            file_size=10,
            format=ExportFormat.JSON,
            trip_id="t1",
            created_at=datetime.now() - timedelta(hours=48),
            expires_at=datetime.now() - timedelta(hours=24),
        )
        service._register_file(expired)
        count = service.cleanup_expired()
        assert count == 1
        assert service.get_download_info("expired-1") is None





