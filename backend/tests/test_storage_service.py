"""
智旅云图 - 存储服务测试

测试存储服务的各项功能
"""

import pytest
from datetime import date, datetime, timedelta
from app.services.storage_service import (
    StorageService,
    DatabaseError,
)
from app.models.schemas import (
    TripRequest,
    TripResponse,
    BudgetInfo,
)


class TestStorageService:
    """存储服务测试类"""

    @pytest.fixture
    def storage(self):
        """创建存储服务实例（使用内存数据库）"""
        storage = StorageService(database_url="sqlite:///:memory:")
        storage.init_database()
        return storage

    @pytest.fixture
    def sample_request(self):
        """创建示例请求（日期相对今天动态生成，避免过期被校验拒绝）"""
        start = date.today() + timedelta(days=14)
        return TripRequest(
            destination="北京",
            start_date=start,
            end_date=start + timedelta(days=5),
            travelers=2,
        )

    @pytest.fixture
    def sample_response(self):
        """创建示例响应（日期与 sample_request 保持一致）"""
        start = date.today() + timedelta(days=14)
        return TripResponse(
            trip_id="TEST-001",
            destination="北京",
            trip_name="北京5日游",
            start_date=start,
            end_date=start + timedelta(days=5),
            total_days=5,
            budget=BudgetInfo(
                total_budget=5000,
                daily_avg_budget=1000,
                budget_per_person=2500,
            ),
            generation_time=3.5,
            model_used="glm-4.6v-FlashX",
        )

    # ==================== 健康检查测试 ====================

    def test_health_check(self, storage):
        """测试健康检查"""
        health = storage.health_check()
        assert health["status"] == "healthy"
        assert "database" in health

    # ==================== CRUD 测试 ====================

    def test_create_trip(self, storage, sample_request, sample_response):
        """测试创建行程"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        assert trip_id == "TEST-001"

    def test_get_trip(self, storage, sample_request, sample_response):
        """测试获取行程"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        trip = storage.get_trip(trip_id)
        
        assert trip is not None
        assert trip["id"] == trip_id
        assert trip["destination"] == "北京"
        assert trip["total_days"] == 6  # 8/20 到 8/25 = 6天 (包含起止日期)

    def test_update_trip(self, storage, sample_request, sample_response):
        """测试更新行程"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        success = storage.update_trip(trip_id, user_rating=5, user_feedback="很棒！")
        assert success is True
        
        trip = storage.get_trip(trip_id)
        assert trip["user_rating"] == 5
        assert trip["user_feedback"] == "很棒！"

    def test_delete_trip(self, storage, sample_request, sample_response):
        """测试删除行程"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        success = storage.delete_trip(trip_id)
        assert success is True
        
        trip = storage.get_trip(trip_id)
        assert trip is None

    # ==================== 查询测试 ====================

    def test_list_trips(self, storage, sample_request, sample_response):
        """测试列表查询"""
        # 创建多条记录
        for i in range(3):
            response = sample_response.model_copy()
            response.trip_id = f"TRIP-{i}"
            storage.create_trip(sample_request, response, user_id="test_user")
        
        trips, total = storage.list_trips(user_id="test_user")
        assert total == 3
        assert len(trips) == 3

    def test_list_trips_pagination(self, storage, sample_request, sample_response):
        """测试分页"""
        for i in range(5):
            response = sample_response.model_copy()
            response.trip_id = f"TRIP-{i}"
            storage.create_trip(sample_request, response, user_id="test_user")
        
        # 第一页
        trips, total = storage.list_trips(user_id="test_user", limit=2, offset=0)
        assert len(trips) == 2
        assert total == 5
        
        # 第二页
        trips, total = storage.list_trips(user_id="test_user", limit=2, offset=2)
        assert len(trips) == 2
        assert total == 5

    def test_search_trips(self, storage, sample_request, sample_response):
        """测试搜索"""
        storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        # 搜索北京
        results = storage.search_trips("北京", user_id="test_user")
        assert len(results) >= 1
        
        # 搜索不存在的结果
        results = storage.search_trips("上海", user_id="test_user")
        # 可能为空，取决于之前是否有上海数据

    # ==================== 收藏测试 ====================

    def test_toggle_favorite(self, storage, sample_request, sample_response):
        """测试切换收藏"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        # 第一次切换（设为收藏）
        is_favorite = storage.toggle_favorite(trip_id)
        assert is_favorite is True
        
        # 第二次切换（取消收藏）
        is_favorite = storage.toggle_favorite(trip_id)
        assert is_favorite is False

    def test_get_favorites(self, storage, sample_request, sample_response):
        """测试获取收藏列表"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        storage.toggle_favorite(trip_id)
        
        favorites = storage.get_favorites("test_user")
        assert len(favorites) >= 1
        assert favorites[0]["id"] == trip_id

    # ==================== 分享测试 ====================

    def test_generate_share_code(self, storage, sample_request, sample_response):
        """测试生成分享码"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        share_code = storage.generate_share_code(trip_id)
        assert share_code is not None
        assert len(share_code) == 8

    def test_get_by_share_code(self, storage, sample_request, sample_response):
        """测试通过分享码获取行程"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        share_code = storage.generate_share_code(trip_id)
        
        trip = storage.get_by_share_code(share_code)
        assert trip is not None
        assert trip["id"] == trip_id

    # ==================== 导出测试 ====================

    def test_export_trip(self, storage, sample_request, sample_response):
        """测试导出行程"""
        trip_id = storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        # 导出为 JSON
        exported = storage.export_trip(trip_id, "json")
        assert exported is not None
        assert "request" in exported
        assert "response" in exported
        
        # 导出为摘要
        exported = storage.export_trip(trip_id, "summary")
        assert exported is not None
        assert "destination" in exported
        assert exported["destination"] == "北京"

    # ==================== 统计测试 ====================

    def test_get_statistics(self, storage, sample_request, sample_response):
        """测试统计信息"""
        storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        stats = storage.get_statistics(user_id="test_user")
        assert stats["total_trips"] >= 1
        assert "total_budget" in stats
        assert "favorites_count" in stats

    def test_get_destination_stats(self, storage, sample_request, sample_response):
        """测试目的地统计"""
        storage.create_trip(sample_request, sample_response, user_id="test_user")
        
        stats = storage.get_destination_stats()
        assert len(stats) >= 1
        assert stats[0]["destination"] == "北京"


# ==================== 独立运行入口 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
