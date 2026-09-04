# 智旅云图 - 环境变量说明

> 项目根目录的 `.env` 由前后端共用（后端 `Settings` 配置 `extra="ignore"`，会忽略前端专属变量）。模板见 `.env.example`。

## 1. 必填项

后端启动时会校验以下 Key，缺失直接抛 `RuntimeError` 拒绝启动：

| 变量 | 说明 | 获取方式 |
|------|------|---------|
| `AMAP_API_KEY` | 高德地图 Web 服务 API Key | 高德开放平台控制台 |
| `ZHIPU_API_KEY` | 智谱大模型 API Key | 智谱开放平台 |

## 2. 项目基础配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROJECT_NAME` | `智旅云图` | 项目名（用于 API 元数据） |
| `DEBUG` | `true` | 调试模式（SQLAlchemy echo 等） |
| `VERSION` | `1.0.0` | 服务版本 |

## 3. 高德地图配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AMAP_API_KEY` | （必填） | Web 服务 API Key（地理编码、POI、天气） |
| `AMAP_JS_API_KEY` | （必填） | JavaScript API Key（前端地图） |
| `AMAP_SECURITY_JS_CODE` | 空 | JSAPI v2.0 安全密钥，需从高德控制台手动填入，否则前端地图鉴权失败 |

## 4. 智谱大模型（LLM / Embedding / Rerank）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIPU_API_KEY` | （必填） | 智谱 API Key |
| `ZHIPU_MODEL` | `glm-4.6v-FlashX` | 行程生成模型 |
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI 兼容端点 |
| `EMBEDDING_MODEL` | `text-embedding-v4` | 向量模型 |
| `EMBEDDING_API_KEY` | 空（自动复用 ZHIPU_API_KEY） | Embedding 专用 Key，可单独覆盖 |
| `EMBEDDING_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | Embedding 端点 |
| `RERANK_MODEL` | `rerank` | Rerank 模型名 |

## 5. 数据与缓存配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHROMA_DB_PATH` | `./data/chroma_db` | ChromaDB 向量库路径；相对路径基于项目根解析 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/trips.db` | SQLAlchemy 连接串 |
| `CACHE_ENABLED` | `false` | 是否启用 Redis 缓存（false = 仅内存回退） |
| `GUIDE_DOCS_PATH` | `./data/guides` | 攻略文档目录 |

## 6. 服务与日志配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_LEVEL` | `INFO` | loguru 落盘级别 |
| `LOG_FILE_PATH` | `backend/logs/app.log` | 日志文件路径（10MB 轮转、7 天保留） |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔白名单；`*` 表示允许所有来源并禁用凭证 |

## 7. 前端环境变量（`frontend/.env.development` / `.env.production`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VITE_APP_TITLE` | `智旅云图` | 页面标题 |
| `VITE_API_BASE_URL` | 空（同源） | API 基础路径；留空由 vite 代理 / 生产反代转发 |
| `VITE_API_PROXY_TARGET` | `http://localhost:8000` | 开发代理目标（后端地址） |
| `VITE_DEV_PORT` | `5173` | 前端开发端口 |

## 8. Docker Compose 相关

`docker-compose.yaml` 额外支持：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BACKEND_PORT` | `8000` | 后端宿主端口映射 |
| `REDIS_PORT` | `6379` | Redis 宿主端口映射 |

## 9. 常见配置组合

```env
# 最小可用（本地开发）
AMAP_API_KEY=你的高德Key
AMAP_JS_API_KEY=你的高德JSKey
ZHIPU_API_KEY=你的智谱Key

# 开启 Redis 缓存
CACHE_ENABLED=true

# 允许跨域访问（生产反代时通常保持默认）
CORS_ORIGINS=http://localhost:5173
```

> 注意：`.env` 中包含真实的 `AMAP_JS_API_KEY` 等敏感信息，请勿提交到版本库（`.gitignore` 已排除）。

---

相关文档：[README.md](../README.md) · [技术架构](ARCHITECTURE.md) · [数据流](DATA_FLOW.md) · [启动方式](STARTUP.md) · [API 文档](API.md)
