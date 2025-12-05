# 多阶段构建 Dockerfile
# 第一阶段：前端构建
FROM node:18-alpine AS frontend-builder

WORKDIR /app/frontend

# 复制前端源码
COPY ia/webapp/ui/package*.json ./
COPY ia/webapp/ui/ ./

# 安装所有依赖（包括开发依赖）并构建
RUN npm ci && \
    npm run build

# 第二阶段：后端运行环境
FROM python:3.10-slim AS backend

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IA_ARCHIVE=/app/archive

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && \
    rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY ia/ ./ia/
COPY README.md ./

# 从前端构建阶段复制构建产物
COPY --from=frontend-builder /app/static/ui ./ia/webapp/static/ui/

# 设置数据卷
VOLUME ["/app/archive"]

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/analysis/status || exit 1

# 启动命令
CMD ["python3", "-m", "uvicorn", "ia.webapp.server:app", "--host", "0.0.0.0", "--port", "8000"]