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
from .weather_service import (
    WeatherService,
    WeatherLiveData,
    WeatherForecastData,
    weather_service,
    init_weather_service,
    get_weather_service,
    get_live_weather,
    get_forecast,
    batch_get_weather,
    get_trip_weather,
)
try:
    from .export_service import (
        ExportService,
        ExportFormat,
        ExportOptions,
        ExportRequest,
        ExportResponse,
        ExportFileMetadata,
        ExportError,
        TripNotFoundError,
        UnsupportedFormatError,
        FileWriteError,
        export_service,
    )
except ModuleNotFoundError:  # 可选依赖（如 weasyprint）缺失时不影响其它服务导入
    ExportService = None  # type: ignore[misc, assignment]
    ExportFormat = None  # type: ignore[misc, assignment]
    ExportOptions = None  # type: ignore[misc, assignment]
    ExportRequest = None  # type: ignore[misc, assignment]
    ExportResponse = None  # type: ignore[misc, assignment]
    ExportFileMetadata = None  # type: ignore[misc, assignment]
    ExportError = None  # type: ignore[misc, assignment]
    TripNotFoundError = None  # type: ignore[misc, assignment]
    UnsupportedFormatError = None  # type: ignore[misc, assignment]
    FileWriteError = None  # type: ignore[misc, assignment]
    export_service = None  # type: ignore[misc, assignment]

from .place_candidate_service import (
    CandidateEmptyError,
    CandidateError,
    CandidateFetchError,
    CandidatePlace,
    CandidatePool,
    PlaceCandidateConfig,
    PlaceCandidateService,
    QueryPlan,
    SearchMode,
    SearchTask,
    build_query_plan,
    filter_and_rank,
    place_candidate_service,
)
from .trip_service import (
    PRESET_CITIES,
    CityNotSupportedError,
    TripNotFoundError,
    TripService,
    TripServiceError,
    is_preset_city,
    trip_service,
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
    # Weather Service
    "WeatherService",
    "WeatherLiveData",
    "WeatherForecastData",
    "weather_service",
    "init_weather_service",
    "get_weather_service",
    "get_live_weather",
    "get_forecast",
    "batch_get_weather",
    "get_trip_weather",
    # Export Service
    "ExportService",
    "ExportFormat",
    "ExportOptions",
    "ExportRequest",
    "ExportResponse",
    "ExportFileMetadata",
    "ExportError",
    "TripNotFoundError",
    "UnsupportedFormatError",
    "FileWriteError",
    "export_service",
    # Place Candidate
    "CandidateEmptyError",
    "CandidateError",
    "CandidateFetchError",
    "CandidatePlace",
    "CandidatePool",
    "PlaceCandidateConfig",
    "PlaceCandidateService",
    "QueryPlan",
    "SearchMode",
    "SearchTask",
    "build_query_plan",
    "filter_and_rank",
    "place_candidate_service",
    # Trip Service (Phase 6.1)
    "PRESET_CITIES",
    "CityNotSupportedError",
    "TripNotFoundError",
    "TripService",
    "TripServiceError",
    "is_preset_city",
    "trip_service",
]
