#!/bin/bash

# 智能分析命令行工具
# 简化的执行命令，自动加载配置

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

# 显示帮助信息
if [ "$#" -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "智能分析平台 - 命令行工具"
    echo ""
    echo "使用方法:"
    echo "  ./analyze.sh crawl [--days N]        # 抓取并分析最近N天的数据(默认3天)"
    echo "  ./analyze.sh reanalyze [--limit N]   # 重新分析最近N个运行(默认5个)"
    echo "  ./analyze.sh missing [--days N]      # 分析缺失的数据(最近N天)"
    echo ""
    echo "示例:"
    echo "  ./analyze.sh crawl --days 7          # 抓取并分析最近7天的数据"
    echo "  ./analyze.sh reanalyze --limit 10    # 重新分析最近10个运行"
    echo "  ./analyze.sh missing --days 3        # 分析最近3天缺失的数据"
    exit 0
fi

# 执行命令
echo "执行命令: $@"
python3 -m ia.cli "$@"
