# AGENTS.md — 智旅云图 (zhilv-yuntu)

> 本文件是 Codex 的项目记忆/指导文件，每次任务开始时应优先阅读，避免完整重读项目。
> 详细背景见 `.cursor/rules/PROJECT_CONTEXT.md`，进度见 `.cursor/rules/PROGRESS.md` 与 `REPLICATION_TASKS.md`。

## 项目是什么
- **智旅云图**：多 Agent 协同的智能旅游行程规划助手。
- 用户输入目的地/日期/预算/人数/偏好 → 生成结构化行程，并补充地图点位、天气、预算拆分、景点图片，支持 Markdown/PDF 导出与历史管理。
- 技术栈：FastAPI + React 18 + LangChain/LangGraph + ChromaDB + Redis + 高德地图 API + SQLite。
- LLM/Embedding：智谱大模型（`glm-4.6v-FlashX` 生成、`text-embedding-v4` 向量、`rerank` 重排），OpenAI 兼容接口。

## 目录结构
```
backend/
  app/
    config.py              # 全局配置（.env 读取、loguru 落盘、启动期 API Key 校验）
    api/main.py            # FastAPI 唯一装配点（lifespan、CORS、全局异常处理）
    api/routes/            # trip.py / weather.py / export.py（路由不携带 prefix）
    agents/                # LangGraph 多 Agent（trip_planner_agent、planner_graph、nodes、rag_tool、tools、state、llm_factory）
    rag/                   # RAG（guide_catalog、index_config、retriever、vector_db）
    services/              # trip_service、storage_service、map_service、weather_service、export_service、cache_service、amap_geo_service、place_candidate_service
    models/                # schemas.py（Pydantic）、db_models.py、init_db.py
  tests/                   # pytest 测试（20+ 文件，mock 外部服务）
  scripts/ingest_guides.py # 攻略文档入库
  data/                    # trips.db、chroma_db、guides、exports、backups
frontend/
  src/
    pages/                 # Home / Result / History / NotFound（页面只做组装）
    components/            # trip/ budget/ map/ weather/ 业务组件
    layouts/ router/ services/ types/ utils/ hooks/ constants/ theme/
  DESIGN.md                # 前端设计蓝图（Ant Design 5 主题规范）
  vite.config.ts           # 代理 /trip /weather /export /health → :8000
docker-compose.yaml        # backend + redis 服务
start.ps1                  # Docker 启动/停止/状态/日志/构建脚本
.env.example               # 环境变量模板（前后端共用）
REPLICATION_TASKS.md       # 任务清单（含 [ ] 勾选）
```

## 常用命令
```powershell
# 后端（需要 .env 配置 AMAP_API_KEY + ZHIPU_API_KEY，缺失会启动失败）
cd backend; uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

# 前端（Vite dev，端口 5173，代理到后端 8000）
cd frontend; npm install; npm run dev

# 测试（后端）
cd backend; pytest tests/ -q

# 前端类型检查 / 构建
cd frontend; npm run type-check; npm run build

# RAG 攻略入库
cd backend; python scripts/ingest_guides.py

# Docker 方式
.\start.ps1            # 启动；-Stop / -Restart / -Status / -Logs / -Build
docker compose up -d backend redis
```

## 关键约定与注意事项
- **路由分层**：路由文件只做 HTTP 入口与校验，不承载业务；prefix/tags 统一在 `api/main.py` 装配。领域异常（`CityNotSupportedError`/`TripNotFoundError`/`TripServiceError`/`DatabaseError`）冒泡到全局处理器转 HTTP 状态码。
- **同步 vs 异步**：`trip_service.generate_trip` 是同步阻塞（LangGraph invoke + SQLite），路由用同步 `def` 让 FastAPI 走线程池；weather/export 用 `async def`。
- **前端设计**：Ant Design 5 + 单一强调色 `#0C7C7E`；页面只做组装，业务组件独立成文件、显式 props；路径别名 `@/` → `src/`；高德 JSAPI key 经 `__AMAP_JS_API_KEY__` 注入。
- **配置**：`.env` 前后端共用（`Settings` 配置 `extra="ignore"`）；`CHROMA_DB_PATH`/`DATABASE_URL` 相对路径基于项目根解析，避免启动目录不同导致连错库。
- **城市分级**：A 级（北京、大理、成都、西安、厦门、三亚）走本地攻略 RAG；B 级走高德 POI 候选池；C 级（省级等）返回错误。
- **测试**：`backend/tests/` 用 mock 服务层（不打真实 LLM/高德/SQLite）；修改服务层后运行对应测试文件。
- **进度同步**：完成功能后按项目约定更新 `.cursor/rules/PROGRESS.md` 与 `REPLICATION_TASKS.md` 中的勾选状态。
- **日志**：loguru 统一落盘到 `backend/logs/app.log`（10MB 轮转、7 天保留）。
