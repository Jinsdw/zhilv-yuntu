# 智旅云图后端 Services 模块

from .cache_service import (
    CacheService,
    CacheStrategy,
    CacheNamespace,
    cache_service,
)
from .storage_service import (
    StorageService,
    DatabaseError,
    storage_service,
)
from .amap_geo_service import (
    AmapGeoService,
    GeocodeResult,
    RegeoResult,
    CityMatchType,
    amap_geo,
    init_amap_geo_service,
    get_amap_geo_service,
)
from .map_service import (
    MapService,
    RouteStrategy,
    DistanceType,
    POISortType,
    RouteStep,
    RouteSegment,
    DistanceResult,
    DistanceMatrix,
    DistrictInfo,
    POIInfo,
    POISearchResult,
    StaticMapConfig,
    StaticMapResult,
    PlaceMarker,
    DayRoute,
    MapBounds,
    MapData,
    _map_service,
    init_map_service,
    get_map_service,
)

__all__ = [
    # Cache
    "CacheService",
    "CacheStrategy",
    "CacheNamespace",
    "cache_service",
    # Storage
    "StorageService",
    "DatabaseError",
    "storage_service",
    # Amap Geo
    "AmapGeoService",
    "GeocodeResult",
    "RegeoResult",
    "CityMatchType",
    "amap_geo",
    "init_amap_geo_service",
    "get_amap_geo_service",
    # Map Service
    "MapService",
    "RouteStrategy",
    "DistanceType",
    "POISortType",
    "RouteStep",
    "RouteSegment",
    "DistanceResult",
    "DistanceMatrix",
    "DistrictInfo",
    "POIInfo",
    "POISearchResult",
    "StaticMapConfig",
    "StaticMapResult",
    "PlaceMarker",
    "DayRoute",
    "MapBounds",
    "MapData",
    "_map_service",
    "init_map_service",
    "get_map_service",
]
