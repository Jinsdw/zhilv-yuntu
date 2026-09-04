# 更新日志

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。所有显著变更均记录于此。

## [1.0.0] - 2026-09-04

智旅云图首个可运行版本：多 Agent 协同的智能旅游行程规划助手。

### 新增

#### 第一阶段：项目初始化与环境配置
- 创建 `backend/`、`frontend/` 完整目录结构
- `backend/app/config.py` 全局配置（`.env` 读取、loguru 落盘、启动期 API Key 校验）
- `.env.example` 环境变量模板（前后端共用）
- Docker 环境（`docker-compose.yaml`、`start.ps1`、backend Dockerfile）
- 6 个沉淀城市（北京、大理、成都、西安、厦门、三亚）攻略文档

#### 第二阶段：后端核心数据模型
- `schemas.py`：`TripRequest` / `TripResponse` / `ItineraryDay` / `PlaceInfo` / `WeatherInfo` / `BudgetInfo` 等 Pydantic 模型
- `db_models.py`：`trip_history` 等 SQLAlchemy 表结构与索引
- `init_db.py` 数据库初始化

#### 第三阶段：后端服务层
- `cache_service`：Redis + 内存回退、命名空间、TTL
- `storage_service`：SQLite CRUD、历史分页、统计
- `map_service` / `amap_geo_service`：高德路径规划、距离矩阵、行政区、POI、地理编码、图片提取
- `weather_service`：实时天气 / 预报 / 批量天气（缓存 + 限流 + 重试）
- `export_service`：Markdown / PDF（WeasyPrint + HTML/CSS 模板）

#### 第四阶段：RAG 系统
- `vector_db`：ChromaDB 向量库（256 维），全量 / 增量入库、备份恢复
- `retriever`：Query 预处理、意图识别、查询扩展、向量召回、Cross-encoder Rerank、缓存
- `scripts/ingest_guides.py` 攻略入库工具
- RAG 离线评估用例

#### 第五阶段：Agent 系统
- `rag_tool`：`search_travel_guides` OpenAI 兼容工具
- `trip_planner_agent`：结构化行程生成 + 单日编辑 + 降级模板
- `place_candidate_service`：B 级城市 POI 三池（景点/餐饮/住宿）构建与打分

#### 第六阶段：主编排服务
- `trip_service`：城市归一化 → 分级路由 → Agent 调用 → 地图/天气补全 → 预算校正 → 持久化 → 缓存
- `guide_catalog`：攻略目录管理与沉淀城市白名单（文件系统唯一事实来源）

#### 第七阶段：API 路由层
- `POST /trip/generate`、`POST /trip/edit`、`GET /trip/history`、`DELETE /trip/history/{id}`
- `GET /weather/{city}`、`GET /export/markdown/{id}`、`GET /export/pdf/{id}`
- `GET /`、`GET /health`；CORS、请求日志、全局异常处理器（统一错误码）

#### 第八阶段：前端开发
- Vite + React 18 + TypeScript + Ant Design 5 工程
- 页面：Home / Result / History / NotFound
- 组件：行程时间线、天气、预算、地图（`AmapTripMap`：标记、驾车路线、信息窗体、按天视图）
- `services/api.ts` 统一 axios 封装与错误拦截器
- 高德 JSAPI v2.0 集成（`__AMAP_JS_API_KEY__` / `__AMAP_SECURITY_JS_CODE__` 注入）

#### 第九阶段：测试
- 服务层单元测试：`test_amap_geo_service`（60 项）、`test_map_service`（51 项）等
- API 集成测试：`test_api_integration`（21 项，真实 FastAPI + 临时 SQLite，mock 外部网络）
- 覆盖健康检查、生成→落库→历史→导出→编辑→删除全链路及 400/404/422/500/503 错误路径

### 修复
- 修复 `get_trip_as_history` 对 dict 按 ORM 属性访问导致转换失败（编辑/详情链路失效）
- 修复 `create_trip` 未回填 `trip_id` 到落库 `response_data`（编辑后 trip_id 丢失）
- 修复 `trip_service._enrich_single_day_map` 漏传 `photo_cache` 参数（单日编辑 TypeError）
- 修复前端构建阻塞：axios 类型解包收口、未使用导入清理

### 文档
- `README.md` 项目说明
- `docs/ARCHITECTURE.md` 技术架构、`docs/DATA_FLOW.md` 数据流、`docs/ENVIRONMENT.md` 环境变量、`docs/STARTUP.md` 启动方式、`docs/API.md` 接口文档
- 本更新日志

## [Unreleased]

### 规划中
- RAG 检索测试（9.1.4）与 Agent 输出验证测试（9.1.5）
- 功能调试、性能优化（缓存策略、检索、LLM 调用、前端加载）
- 错误处理完善与优雅降级
- 生产部署（环境变量、Dockerfile 优化、服务器准备）
