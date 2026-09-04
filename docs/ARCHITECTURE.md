# 智旅云图 - 技术架构说明

> 本文档说明项目整体架构、模块划分与关键设计决策。

## 1. 总体架构

项目采用经典的前后端分离 + 分层服务架构：

```
┌──────────────────────────────────────────────────────────────┐
│                        前端（React 18）                        │
│  Home.tsx │ Result.tsx │ History.tsx │ AmapTripMap.tsx       │
│  Ant Design 5 │ axios │ 高德 JSAPI v2.0（__AMAP_JS_API_KEY__） │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP（开发期 vite 代理 → :8000）
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                  API 路由层（FastAPI, main.py）                │
│  prefix/tags 统一装配 │ CORS │ 全局异常处理 │ 请求日志          │
│  /trip │ /weather │ /export │ /health                        │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    服务编排层（services/）                      │
│  trip_service（主编排） │ storage │ map │ weather │ export      │
│  amap_geo │ place_candidate │ cache                          │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                Agent 层（agents/, LangGraph）                  │
│  planner_graph（主图 + 单日编辑子图）                            │
│  nodes │ rag_tool │ tools │ state │ llm_factory              │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                     RAG 层（rag/）                             │
│  guide_catalog │ index_config │ retriever │ vector_db        │
│  ChromaDB │ 智谱 Embedding │ Rerank                          │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
             SQLite（trips.db） │ Redis（可选缓存） │ 高德 Web API
```

## 2. 分层职责

### 2.1 API 路由层

- `backend/app/api/main.py`：FastAPI 唯一装配点，负责 lifespan、CORS、请求日志中间件、全局异常处理器与路由注册（prefix/tags 统一在此管理）。
- 路由文件只做 HTTP 入口与参数校验，不承载业务：
  - `routes/trip.py`：行程生成 / 编辑 / 历史 / 删除（同步 `def`，走线程池）。
  - `routes/weather.py`：城市天气查询（`async def`）。
  - `routes/export.py`：Markdown / PDF 导出。
- 领域异常冒泡到全局处理器转 HTTP 状态码：
  - `CityNotSupportedError` → 400 `CITY_NOT_SUPPORTED`
  - `TripNotFoundError` → 404 `TRIP_NOT_FOUND`
  - `TripServiceError` → 500 `TRIP_SERVICE_ERROR`
  - `DatabaseError` → 500 `INTERNAL_ERROR`
  - `HTTPException` → 保留原状态码，统一 `HTTP_ERROR` 结构

### 2.2 服务层

| 模块 | 职责 |
|------|------|
| `trip_service` | 主编排：城市分级 → Agent 调用 → 地图补全 → 天气补全 → 预算校正 → 持久化 |
| `storage_service` | SQLite 连接、行程 CRUD、历史分页查询、用户偏好 |
| `map_service` | 高德路径规划、距离矩阵、行政区、POI 搜索、静态地图 |
| `amap_geo_service` | 地理编码 / 逆地理编码 / POI 图片提取，含重试与限流 |
| `weather_service` | 实时天气、未来预报、批量天气、行程天气（缓存 30 分钟 / 6 小时） |
| `place_candidate_service` | B 级城市 POI 三池（景点/餐饮/住宿）构建与打分排序 |
| `cache_service` | Redis + 内存回退缓存，命名空间管理 |
| `export_service` | Markdown / PDF / JSON 导出（WeasyPrint + HTML/CSS 模板） |

### 2.3 Agent 层（LangGraph）

- **主图** `planner_graph`：
  `START → prefetch_rag → llm_plan ⇄ rag_tools → parse_draft → (repair_json) → validate_repair → build_trip → enrich_budget → END`，任意步骤失败可走 `fallback` 降级模板。
- **单日编辑子图** `edit_day_graph`：以 `build_edit_day_input` 起始，`merge_edit_day` 结束。
- `rag_tool`：把第四阶段 Retriever 封装为 OpenAI 兼容 function calling 工具（`search_travel_guides`）。
- `llm_factory`：通过 `langchain-openai` 的 `ChatOpenAI` 对接智谱 OpenAI 兼容端点。

### 2.4 RAG 层

- `guide_catalog`：扫描 `backend/data/*_guide.md`，构建沉淀城市白名单与城市 → 文件映射；文件系统是唯一事实来源。
- `retriever`：Query 预处理 → 意图识别 → 查询扩展 → 混合检索（向量）→ Cross-encoder Rerank → 缓存。
- `vector_db`：ChromaDB 向量库（256 维），支持全量入库、增量更新、备份恢复与健康监控。

## 3. 多 Agent 协同

| Agent | 职责 | 数据来源 |
|-------|------|---------|
| RAG Agent | 攻略检索（Query Rewrite、向量召回、Rerank） | 本地 Markdown 攻略 |
| Trip Planner Agent | 生成 / 编辑结构化行程（JSON） | RAG 结果或 POI 候选池 + LLM |
| Map Agent | 地理编码、POI 详情、路线、图片 | 高德 Web API |
| Weather Agent | 实时天气 / 预报与出行建议 | 高德天气 API |

城市分级路由：
- **A 级（沉淀城市）**：北京、大理、成都、西安、厦门、三亚 → Agent 走 RAG 工具（`use_tools=True`）。
- **B 级（动态城市）**：构建 POI 三池（景点/餐饮/住宿）→ 全链路 POI 驱动；景点池为空或拉取失败则回退 RAG 路径。
- **C 级（省级等）**：返回 `CITY_NOT_SUPPORTED`。

## 4. 关键设计决策

1. **同步 vs 异步**：`generate_trip` / `edit_trip_day` 为同步阻塞（LangGraph invoke + SQLite），路由声明同步 `def` 让 FastAPI 走线程池；天气/导出走 `async def`。`trip_service._run_async` 在同步上下文桥接异步高德 IO。
2. **失败不阻断主流程**：地图/天气/缓存失败记入 `metadata["enrich_warnings"]`，行程照常返回，避免外部依赖拖垮核心链路。
3. **路径稳定性**：`CHROMA_DB_PATH` / `DATABASE_URL` 相对路径基于项目根解析，避免启动目录不同连错库。
4. **单一装配点**：路由 prefix/tags、CORS、异常处理器、日志全部集中在 `api/main.py`。
5. **配置容错**：`.env` 前后端共用，`Settings(extra="ignore")` 忽略前端专属变量（如 `AMAP_SECURITY_JS_CODE`）。
6. **降级策略**：LLM 不可用时用攻略模板生成兜底行程（`_fallback_plan`）；天气查无数据返回空结构不报错。

## 5. 前端架构

- 页面只做组装：`Home`（规划表单）/ `Result`（行程展示 + 地图 + 天气 + 预算）/ `History`（历史列表）/ `NotFound`。
- 业务组件独立成文件、显式 props：`components/trip/`、`components/map/`、`components/weather/`、`components/budget/`。
- `services/api.ts` 统一 axios 实例 + 拦截器，页面不直接触碰 axios；超时区分生成（5 分钟）/ 编辑（2 分钟）/ 导出（2 分钟）。
- 高德 JSAPI key 经 `vite.config.ts` 的 `define` 注入 `__AMAP_JS_API_KEY__` / `__AMAP_SECURITY_JS_CODE__`。
- 开发期 vite proxy：`/trip` `/weather` `/export` `/health` → `http://localhost:8000`。

## 6. 关键文件索引

| 模块 | 核心文件 |
|------|---------|
| 主编排 | `backend/app/services/trip_service.py` |
| Agent 主图 | `backend/app/agents/planner_graph.py` |
| 行程 Agent | `backend/app/agents/trip_planner_agent.py` |
| RAG 工具 | `backend/app/agents/rag_tool.py` |
| 检索器 | `backend/app/rag/retriever.py` |
| 攻略目录 | `backend/app/rag/guide_catalog.py` |
| API 入口 | `backend/app/api/main.py` |
| 数据模型 | `backend/app/models/schemas.py`、`db_models.py` |
| 前端入口 | `frontend/src/main.tsx`、`App.tsx`、`router/` |

---

相关文档：[README.md](../README.md) · [数据流说明](DATA_FLOW.md) · [环境变量](ENVIRONMENT.md) · [启动方式](STARTUP.md) · [API 文档](API.md)
