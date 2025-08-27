#!/bin/bash

# 智能分析平台启动脚本
# 自动加载配置文件，无需手动设置环境变量

# 设置工作目录
cd "$(dirname "$0")"

# 检查配置文件
if [ ! -f "models_config.json" ]; then
    echo "错误: 配置文件 models_config.json 不存在"
    echo "请复制 models_config.example.json 并配置您的API密钥"
    echo "cp models_config.example.json models_config.json"
    exit 1
fi

# 设置Python路径
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 默认参数
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-4}"

# 启动服务
echo "启动智能分析平台..."
echo "访问地址: http://${HOST}:${PORT}/static/ui/"
echo "API文档: http://${HOST}:${PORT}/docs"
echo "Webhook端点: POST http://${HOST}:${PORT}/api/v1/webhook/analyze"

# 使用uvicorn启动
python3 -m uvicorn ia.webapp.server:app \
    --host ${HOST} \
    --port ${PORT} \
    --workers ${WORKERS} \
    --reload
