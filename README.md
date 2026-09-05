# 智旅云图 (zhilv-yuntu)

> 多 Agent 协同的智能旅游行程规划助手

用户输入**目的地、日期、预算、人数与偏好**后，系统自动生成结构化行程方案，并补充地图点位、路线、天气、预算拆分、景点图片与可导出的旅行文档（Markdown / PDF）。

## 功能特性

| 能力 | 说明 |
|------|------|
| 智能行程生成 | 大模型 + 本地攻略 RAG / 高德 POI 候选池，按天输出结构化行程 |
| 地图可视化 | 高德 JSAPI 展示每日景点标记、驾车路线与信息窗体 |
| 天气补全 | 高德天气 API 实时天气与未来 4 天预报，生成穿搭/出行建议 |
| 预算拆分 | 住宿/餐饮/门票/交通/购物/其他六项自动拆分与二次校正 |
| 智能编辑 | 对已生成行程的某一天进行自然语言编辑 |
| 行程历史 | SQLite 持久化，分页查询、筛选、排序；明信片墙卡片展示（含封面图片） |
| 收藏与批量管理 | 单条/批量收藏、批量删除，支持按收藏状态筛选 |
| 无登录数据隔离 | 浏览器指纹生成稳定设备标识（`X-Device-Id`），历史数据按设备归属隔离，跨设备不可见 |
| 文档导出 | Markdown / PDF 一键导出（含分类行程贴士与图片嵌入，PDF 渲染失败自动降级） |
| 多城市分级 | A 级沉淀城市走 RAG，B 级动态城市走高德 POI，C 级（省级等）返回友好错误 |

## 多 Agent 协同

| Agent | 职责 |
|-------|------|
| RAG Agent | 本地攻略检索：Query Rewrite + 向量召回 + Cross-encoder Rerank |
| Trip Planner Agent | 结构化行程生成 + 单日自然语言编辑 + 降级模板兜底 |
| Map Agent | 高德地理编码、POI、路线规划、距离矩阵与景点图片 |
| Weather Agent | 实时天气与预报查询，结合天气给出旅行提示 |

## 技术栈

- **后端**：FastAPI + LangChain / LangGraph + ChromaDB + Redis（可选）+ SQLite + loguru
- **模型**：智谱大模型（`glm-4.6v-FlashX` 生成、`text-embedding-v4` 向量、`rerank` 重排，OpenAI 兼容接口）
- **地图 / 天气**：高德地图 Web 服务 API + JavaScript API v2.0
- **前端**：React 18 + TypeScript + Ant Design 5 + Vite + Axios；「山海拾光」明信片杂志风主题（主色 `#C0472F`，明暗双模式）
- **部署**：Docker Compose（backend + redis）+ `start.ps1` 管理脚本

## 快速开始

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少填入：

```env
AMAP_API_KEY=你的高德Web服务Key
ZHIPU_API_KEY=你的智谱Key
```

前端地图还需配置 `AMAP_JS_API_KEY` 与 `AMAP_SECURITY_JS_CODE`（JSAPI v2.0 安全密钥，高德控制台获取）。

### 2. 启动后端

```powershell
cd backend
python -m venv venv                     # 首次
.\venv\Scripts\Activate.ps1             # Windows 激活虚拟环境
pip install -r requirements.txt         # 首次
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

> 缺少 `AMAP_API_KEY` 或 `ZHIPU_API_KEY` 时启动会直接失败并提示；Swagger 文档见 `http://localhost:8000/docs`。

### 3. 启动前端

```powershell
cd frontend
npm install   # 首次
npm run dev
```

打开 `http://localhost:5173` 即可使用；开发期 vite 自动代理 `/trip`、`/weather`、`/export`、`/health` 到后端 `:8000`。

> 详细启动方式见 [docs/STARTUP.md](docs/STARTUP.md)，环境变量见 [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)。

## 部署上线（服务器）

完整的宝塔面板部署步骤见 [deploy/DEPLOY.md](deploy/DEPLOY.md)：

- 本地打包：`powershell -ExecutionPolicy Bypass -File .\deploy\package.ps1`（产物在 `deploy/zhilv-yuntu-*.zip`）
- 服务器后端：`docker compose -f docker-compose.prod.yaml up -d --build backend redis`
- 服务器前端：`cd frontend && npm install && npm run build`（产物 `frontend/dist`）
- Nginx 站点配置模板：[deploy/zhilv-nginx.conf](deploy/zhilv-nginx.conf)

## API 概览

需要归属校验的接口通过请求头 `X-Device-Id` 携带设备标识（前端 axios 拦截器自动附加）。

| 方法 | 路径 | 说明 | 设备标识 |
|------|------|------|---------|
| POST | `/trip/generate` | 生成行程（同步阻塞，线程池执行） | 可选 |
| POST | `/trip/edit` | 自然语言编辑单日行程 | 必填 |
| GET | `/trip/history` | 历史列表（分页/目的地/收藏筛选/排序） | 必填 |
| POST | `/trip/history/batch-delete` | 批量删除历史 | 必填 |
| POST | `/trip/history/batch-favorite` | 批量收藏 / 取消收藏 | 必填 |
| GET | `/trip/{trip_id}` | 行程详情（历史回看） | 必填 |
| DELETE | `/trip/history/{trip_id}` | 删除单条历史 | 必填 |
| GET | `/export/markdown/{trip_id}` | 导出 Markdown | 必填 |
| GET | `/export/pdf/{trip_id}` | 导出 PDF | 必填 |
| GET | `/weather/{city}` | 城市实时天气与未来 1-4 天预报 | 可选 |
| GET | `/health` | 健康检查（含数据库依赖状态） | - |

## 目录结构

```text
backend/
  app/
    config.py              # 全局配置（.env 读取、loguru 落盘、启动期 API Key 校验）
    api/main.py            # FastAPI 唯一装配点（lifespan、CORS、请求日志、全局异常处理）
    api/routes/            # trip.py / weather.py / export.py（路由不携带 prefix）
    api/deps.py            # 设备标识依赖（可选读取 + 强制校验）
    agents/                # LangGraph 多 Agent（trip_planner_agent、planner_graph、nodes、rag_tool、tools、state、llm_factory）
    rag/                   # RAG（guide_catalog、index_config、retriever、vector_db）
    services/              # trip_service、storage_service、map_service、weather_service、export_service、cache_service 等
    models/                # schemas.py（Pydantic）、db_models.py、init_db.py
  tests/                   # pytest 测试（22 个文件，mock 外部服务）
  scripts/ingest_guides.py # 攻略文档入库
  data/                    # trips.db、chroma_db、guides、exports、backups
frontend/
  src/
    pages/                 # Home / Result / History / NotFound（页面只做组装）
    components/            # trip/ budget/ map/ weather/ 业务组件
    layouts/ router/ services/ types/ utils/ hooks/ constants/ theme/
  DESIGN.md                # 前端设计蓝图（「山海拾光」主题规范）
docker-compose.yaml        # backend + redis 服务
start.ps1                  # Docker 启动/停止/状态/日志/构建脚本
.env.example               # 环境变量模板（前后端共用）
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
pytest tests/ -q          # 全部后端测试（22 个文件，mock 外部服务，不打真实网络）

cd frontend
npm run type-check        # 前端类型检查
npm run build             # 前端生产构建（tsc -b + vite build）
```

攻略数据入库（向量库为空或更新攻略后执行）：

```powershell
cd backend
python scripts/ingest_guides.py --all          # 全部 6 个沉淀城市
python scripts/ingest_guides.py --city beijing # 单个城市
python scripts/ingest_guides.py --stats        # 查看向量库统计
```

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
| [.cursor/rules/PROGRESS.md](.cursor/rules/PROGRESS.md) | 项目进度追踪（唯一真实来源） |

## 项目进度

- 第一至第九阶段（初始化、数据模型、服务层、RAG、Agent、编排、API、前端、测试与文档）已完成
- 第十阶段（调试与优化）、第十一阶段（部署上线）规划中
- 详见 [REPLICATION_TASKS.md](REPLICATION_TASKS.md) 与 [.cursor/rules/PROGRESS.md](.cursor/rules/PROGRESS.md)

## 许可

本项目仅供学习与内部使用；使用高德地图与智谱大模型服务需自行申请并遵守其服务条款。
