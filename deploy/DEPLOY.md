# 智旅云图 - 服务器部署手册（宝塔Linux面板）

> 目标环境：宝塔Linux面板 11.8（腾讯云专享版），系统建议 Ubuntu 22.04 / Debian 12 / 腾讯云 OpenCloudOS。
> 部署形态：后端 + Redis 用 Docker Compose（`docker-compose.prod.yaml`），前端 Vite 构建为静态文件由 Nginx 托管，Nginx 把 `/trip` `/weather` `/export` `/health` 反代到 `127.0.0.1:8000`。

## 部署前准备

- 准备一个域名，A 记录解析到服务器公网 IP，`ping` / `nslookup` 验证生效（没有域名可用 IP 临时访问，但高德 JSAPI 域名白名单需填 IP，且 HTTPS 不便）。
- 腾讯云安全组 + 宝塔「安全」页防火墙都放行 `80`、`443`（面板 `8888` 已开）。
- 安全提醒：`.env.example` 里的高德 Key 是明文模板，正式环境务必换成你自己在高德控制台申请的 Key；`.env` 已被 `.gitignore` 排除，不会提交到 git。

## 第 1 步：服务器装环境（宝塔面板操作）

1. 应用商店安装 **Docker** 应用（新版自带 docker compose v2），终端验证：
   ```bash
   docker -v
   docker compose version
   ```
2. 安装 **Node.js 20 LTS**（宝塔 → 网站 → Node 项目 → 版本管理），验证：
   ```bash
   node -v
   npm -v
   ```
3. 可选加速（国内服务器）：
   ```bash
   npm config set registry https://registry.npmmirror.com
   ```
   Docker 拉镜像 / pip 装依赖慢时，在宝塔 Docker 设置里配腾讯云内网镜像源 `https://mirror.ccs.tencentyun.com`。

## 第 2 步：本地打包并上传

在本地开发机项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\package.ps1
```

产物：`deploy/zhilv-yuntu-<时间戳>.zip`（已排除 `node_modules`、`.git`、`venv`、日志、本地 `.env` 等）。

把 zip 上传到服务器 `/www/wwwroot/zhilv`（宝塔文件管理器或 SFTP），解压后目录结构应为：

```text
/www/wwwroot/zhilv/
  backend/            # 含 Dockerfile、requirements.txt、data/（攻略、chroma_db）
  frontend/           # 前端源码（node_modules 需在服务器安装）
  docker-compose.yaml
  docker-compose.prod.yaml
  deploy/
  .env.example
```

## 第 3 步：配置 .env

```bash
cd /www/wwwroot/zhilv
cp .env.example .env
vi .env
```

至少修改/确认以下项：

```env
DEBUG=false
AMAP_API_KEY=你的高德Web服务Key
AMAP_JS_API_KEY=你的高德JSAPI Key
AMAP_SECURITY_JS_CODE=你的高德JSAPI安全密钥
ZHIPU_API_KEY=你的智谱Key
CORS_ORIGINS=https://你的域名
```

注意：

- `AMAP_JS_API_KEY` / `AMAP_SECURITY_JS_CODE` 会在前端构建时注入，**必须在构建前端之前配好**。
- 到高德控制台 → 应用管理，把 `https://你的域名` 加入 JSAPI 的「域名白名单」。
- `AMAP_API_KEY` 或 `ZHIPU_API_KEY` 缺失时，后端启动会直接失败并给出提示。

## 第 4 步：启动后端（Docker Compose）

```bash
cd /www/wwwroot/zhilv
docker compose -f docker-compose.prod.yaml up -d --build backend redis
```

验证：

```bash
docker compose -f docker-compose.prod.yaml ps
curl http://127.0.0.1:8000/health      # 期望返回 healthy
docker compose -f docker-compose.prod.yaml logs -f backend
```

说明：

- 后端只绑定 `127.0.0.1:8000`，公网无法直连，必须经 Nginx 反代访问。
- 攻略文档与 ChromaDB 通过 `./backend:/app` 挂载宿主机目录，无需额外灌数据。
- 日志落盘到宿主机 `backend/logs/app.log`（容器内 `/app/logs/app.log`）。
- 改代码后 `docker compose -f docker-compose.prod.yaml restart backend` 即可生效；改 `requirements.txt` 后需重新 `up -d --build`。

## 第 5 步：构建前端

```bash
cd /www/wwwroot/zhilv/frontend
npm install
npm run build
```

产物在 `frontend/dist/`，由 Nginx 托管。

## 第 6 步：宝塔建站 + Nginx 反代

1. 宝塔 → 网站 → 添加站点：域名填你的域名，PHP 版本选「纯静态」，根目录填 `/www/wwwroot/zhilv/frontend/dist`。
2. 网站 → 设置 → 配置文件，把 `deploy/zhilv-nginx.conf` 里的 server 块整体粘贴进去（替换自动生成内容），修改 `server_name` 和 `root` 后保存。
3. 点击「重载」让 Nginx 生效。

## 第 7 步：HTTPS（推荐）

1. 宝塔 → 网站 → SSL → Let's Encrypt 免费证书 → 开启「强制 HTTPS」。
2. 如需要跨域保护，确认 `.env` 的 `CORS_ORIGINS` 含 `https://你的域名`，然后 `docker compose -f docker-compose.prod.yaml restart backend`。
3. 高德控制台域名白名单确认已包含 `https://你的域名`。

## 第 8 步：验收

- [ ] `curl https://你的域名/health` 返回 healthy
- [ ] 首页可打开，地图可加载（说明高德白名单生效）
- [ ] 生成一个 A 级城市行程（如大理）：行程、地图点位、天气、预算正常
- [ ] Markdown / PDF 导出正常（PDF 依赖 pango/cairo 已装入镜像；若仍失败会自动降级为 reportlab 渲染）
- [ ] 历史记录、收藏、批量删除正常
- [ ] `docker compose -f docker-compose.prod.yaml logs -f backend` 无报错

## 第 9 步：维护

- 日志：`backend/logs/app.log` 或 `docker compose -f docker-compose.prod.yaml logs -f backend`。
- 重启后端：`docker compose -f docker-compose.prod.yaml restart backend`。
- 更新代码：重新上传解压 → 前端 `npm run build` → 后端 `docker compose -f docker-compose.prod.yaml up -d --build backend redis`。
- 数据备份：宝塔「计划任务」每日/每周打包 `/www/wwwroot/zhilv/backend/data` 到 `/www/backup`。
- 停止服务：`docker compose -f docker-compose.prod.yaml down`。

## 常见问题

| 现象 | 处理 |
|------|------|
| 后端启动失败提示缺少 API Key | 检查 `.env` 的 `AMAP_API_KEY` / `ZHIPU_API_KEY` 并重启容器 |
| `docker pull` / `pip install` 很慢 | 配置腾讯云内网镜像源，见第 1 步 |
| 地图白屏/无法加载 | 高德 JSAPI Key 域名白名单未包含你的域名；`AMAP_SECURITY_JS_CODE` 未配置 |
| 生成行程很慢或 504 | Nginx `proxy_read_timeout` 已放宽到 300s；检查智谱 API Key 配额 |
| `/health` 返回 503 | 数据库初始化失败，看 `backend/logs/app.log` |
| 端口 8000 被占用 | `docker compose -f docker-compose.prod.yaml ps` 确认无旧容器，或 `docker compose ... down` 后重试 |
