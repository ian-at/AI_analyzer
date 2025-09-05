# 智能分析平台 (Intelligent Analysis Platform)

基于AI的多测试类型智能分析平台，支持UnixBench性能测试、单元测试和接口测试结果的智能分析，自动检测异常并提供根因分析。

## 核心功能

### 🎯 多测试类型支持
- **UnixBench (UB)**: 性能基准测试结果分析
- **单元测试 (Unit Test)**: 内核单元测试失败根因分析
- **接口测试 (Interface Test)**: 接口兼容性测试异常检测

### 🤖 AI智能分析
- 支持多模型配置（Claude、GPT、通义千问、Kimi等）
- 自动检测异常并提供根因分析
- 针对不同测试类型的专用分析策略

### 📊 智能处理机制
- **批量处理优化**: 针对大数据集的智能批处理和缓存机制
- **条件分析**: 单元测试100%通过时自动跳过AI分析
- **自动降级**: AI失败时自动回退到启发式算法
- **实时进度跟踪**: 分析过程实时反馈

### 🌐 Web可视化面板
- **多模块切换**: UB测试、单元测试与接口测试的优雅切换
- **交互式图表**: 趋势分析、失败分布、质量热力图
- **详细报告**: 测试用例级别的详细分析结果

### 📡 完整的Webhook支持
- **UB测试**: `/api/v1/webhook/analyze-patch`
- **单元测试**: `/api/v1/webhook/analyze-unit-patch`
- **接口测试**: `/api/v1/webhook/analyze-interface-patch`
- 支持外部系统调用，根据patch_id自动获取并分析数据

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

- **Web界面**: `http://localhost:8000/static/ui/`
  - UB测试分析: `http://localhost:8000/static/ui/index.html#/dashboard`
  - 单元测试分析: `http://localhost:8000/static/ui/index.html#/unit-dashboard`
  - 接口测试分析: `http://localhost:8000/static/ui/index.html#/interface-dashboard`
- **API文档**: `http://localhost:8000/docs`

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

### UB测试分析
```bash
curl -X POST "http://localhost:8000/api/v1/webhook/analyze-patch?patch_id=2365&patch_set=6"
```

### 单元测试分析
```bash
curl -X POST "http://localhost:8000/api/v1/webhook/analyze-unit-patch?patch_id=2299&patch_set=4"
```

### 接口测试分析
```bash
curl -X POST "http://localhost:8000/api/v1/webhook/analyze-interface-patch?patch_id=2444&patch_set=2"
```

### 参数说明
- `patch_id`: 补丁ID（必填）
- `patch_set`: 补丁集（必填）
- `force_refetch`: 是否强制重新获取数据（可选，默认false）
- `force_reanalyze`: 是否强制重新分析（可选，默认true）
- `max_search_days`: 最大搜索天数（可选，不设置则搜索所有日期）

详细文档请参考：
- [API_DOCS.md](./samples/API_DOCS.md) - 完整API文档
- [UNIT_TEST_WEBHOOK.md](./samples/UNIT_TEST_WEBHOOK.md) - 单元测试Webhook详细指南
- [INTERFACE_TEST_WEBHOOK.md](./samples/INTERFACE_TEST_WEBHOOK.md) - 接口测试Webhook详细指南

## 项目结构

```
intelligent-analysis/
├── ia/                           # 核心代码
│   ├── analyzer/                # AI分析模块
│   │   ├── k2_client.py        # AI模型客户端
│   │   └── unit_test_analyzer.py # 单元测试分析器
│   ├── webhook/                 # Webhook接口
│   ├── webapp/                  # Web服务
│   │   ├── server.py           # FastAPI服务器
│   │   └── ui/                 # React前端
│   ├── fetcher/                 # 数据抓取
│   │   ├── crawler.py          # UB数据爬虫
│   │   ├── unit_test_crawler.py # 单元测试数据爬虫
│   │   └── interface_test_crawler.py # 接口测试数据爬虫
│   ├── parser/                  # 数据解析
│   │   ├── parser.py           # UB数据解析
│   │   ├── unit_test_parser.py # 单元测试解析
│   │   └── interface_test_parser.py # 接口测试解析
│   └── reporting/              # 报告生成
├── archive/                     # 数据归档目录
│   ├── ub/                     # UB测试数据
│   ├── unit/                   # 单元测试数据
│   └── interface/              # 接口测试数据
├── samples/                     # 文档和示例
│   ├── API_DOCS.md             # API文档
│   ├── UNIT_TEST_WEBHOOK.md    # 单元测试Webhook指南
│   └── INTERFACE_TEST_WEBHOOK.md # 接口测试Webhook指南
├── models_config.json          # 主配置文件
├── start_server.sh             # 启动脚本
└── analyze.sh                 # 分析脚本
```

## 技术栈

- **后端**: FastAPI + Python 3.8+
- **前端**: React + TypeScript + Ant Design
- **AI集成**: OpenAI兼容API端点
- **数据处理**: Pandas + NumPy
- **异步处理**: ThreadPoolExecutor

## 配置说明

配置文件 `models_config.json` 支持：

### 数据源配置
- `SOURCE_URL`: UB测试数据源URL
- `SOURCE_URL_UNIT`: 单元测试数据源URL
- `SOURCE_URL_INTERFACE`: 接口测试数据源URL
- `ARCHIVE_ROOT`: UB测试本地存储路径
- `ARCHIVE_ROOT_UNIT`: 单元测试本地存储路径
- `ARCHIVE_ROOT_INTERFACE`: 接口测试本地存储路径

### AI模型配置
- 多模型端点配置（Claude、GPT、通义千问、Kimi等）
- API密钥管理
- 批量优化参数

### UI配置
- `ui.show_config_menu`: 控制配置菜单显示/隐藏

示例配置请参考 `models_config.example.json`

## 使用指南

### UB测试分析
1. 访问UB测试面板: `http://localhost:8000/static/ui/index.html#/dashboard`
2. 点击"获取数据"按钮抓取最新的UB测试结果
3. 点击"AI分析"按钮对异常数据进行智能分析
4. 查看详细的性能趋势和异常报告

### 单元测试分析
1. 访问单元测试面板: `http://localhost:8000/static/ui/index.html#/unit-dashboard`
2. 点击"获取数据"按钮抓取最新的单元测试结果
3. 对于有失败测试的patch，点击"分析"按钮进行AI根因分析
4. 查看失败测试用例的详细分析和建议

### 接口测试分析
1. 访问接口测试面板: `http://localhost:8000/static/ui/index.html#/interface-dashboard`
2. 点击"获取数据"按钮抓取最新的接口测试结果
3. 对于有失败测试的patch，点击"分析"按钮进行AI异常分析
4. 查看接口兼容性问题的详细报告和修复建议

### 智能特性
- **条件分析**: 单元测试100%通过时自动跳过AI分析，节省资源
- **降级机制**: AI分析失败时自动使用基于规则的启发式分析
- **实时反馈**: 所有操作都有实时进度显示和状态更新

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



