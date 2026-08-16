"""
智旅云图 - 缓存服务测试

测试缓存服务的各项功能
"""

import pytest
import time
from app.services.cache_service import (
    CacheService,
    CacheStrategy,
    CacheNamespace,
    CacheConfig,
)


class TestCacheService:
    """缓存服务测试类"""

    @pytest.fixture
    def cache(self):
        """创建缓存服务实例"""
        return CacheService(config=CacheConfig(prefix="test"))

    # ==================== 基本操作测试 ====================

    def test_set_and_get(self, cache):
        """测试基本设置和获取"""
        cache.set("key1", "value1", namespace="test")
        result = cache.get("key1", namespace="test")
        assert result == "value1"

    def test_get_default_value(self, cache):
        """测试获取不存在的键时返回默认值"""
        result = cache.get("nonexistent", namespace="test", default="default")
        assert result == "default"

    def test_delete(self, cache):
        """测试删除"""
        cache.set("key1", "value1", namespace="test")
        cache.delete("key1", namespace="test")
        result = cache.get("key1", namespace="test")
        assert result is None

    def test_exists(self, cache):
        """测试存在检查"""
        cache.set("key1", "value1", namespace="test")
        assert cache.exists("key1", namespace="test") is True
        assert cache.exists("nonexistent", namespace="test") is False

    def test_get_ttl(self, cache):
        """测试获取 TTL"""
        cache.set("key1", "value1", namespace="test", strategy=CacheStrategy.SHORT_TERM)
        ttl = cache.get_ttl("key1", namespace="test")
        assert ttl is not None
        assert 0 < ttl <= 300

    # ==================== 命名空间测试 ====================

    def test_namespace_isolation(self, cache):
        """测试命名空间隔离"""
        cache.set("key1", "value1", namespace="ns1")
        cache.set("key1", "value2", namespace="ns2")
        
        assert cache.get("key1", namespace="ns1") == "value1"
        assert cache.get("key1", namespace="ns2") == "value2"

    def test_clear_namespace(self, cache):
        """测试清空命名空间"""
        cache.set("key1", "value1", namespace="test")
        cache.set("key2", "value2", namespace="test")
        cache.set("key3", "value3", namespace="other")
        
        count = cache.clear_namespace("test")
        assert count >= 2
        assert cache.get("key1", namespace="test") is None
        assert cache.get("key3", namespace="other") == "value3"

    def test_clear_all(self, cache):
        """测试清空所有缓存"""
        cache.set("key1", "value1", namespace="ns1")
        cache.set("key2", "value2", namespace="ns2")
        
        count = cache.clear_all()
        assert count >= 2
        assert cache.get("key1", namespace="ns1") is None

    # ==================== 缓存策略测试 ====================

    def test_different_strategies(self, cache):
        """测试不同的缓存策略"""
        cache.set("permanent", "permanent_value", strategy=CacheStrategy.PERMANENT)
        cache.set("short", "short_value", strategy=CacheStrategy.SHORT_TERM)
        cache.set("medium", "medium_value", strategy=CacheStrategy.MEDIUM_TERM)
        cache.set("long", "long_value", strategy=CacheStrategy.LONG_TERM)
        
        assert cache.get("permanent") == "permanent_value"
        assert cache.get("short") == "short_value"
        assert cache.get("medium") == "medium_value"
        assert cache.get("long") == "long_value"

    # ==================== get_or_set 测试 ====================

    def test_get_or_set(self, cache):
        """测试 get_or_set 功能"""
        factory_calls = [0]
        
        def factory():
            factory_calls[0] += 1
            return "computed_value"
        
        # 第一次调用应该执行 factory
        result1 = cache.get_or_set("factory_key", factory, "test")
        assert result1 == "computed_value"
        assert factory_calls[0] == 1
        
        # 第二次调用应该从缓存获取
        result2 = cache.get_or_set("factory_key", factory, "test")
        assert result2 == "computed_value"
        assert factory_calls[0] == 1  # 不应该再次调用 factory

    # ==================== 统计数据测试 ====================

    def test_stats(self, cache):
        """测试缓存统计"""
        cache.set("key1", "value1", namespace="test")
        cache.get("key1", namespace="test")  # 命中
        cache.get("key2", namespace="test")  # 未命中
        
        stats = cache.get_stats()
        assert "level" in stats
        print(stats,'******************************')
        assert "memory" in stats
        if stats["memory"]:
            assert stats["memory"]["hits"] >= 1
            assert stats["memory"]["misses"] >= 1

    # ==================== 复杂数据类型测试 ====================

    def test_complex_data(self, cache):
        """测试复杂数据类型的存储"""
        complex_data = {
            "user": {"name": "张三", "age": 25},
            "scores": [90, 85, 92],
            "nested": {"a": {"b": "c"}},
        }
        
        cache.set("complex", complex_data, namespace="test")
        result = cache.get("complex", namespace="test")
        
        assert result == complex_data
        assert result["user"]["name"] == "张三"
        assert result["scores"] == [90, 85, 92]


# ==================== 独立运行入口 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
