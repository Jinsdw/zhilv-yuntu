# 智旅云图 (zhilv-yuntu)

> 多 Agent 协同的智能旅游行程规划助手

用户输入**目的地、日期、预算、人数与偏好**后，系统自动生成结构化行程方案，并补充地图点位、路线、天气、预算拆分、景点图片与可导出的旅行文档（Markdown / PDF）。

## 核心能力

| 能力 | 说明 |
|------|------|
| 智能行程生成 | 大模型 + 本地攻略 RAG / 高德 POI 候选池，按天输出结构化行程 |
| 地图可视化 | 高德 JSAPI 展示每日景点标记、驾车路线与信息窗体 |
| 天气补全 | 高德天气 API 提供实时天气与未来 4 天预报，并生成穿搭/出行建议 |
| 预算拆分 | 住宿/餐饮/门票/交通/购物/其他六项预算自动拆分与二次校正 |
| 智能编辑 | 对已生成行程的某一天进行自然语言编辑 |
| 行程历史 | SQLite 持久化，支持分页查询、筛选与删除 |
| 文档导出 | Markdown / PDF 一键导出（含分类行程贴士） |
| 多城市分级 | A 级沉淀城市走 RAG，B 级动态城市走高德 POI，C 级（省级等）返回友好错误 |

## 技术栈

- **后端**：FastAPI + LangChain / LangGraph + ChromaDB + Redis（可选）+ SQLite + loguru
- **模型**：智谱大模型（`glm-4.6v-FlashX` 生成、`text-embedding-v4` 向量、`rerank` 重排，OpenAI 兼容接口）
- **地图 / 天气**：高德地图 Web 服务 API + JavaScript API v2.0
- **前端**：React 18 + TypeScript + Ant Design 5 + Vite + Axios
- **部署**：Docker Compose（backend + redis）+ `start.ps1` 管理脚本

## 快速开始

```powershell
# 1. 配置环境变量（复制模板并填入 API Key）
Copy-Item .env.example .env

# 2. 启动后端（需已配置 AMAP_API_KEY + ZHIPU_API_KEY）
cd backend
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

# 3. 启动前端（另开终端）
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173` 即可使用；接口文档见 `http://localhost:8000/docs`。

> 详细启动方式见 [docs/STARTUP.md](docs/STARTUP.md)，环境变量见 [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)。

## 文档导航

| 文档 | 说明 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 技术架构说明（分层、模块、Agent 协同） |
| [docs/DATA_FLOW.md](docs/DATA_FLOW.md) | 数据流图说明（生成/检索/编辑/导出链路） |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | 环境变量说明 |
| [docs/STARTUP.md](docs/STARTUP.md) | 启动方式说明（本地 / Docker / 测试 / 入库） |
| [docs/API.md](docs/API.md) | API 接口文档 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新日志 |
| [REPLICATION_TASKS.md](REPLICATION_TASKS.md) | 复刻任务清单与进度 |

## 目录结构

```
backend/
  app/
    config.py              # 全局配置（.env 读取、loguru 落盘、启动期 API Key 校验）
    api/main.py            # FastAPI 唯一装配点（lifespan、CORS、全局异常处理）
    api/routes/            # trip.py / weather.py / export.py（路由不携带 prefix）
    agents/                # LangGraph 多 Agent（planner_graph、nodes、rag_tool、tools、state、llm_factory）
    rag/                   # RAG（guide_catalog、index_config、retriever、vector_db）
    services/              # trip_service、storage_service、map_service、weather_service、export_service 等
    models/                # schemas.py（Pydantic）、db_models.py、init_db.py
  tests/                   # pytest 测试（mock 外部服务）
  scripts/ingest_guides.py # 攻略文档入库
  data/                    # trips.db、chroma_db、guides、exports、backups
frontend/
  src/
    pages/                 # Home / Result / History / NotFound
    components/            # trip/ budget/ map/ weather/ 业务组件
    layouts/ router/ services/ types/ utils/ hooks/ constants/ theme/
  DESIGN.md                # 前端设计蓝图（Ant Design 5 主题规范）
docker-compose.yaml        # backend + redis 服务
start.ps1                  # Docker 启动/停止/状态/日志/构建脚本
.env.example               # 环境变量模板
```

## 支持的城市

| 等级 | 城市 | 数据来源 |
|------|------|---------|
| A 级（沉淀城市） | 北京、大理、成都、西安、厦门、三亚 | 本地 Markdown 攻略 + RAG |
| B 级（动态城市） | 其他可识别的城市 | 高德 POI 候选池 |
| C 级（不支持） | 省级目的地等 | 返回 `CITY_NOT_SUPPORTED` 错误 |

## 测试与质量

```powershell
cd backend
pytest tests/ -q          # 后端测试（mock 外部服务）

cd frontend
npm run type-check        # 前端类型检查
npm run build             # 前端构建
```

## 许可

本项目仅供学习与内部使用；使用高德地图与智谱大模型服务需自行申请并遵守其服务条款。
