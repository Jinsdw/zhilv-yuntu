"""
智旅云图 - 缓存服务实现

支持 Redis 和内存回退的缓存服务:
- 统一缓存抽象层
- 自动降级: Redis -> 内存缓存
- TTL 过期策略
- 命名空间键管理
- 异步支持
"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypeVar, Generic

from ..config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheLevel(Enum):
    """缓存层级"""
    REDIS = "redis"
    MEMORY = "memory"


class CacheStrategy(Enum):
    """缓存策略"""
    # 永久缓存 (除非手动删除)
    PERMANENT = "permanent"
    # 短期缓存 (5分钟)
    SHORT_TERM = "short_term"
    # 中期缓存 (30分钟)
    MEDIUM_TERM = "medium_term"
    # 长期缓存 (24小时)
    LONG_TERM = "long_term"
    # 用户会话级 (会话结束时失效)
    SESSION = "session"


@dataclass
class CacheConfig:
    """缓存配置"""
    # TTL 秒数
    ttl: int = 300
    # 是否启用压缩
    compress: bool = False
    # 最大内存缓存条目数
    max_memory_entries: int = 1000
    # 缓存前缀
    prefix: str = "zhilv"
    
    @classmethod
    def from_strategy(cls, strategy: CacheStrategy) -> "CacheConfig":
        """从缓存策略创建配置"""
        ttl_map = {
            CacheStrategy.PERMANENT: -1,      # -1 表示永不过期
            CacheStrategy.SHORT_TERM: 300,      # 5分钟
            CacheStrategy.MEDIUM_TERM: 1800,   # 30分钟
            CacheStrategy.LONG_TERM: 86400,     # 24小时
            CacheStrategy.SESSION: 3600,        # 1小时
        }
        return cls(ttl=ttl_map.get(strategy, 300))


@dataclass
class CacheEntry(Generic[T]):
    """缓存条目"""
    key: str
    value: T
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    access_count: int = 0
    last_access: Optional[float] = None
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at is None:
            return False  # 永不过期
        return time.time() > self.expires_at
    
    def access(self) -> T:
        """访问缓存并更新统计"""
        self.access_count += 1
        self.last_access = time.time()
        return self.value


class CacheBackend(ABC):
    """缓存后端抽象基类"""
    
    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """获取值"""
        pass
    
    @abstractmethod
    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """设置值"""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """删除键"""
        pass
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        pass
    
    @abstractmethod
    def clear_pattern(self, pattern: str) -> int:
        """删除匹配模式的所有键"""
        pass
    
    @abstractmethod
    def get_ttl(self, key: str) -> Optional[int]:
        """获取剩余 TTL"""
        pass


class RedisCacheBackend(CacheBackend):
    """Redis 缓存后端"""
    
    def __init__(self):
        self._client = None
        self._connect()
    
    def _connect(self):
        """建立 Redis 连接"""
        try:
            import redis
            self._client = redis.Redis(
                host=settings.REDIS_HOST if hasattr(settings, 'REDIS_HOST') else "localhost",
                port=settings.REDIS_PORT if hasattr(settings, 'REDIS_PORT') else 6379,
                db=settings.REDIS_DB if hasattr(settings, 'REDIS_DB') else 0,
                password=settings.REDIS_PASSWORD if hasattr(settings, 'REDIS_PASSWORD') else None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            self._client.ping()
            logger.info("Redis 连接成功")
        except Exception as e:
            logger.warning(f"Redis 连接失败，将使用内存缓存: {e}")
            self._client = None
    
    @property
    def is_available(self) -> bool:
        """检查 Redis 是否可用"""
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False
    
    def get(self, key: str) -> Optional[str]:
        if not self.is_available:
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.error(f"Redis GET 失败: {e}")
            return None
    
    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        if not self.is_available:
            return False
        try:
            if ttl and ttl > 0:
                self._client.setex(key, ttl, value)
            else:
                self._client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Redis SET 失败: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        if not self.is_available:
            return False
        try:
            self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis DELETE 失败: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        if not self.is_available:
            return False
        try:
            return bool(self._client.exists(key))
        except Exception as e:
            logger.error(f"Redis EXISTS 失败: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        if not self.is_available:
            return 0
        try:
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Redis CLEAR_PATTERN 失败: {e}")
            return 0
    
    def get_ttl(self, key: str) -> Optional[int]:
        if not self.is_available:
            return None
        try:
            ttl = self._client.ttl(key)
            return ttl if ttl >= 0 else None
        except Exception as e:
            logger.error(f"Redis TTL 失败: {e}")
            return None


class MemoryCacheBackend(CacheBackend):
    """内存缓存后端 (LRU 策略)"""
    
    def __init__(self, max_entries: int = 1000):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_entries = max_entries
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }
    
    def get(self, key: str) -> Optional[str]:
        entry = self._cache.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None
        
        if entry.is_expired():
            del self._cache[key]
            self._stats["misses"] += 1
            return None
        
        # LRU: 移到末尾
        self._cache.move_to_end(key)
        self._stats["hits"] += 1
        return entry.value
    
    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        # 如果存在，先删除再添加（保持 LRU 顺序）
        if key in self._cache:
            del self._cache[key]
        
        # LRU 淘汰
        if len(self._cache) >= self._max_entries:
            self._evict_oldest()
        
        expires_at = None
        if ttl and ttl > 0:
            expires_at = time.time() + ttl
        
        entry = CacheEntry(key=key, value=value, expires_at=expires_at)
        self._cache[key] = entry
        return True
    
    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def exists(self, key: str) -> bool:
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            return True
        return False
    
    def clear_pattern(self, pattern: str) -> int:
        """删除匹配模式的键"""
        import fnmatch
        count = 0
        keys_to_delete = [
            k for k in self._cache.keys()
            if fnmatch.fnmatch(k, pattern)
        ]
        for key in keys_to_delete:
            del self._cache[key]
            count += 1
        return count
    
    def get_ttl(self, key: str) -> Optional[int]:
        entry = self._cache.get(key)
        if entry and entry.expires_at:
            remaining = int(entry.expires_at - time.time())
            return max(0, remaining)
        return None
    
    def _evict_oldest(self):
        """淘汰最老的条目"""
        if self._cache:
            self._cache.popitem(last=False)
            self._stats["evictions"] += 1
    
    def get_stats(self) -> dict:
        """获取缓存统计"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        return {
            **self._stats,
            "size": len(self._cache),
            "hit_rate": round(hit_rate, 4),
        }


class CacheService:
    """
    统一缓存服务
    
    特性:
    - 自动降级: Redis -> 内存缓存
    - 命名空间键管理
    - 多种缓存策略
    - 序列化/反序列化
    - 统计监控
    """
    
    # 默认 TTL (秒)
    DEFAULT_TTL = 300
    
    def __init__(self, config: Optional[CacheConfig] = None):
        self._config = config or CacheConfig()
        self._redis_backend = RedisCacheBackend()
        self._memory_backend = MemoryCacheBackend(
            max_entries=self._config.max_memory_entries
        )
        self._current_level = CacheLevel.MEMORY
        self._update_cache_level()
    
    def _update_cache_level(self):
        """更新当前缓存层级"""
        if self._redis_backend.is_available:
            self._current_level = CacheLevel.REDIS
        else:
            self._current_level = CacheLevel.MEMORY
    
    @property
    def backend(self) -> CacheBackend:
        """获取当前使用的后端"""
        self._update_cache_level()
        if self._current_level == CacheLevel.REDIS:
            return self._redis_backend
        return self._memory_backend
    
    def _make_key(self, namespace: str, key: str) -> str:
        """生成带命名空间的键"""
        return f"{self._config.prefix}:{namespace}:{key}"
    
    def _serialize(self, value: Any) -> str:
        """序列化值"""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    
    def _deserialize(self, data: Optional[str]) -> Optional[Any]:
        """反序列化值"""
        if data is None:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    
    def get(
        self,
        key: str,
        namespace: str = "default",
        default: Optional[T] = None,
        strategy: CacheStrategy = CacheStrategy.SHORT_TERM,
    ) -> Optional[T]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            namespace: 命名空间
            default: 默认值
            strategy: 缓存策略 (用于计算 TTL)
            
        Returns:
            缓存值或默认值
        """
        full_key = self._make_key(namespace, key)
        data = self.backend.get(full_key)
        
        if data is not None:
            return self._deserialize(data)
        
        return default
    
    def set(
        self,
        key: str,
        value: Any,
        namespace: str = "default",
        strategy: CacheStrategy = CacheStrategy.SHORT_TERM,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            namespace: 命名空间
            strategy: 缓存策略
            ttl: 显式 TTL (覆盖 strategy)
            
        Returns:
            是否设置成功
        """
        full_key = self._make_key(namespace, key)
        serialized = self._serialize(value)
        
        # 确定 TTL
        if ttl is None:
            config = CacheConfig.from_strategy(strategy)
            ttl = config.ttl
        
        return self.backend.set(full_key, serialized, ttl if ttl > 0 else None)
    
    def delete(self, key: str, namespace: str = "default") -> bool:
        """删除缓存"""
        full_key = self._make_key(namespace, key)
        return self.backend.delete(full_key)
    
    def exists(self, key: str, namespace: str = "default") -> bool:
        """检查缓存是否存在"""
        full_key = self._make_key(namespace, key)
        return self.backend.exists(full_key)
    
    def get_ttl(self, key: str, namespace: str = "default") -> Optional[int]:
        """获取剩余 TTL"""
        full_key = self._make_key(namespace, key)
        return self.backend.get_ttl(full_key)
    
    def clear_namespace(self, namespace: str) -> int:
        """
        清除命名空间下所有缓存
        
        Args:
            namespace: 命名空间
            
        Returns:
            删除的键数量
        """
        pattern = self._make_key(namespace, "*")
        return self.backend.clear_pattern(pattern)
    
    def clear_all(self) -> int:
        """清除所有缓存"""
        return self.backend.clear_pattern(f"{self._config.prefix}:*")
    
    def get_or_set(
        self,
        key: str,
        factory,
        namespace: str = "default",
        strategy: CacheStrategy = CacheStrategy.SHORT_TERM,
    ) -> Any:
        """
        获取缓存或设置
        
        特点: 原子操作，避免缓存击穿
        
        Args:
            key: 缓存键
            factory: 值工厂函数 (当缓存不存在时调用)
            namespace: 命名空间
            strategy: 缓存策略
            
        Returns:
            缓存值或工厂生成的值
        """
        value = self.get(key, namespace)
        if value is not None:
            return value
        
        # 缓存未命中，调用工厂生成值
        value = factory()
        self.set(key, value, namespace, strategy)
        return value
    
    async def get_or_set_async(
        self,
        key: str,
        factory,
        namespace: str = "default",
        strategy: CacheStrategy = CacheStrategy.SHORT_TERM,
    ) -> Any:
        """
        异步获取缓存或设置
        """
        value = self.get(key, namespace)
        if value is not None:
            return value
        
        if callable(factory):
            if hasattr(factory, '__await__'):
                # 异步工厂函数
                value = await factory()
            else:
                value = factory()
        else:
            value = factory
        
        self.set(key, value, namespace, strategy)
        return value
    
    def memoize(
        self,
        namespace: str = "default",
        strategy: CacheStrategy = CacheStrategy.SHORT_TERM,
    ):
        """
        装饰器: 自动缓存函数结果
        
        Usage:
            @cache_service.memoize("llm")
            async def call_llm(prompt: str) -> str:
                return await llm.invoke(prompt)
        """
        def decorator(func):
            import functools
            
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                # 生成缓存键 (基于函数名和参数)
                cache_key = self._make_cache_key(func, args, kwargs)
                value = self.get(cache_key, namespace)
                
                if value is not None:
                    return value
                
                if hasattr(func, '__await__'):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                self.set(cache_key, result, namespace, strategy)
                return result
            
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                cache_key = self._make_cache_key(func, args, kwargs)
                value = self.get(cache_key, namespace)
                
                if value is not None:
                    return value
                
                result = func(*args, **kwargs)
                self.set(cache_key, result, namespace, strategy)
                return result
            
            if hasattr(func, '__await__'):
                return async_wrapper
            return sync_wrapper
        
        return decorator
    
    def _make_cache_key(self, func, args, kwargs) -> str:
        """生成函数缓存键"""
        # 函数标识
        func_id = f"{func.__module__}.{func.__name__}"
        
        # 参数哈希
        args_str = json.dumps(args, sort_keys=True, default=str)
        kwargs_str = json.dumps(kwargs, sort_keys=True, default=str)
        params_hash = hashlib.md5(f"{args_str}{kwargs_str}".encode()).hexdigest()[:12]
        
        return f"{func_id}:{params_hash}"
    
    def get_stats(self) -> dict:
        """获取缓存统计"""
        return {
            "level": self._current_level.value,
            "memory": self._memory_backend.get_stats() if self._current_level == CacheLevel.MEMORY else None,
            "redis_available": self._redis_backend.is_available,
        }
    
    @property
    def is_using_memory_fallback(self) -> bool:
        """是否使用内存回退"""
        return self._current_level == CacheLevel.MEMORY


# 全局缓存服务实例
cache_service = CacheService()


# 预定义的命名空间常量
class CacheNamespace:
    """缓存命名空间常量"""
    # LLM 响应缓存
    LLM = "llm"
    # RAG 检索结果
    RAG = "rag"
    # 城市信息
    CITY = "city"
    # 地图数据
    MAP = "map"
    # POI 候选池
    PLACE = "place"
    # 天气数据
    WEATHER = "weather"
    # 用户会话
    SESSION = "session"
    # 用户历史
    HISTORY = "history"
