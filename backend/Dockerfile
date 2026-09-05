# ============================================
# 智旅云图 - 后端 Dockerfile
# ============================================
# 基于 Python 3.11-slim 镜像，体积小巧
# 默认以生产模式启动（无 --reload）；本地开发用 docker-compose.yaml 的 command 覆盖

FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖（含 WeasyPrint PDF 渲染所需原生库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
# 国内服务器直连 PyPI 不稳定，默认走腾讯云镜像；可用 --build-arg PIP_INDEX_URL=... 覆盖
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/chroma_db /app/logs

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令（生产模式，无热重载）
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
