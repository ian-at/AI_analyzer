# 智能分析平台 (Intelligent Analysis Platform)

基于AI的UnixBench性能测试结果智能分析平台，自动检测性能异常并提供根因分析。

## 核心功能

- 🤖 **AI智能分析**: 支持多模型配置，自动检测性能异常
- 📊 **批量处理优化**: 针对大数据集的智能批处理和缓存机制
- 📈 **实时进度跟踪**: 分析过程实时反馈
- 🌐 **Web可视化面板**: 交互式数据展示和趋势分析
- 🔄 **自动降级机制**: AI失败时自动回退到启发式算法
- 📡 **Webhook接口**: 支持外部系统调用，根据patch_id获取并分析数据
- 📜 **历史趋势分析**: 基于历史数据的异常检测

## 快速开始

### 1. 配置

复制并编辑配置文件：
```bash
cp models_config.example.json models_config.json
# 编辑 models_config.json，配置您的API密钥
```

### 2. 启动服务

使用简化的启动脚本：
```bash
./start_server.sh
```

或手动启动：
```bash
python3 -m uvicorn ia.webapp.server:app --host 0.0.0.0 --port 8000
```

### 3. 访问界面

- Web界面: `http://localhost:8000/static/ui/`
- API文档: `http://localhost:8000/docs`

## 命令行工具

使用简化的分析脚本：
```bash
# 查看帮助
./analyze.sh --help

# 抓取并分析最近7天的数据
./analyze.sh crawl --days 7

# 重新分析最近10个运行
./analyze.sh reanalyze --limit 10

# 分析缺失的数据
./analyze.sh missing --days 3
```

## Webhook API

根据patch_id和patch_set自动获取并分析数据：

```bash
curl -X POST http://localhost:8000/api/v1/webhook/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "patch_id": "2365",
    "patch_set": "6"
  }'
```

详细API文档请参考 [API_DOCS.md](./API_DOCS.md)

## 项目结构

```
intelligent-analysis/
├── ia/                     # 核心代码
│   ├── analyzer/          # AI分析模块
│   ├── webhook/           # Webhook接口
│   ├── webapp/            # Web服务
│   ├── fetcher/           # 数据抓取
│   ├── parser/            # HTML解析
│   └── reporting/         # 报告生成
├── archive/               # 数据归档目录
├── cache/                 # 缓存目录
├── models_config.json     # 配置文件
├── start_server.sh        # 启动脚本
└── analyze.sh            # 分析脚本
```

## 技术栈

- **后端**: FastAPI + Python 3.8+
- **前端**: React + TypeScript + Ant Design
- **AI集成**: OpenAI兼容API端点
- **数据处理**: Pandas + NumPy
- **异步处理**: ThreadPoolExecutor

## 配置说明

配置文件 `models_config.json` 支持：
- 多模型端点配置
- 批量优化参数
- 缓存策略设置
- API密钥管理

## 开发指南

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 运行测试：
```bash
python -m pytest tests/
```

3. 代码格式化：
```bash
black ia/
```



