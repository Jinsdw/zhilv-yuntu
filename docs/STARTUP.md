# 智旅云图 - 启动方式说明

> 本文档覆盖本地开发、Docker 部署、测试与数据入库的完整启动流程。

## 1. 环境要求

- **后端**：Python 3.10+，依赖见 `backend/requirements.txt`
- **前端**：Node.js 18+，npm / yarn
- **可选**：Docker + Docker Compose（容器化部署）
- **外部服务**：高德开放平台 API Key、智谱开放平台 API Key

## 2. 本地开发启动

### 2.1 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少填入：

```env
AMAP_API_KEY=你的高德Key
ZHIPU_API_KEY=你的智谱Key
```

前端地图还需在 `.env` 中配置 `AMAP_JS_API_KEY` 与 `AMAP_SECURITY_JS_CODE`（安全密钥，高德控制台获取）。

### 2.2 后端

```powershell
cd backend
python -m venv venv                     # 首次
.\venv\Scripts\Activate.ps1             # Windows 激活虚拟环境
pip install -r requirements.txt         # 首次
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后：

- 服务地址：`http://localhost:8000`
- Swagger 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

> 缺少 `AMAP_API_KEY` 或 `ZHIPU_API_KEY` 时启动会直接失败并提示。

### 2.3 前端

```powershell
cd frontend
npm install          # 首次
npm run dev
```

访问 `http://localhost:5173`。开发期 vite 自动代理 `/trip` `/weather` `/export` `/health` 到后端 `:8000`。

## 3. Docker 方式

### 3.1 使用 start.ps1（推荐）

```powershell
.\start.ps1             # 启动（backend + redis）
.\start.ps1 -Status     # 查看状态与访问地址
.\start.ps1 -Logs       # 跟踪日志（可加 -Service backend）
.\start.ps1 -Restart    # 重启
.\start.ps1 -Stop       # 停止
.\start.ps1 -Build      # 重新构建镜像
```

首次运行会自动从 `.env.example` 生成 `.env`（若不存在）。

### 3.2 直接 docker compose

```powershell
docker compose up -d backend redis
docker compose logs -f backend
docker compose down
```

## 4. 攻略数据入库（RAG）

向量库为空时，沉淀城市检索会返回空并触发降级。首次或更新攻略后执行：

```powershell
cd backend
python scripts/ingest_guides.py --all          # 全部 6 个沉淀城市
python scripts/ingest_guides.py --city beijing # 单个城市
python scripts/ingest_guides.py --recreate     # 强制重建（清空后重入）
python scripts/ingest_guides.py --stats        # 查看向量库统计
```

攻略文档位置：`backend/data/*_guide.md`（beijing / dali / chengdu / xian / xiamen / sanya）。

## 5. 测试

```powershell
cd backend
pytest tests/ -q                # 全部后端测试（mock 外部服务，不打真实网络）
pytest tests/test_trip_service.py -q   # 指定文件
```

前端检查：

```powershell
cd frontend
npm run type-check   # TypeScript 类型检查
npm run build        # 生产构建（tsc -b + vite build）
```

## 6. 常见问题

| 现象 | 处理 |
|------|------|
| 后端启动报缺少 API Key | 在 `.env` 配置 `AMAP_API_KEY` / `ZHIPU_API_KEY` |
| 地图空白/鉴权失败 | 检查 `AMAP_JS_API_KEY` 与 `AMAP_SECURITY_JS_CODE`，密钥需与页面域名绑定 |
| RAG 检索结果为空 | 运行 `scripts/ingest_guides.py --all` 入库攻略 |
| 天气接口 503 | 检查 `AMAP_API_KEY` 权限与网络 |
| 端口冲突 | 修改 `uvicorn --port` / `VITE_DEV_PORT` / `.env` 的 `BACKEND_PORT` |
| 日志位置 | `backend/logs/app.log`（10MB 轮转、7 天保留） |

---

相关文档：[README.md](../README.md) · [技术架构](ARCHITECTURE.md) · [数据流](DATA_FLOW.md) · [环境变量](ENVIRONMENT.md) · [API 文档](API.md)
