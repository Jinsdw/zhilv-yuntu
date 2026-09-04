# 智旅云图 - API 接口文档

> 后端基于 FastAPI，交互式文档见 `http://localhost:8000/docs`（Swagger UI）或 `http://localhost:8000/redoc`。

## 1. 基本信息

- Base URL：`http://localhost:8000`
- 数据格式：`application/json`
- 版本：`1.0.0`
- 前缀：`/trip`、`/weather`、`/export` 由 `api/main.py` 统一装配

## 2. 通用约定

### 2.1 错误响应

领域异常与 HTTPException 统一为结构化错误体：

```json
{
  "error_code": "TRIP_NOT_FOUND",
  "error_message": "行程不存在: TRP-20260904-XXXX"
}
```

| error_code | HTTP 状态 | 场景 |
|-----------|----------|------|
| `CITY_NOT_SUPPORTED` | 400 | C 级目的地（省级等）不支持 |
| `TRIP_NOT_FOUND` | 404 | 行程 / 历史记录不存在 |
| `TRIP_SERVICE_ERROR` | 500 | 编排服务通用错误 |
| `INTERNAL_ERROR` | 500 | 数据库错误或未捕获异常 |
| `HTTP_ERROR` | 原状态码 | 其他 HTTPException（如 503 天气服务不可用） |

参数校验失败（Pydantic 422）返回 FastAPI 默认校验结构。

### 2.2 枚举值

- `budget_level`：`economy` / `standard` / `luxury`
- `travel_style`：`relaxed` / `compact` / `adventure` / `cultural` / `foodie`
- `weather_preference`：`no_preference` / `sunny` / `cool`
- `mode`（天气）：`live` / `forecast` / `both`

---

## 3. 系统接口

### 3.1 GET /

服务元信息。

**响应 200**

```json
{
  "name": "智旅云图",
  "version": "1.0.0",
  "status": "running"
}
```

### 3.2 GET /health

健康检查（附带数据库依赖检查）。

**响应 200**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": 123.45,
  "dependencies": { "database": "connected" }
}
```

数据库断开 → `503` + `status: "unhealthy"`。

---

## 4. 行程接口（/trip）

### 4.1 POST /trip/generate

生成行程（同步阻塞，走线程池；成功已持久化并回填 `trip_id`）。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | string | 否 | 可选用户 ID，用于历史归属 |

**请求体 TripRequest**

```json
{
  "destination": "北京",
  "start_date": "2026-09-05",
  "end_date": "2026-09-07",
  "travelers": 2,
  "budget_level": "standard",
  "travel_style": "cultural",
  "weather_preference": "no_preference",
  "with_kids": false,
  "with_elderly": false,
  "has_disability": false,
  "include_indoor": true,
  "include_outdoor": true,
  "preferred_keywords": ["故宫", "胡同"],
  "excluded_keywords": [],
  "daily_budget": null,
  "max_places_per_day": 5,
  "restaurant_budget_per_meal": 100.0
}
```

| 字段 | 类型 | 默认 | 约束 |
|------|------|------|------|
| `destination` | string | - | 必填，1-50 字符 |
| `start_date` | date | - | 必填，不早于今天 |
| `end_date` | date | - | 必填，不早于 start_date |
| `travelers` | int | 1 | 1-20 |
| `budget_level` | enum | `standard` | - |
| `travel_style` | enum | `relaxed` | - |
| `weather_preference` | enum | `no_preference` | - |
| `with_kids` / `with_elderly` / `has_disability` | bool | false | 特殊需求 |
| `include_indoor` / `include_outdoor` | bool | true | 景点类型过滤 |
| `preferred_keywords` / `excluded_keywords` | string[] | [] | 偏好 / 排除关键词 |
| `daily_budget` | float | null | 每日预算上限（≥0） |
| `max_places_per_day` | int | 5 | 1-10 |
| `restaurant_budget_per_meal` | float | 100.0 | 每餐餐饮预算（≥0） |

**响应 200 TripResponse**（结构摘要）

```json
{
  "trip_id": "TRP-20260904-1A2B3C4D",
  "destination": "北京",
  "trip_name": "北京3日文化之旅",
  "start_date": "2026-09-05",
  "end_date": "2026-09-07",
  "total_days": 3,
  "days": [
    {
      "day_number": 1,
      "itinerary_date": "2026-09-05",
      "day_theme": "皇城文化",
      "weather": { "forecast_date": "2026-09-05", "temp_high": 28, "temp_low": 20, "weather_type": "晴" },
      "items": [
        {
          "start_time": "09:00",
          "end_time": "11:00",
          "place": {
            "place_id": "B000A8N1",
            "name": "故宫博物院",
            "address": "北京市东城区景山前街4号",
            "coordinate": { "latitude": 39.916344, "longitude": 116.397154 },
            "category": "景点"
          },
          "activity": "游览故宫中轴线",
          "ticket_price": 60.0
        }
      ],
      "lunch": { "name": "四季民福烤鸭店", "avg_price": 120.0 },
      "dinner": {},
      "hotel": { "name": "王府井附近舒适酒店", "price": 480.0 },
      "total_places": 5,
      "total_distance": 12.5,
      "total_duration": 480,
      "daily_cost": 720.0,
      "cost_breakdown": { "ticket": 120.0, "food": 300.0, "transport": 60.0 },
      "total_rating": 4.8,
      "daily_tips": ["故宫门票需提前7天预约"]
    }
  ],
  "budget": {
    "total_budget": 2100.0,
    "daily_avg_budget": 700.0,
    "budget_per_person": 1050.0,
    "accommodation_budget": 735.0,
    "food_budget": 630.0,
    "transportation_budget": 210.0,
    "ticket_budget": 420.0,
    "shopping_budget": 0.0,
    "other_budget": 105.0
  },
  "overall_rating": 4.7,
  "trip_highlights": ["紫禁城中轴深度游", "胡同美食探店"],
  "trip_tips": ["提前预约热门景点"],
  "trip_tips_grouped": [
    { "category": "出行准备", "icon": "🎒", "tips": ["故宫须提前7天预约"] }
  ],
  "special_needs_notes": [],
  "weather_suggestions": ["秋高气爽，适合户外"],
  "recommended_foods": ["烤鸭", "炸酱面"],
  "emergency_phone": "110",
  "local_tourism_hotline": "12345",
  "generated_at": "2026-09-04T12:00:00",
  "generation_time": 18.23,
  "model_used": "glm-4.6v-FlashX",
  "version": "1.0",
  "metadata": {}
}
```

**错误**

- 400 `CITY_NOT_SUPPORTED`：目的地为省级等不支持的城市
- 500 `TRIP_SERVICE_ERROR` / `INTERNAL_ERROR`：编排或存储失败

### 4.2 POST /trip/edit

对指定天执行自然语言编辑，返回编辑后的完整行程。

**请求体 TripEditRequest**

```json
{
  "trip_id": "TRP-20260904-1A2B3C4D",
  "day_number": 2,
  "instruction": "第二天增加一个适合傍晚游览的景点",
  "context": "（可选）攻略上下文"
}
```

| 字段 | 类型 | 约束 |
|------|------|------|
| `trip_id` | string | 必填，≥1 字符 |
| `day_number` | int | 必填，≥1（1-based） |
| `instruction` | string | 必填，1-500 字符 |
| `context` | string | 可选 |

**响应 200**：完整 `TripResponse`（同 4.1）

**错误**：404 `TRIP_NOT_FOUND`（行程不存在）

### 4.3 GET /trip/history

行程历史分页摘要（不含每日明细）。

**Query 参数**

| 参数 | 类型 | 默认 | 约束 |
|------|------|------|------|
| `user_id` | string | - | 按用户筛选 |
| `destination` | string | - | 按目的地筛选 |
| `is_favorite` | bool | - | 按收藏状态筛选 |
| `limit` | int | 20 | 1-100 |
| `offset` | int | 0 | ≥0 |
| `order_by` | string | `created_at` | 排序字段 |
| `order_desc` | bool | true | 是否降序 |

**响应 200**

```json
{
  "items": [
    {
      "id": "TRP-20260904-1A2B3C4D",
      "user_id": null,
      "destination": "北京",
      "start_date": "2026-09-05",
      "end_date": "2026-09-07",
      "total_days": 3,
      "total_budget": 2100.0,
      "created_at": "2026-09-04T12:00:00",
      "updated_at": "2026-09-04T12:00:00",
      "is_favorite": false,
      "is_shared": false,
      "share_code": null,
      "access_count": 0,
      "user_rating": null,
      "model_used": "glm-4.6v-FlashX",
      "generation_time": 18.23
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### 4.4 DELETE /trip/history/{trip_id}

删除行程历史。

**响应 204**（无内容）；**错误**：404 `TRIP_NOT_FOUND`

---

## 5. 天气接口（/weather）

### 5.1 GET /weather/{city}

获取城市实时天气与/或未来预报。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `city` | string | 城市名或 adcode（如 `北京` 或 `110000`） |

**Query 参数**

| 参数 | 类型 | 默认 | 约束 |
|------|------|------|------|
| `days` | int | 3 | 1-4（高德上限 4 天） |
| `mode` | enum | `both` | `live` / `forecast` / `both` |

**响应 200 CityWeatherResponse**

```json
{
  "city": "北京",
  "adcode": "110000",
  "live": {
    "forecast_date": "2026-09-04",
    "temp_high": 28,
    "temp_low": 20,
    "weather_type": "晴",
    "humidity": 45,
    "wind_direction": "北风",
    "wind_speed": 12.0,
    "travel_suggestion": "适宜出行"
  },
  "forecast": [
    {
      "forecast_date": "2026-09-05",
      "temp_high": 29,
      "temp_low": 21,
      "weather_type": "多云",
      "dressing_suggestion": "早晚加薄外套"
    }
  ]
}
```

**错误**：503 `HTTP_ERROR`（天气服务不可用）；查无数据返回 200 + 空结构。

---

## 6. 导出接口（/export）

### 6.1 GET /export/markdown/{trip_id}

导出行程为 Markdown 文件。

**响应 200**：`text/markdown; charset=utf-8` 文件流，`Content-Disposition` 携带中文文件名（RFC 5987）。

### 6.2 GET /export/pdf/{trip_id}

导出行程为 PDF 文件。

**响应 200**：`application/pdf` 文件流。

**错误**：404 `TRIP_NOT_FOUND`（行程不存在）

---

## 7. 前端调用约定

前端统一经 `frontend/src/services/api.ts` 调用：

- 2xx 自动解包 `response.data`；204 返回 `undefined`。
- 非 2xx 解析 `error_code` / `error_message` 抛 `ApiError`。
- 超时：生成 5 分钟、编辑 / 导出 2 分钟、其余 30 秒。
- 导出使用 `responseType: 'blob'` 触发浏览器下载。

---

相关文档：[README.md](../README.md) · [技术架构](ARCHITECTURE.md) · [数据流](DATA_FLOW.md) · [环境变量](ENVIRONMENT.md) · [启动方式](STARTUP.md)
