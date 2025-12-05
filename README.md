# 故障诊断AI平台 (Fault Diagnosis AI Platform)

基于AI的计算机故障诊断平台，支持上传故障日志和文件，通过AI模型进行智能分析，自动识别故障原因并提供解决方案。

## 核心功能

### 🤖 AI智能诊断
- 支持多模型配置（Claude、GPT、通义千问、Kimi等）
- 自动分析故障日志和文件
- 识别硬件故障、软件错误、配置问题等不同类型
- 提供根因分析和解决方案

### 📁 文件管理
- 支持多文件上传
- 自动文件存储和哈希校验
- 文件内容智能读取和分析

### 🔍 智能分析机制
- **AI分析**: 使用AI模型进行深度分析
- **自动降级**: AI失败时自动回退到基础分析
- **批量处理**: 支持大文件和多文件分析
- **结构化输出**: 问题分类、严重程度、根因分析、解决方案

## 快速开始

### 1. 配置

复制并编辑配置文件：
```bash
cp models_config.example.json models_config.json
# 编辑 models_config.json，配置您的AI模型API密钥
```

### 2. 启动服务

使用启动脚本：
```bash
./start_server.sh
```

或手动启动：
```bash
python3 -m uvicorn ia.webapp.server:app --host 0.0.0.0 --port 8000
```

### 3. 访问服务

- **API文档**: `http://localhost:8000/docs`
- **健康检查**: `http://localhost:8000/health`

## API使用

### 一站式提交（推荐）

```bash
curl -X POST "http://localhost:8000/api/v1/diagnosis/submit" \
  -F "device_id=PC-001" \
  -F "description=系统频繁蓝屏" \
  -F "files=@/path/to/system.log" \
  -F "files=@/path/to/error.log"
```

### 分步提交

1. **创建诊断任务**
```bash
curl -X POST "http://localhost:8000/api/v1/diagnosis/create" \
  -F "device_id=PC-001" \
  -F "description=系统频繁蓝屏"
```

2. **上传文件**
```bash
curl -X POST "http://localhost:8000/api/v1/diagnosis/{diagnosis_id}/upload" \
  -F "files=@/path/to/log.txt"
```

3. **开始分析**
```bash
curl -X POST "http://localhost:8000/api/v1/diagnosis/{diagnosis_id}/analyze"
```

4. **查询结果**
```bash
curl "http://localhost:8000/api/v1/diagnosis/{diagnosis_id}"
```

详细API文档请参考：[DIAGNOSIS_API.md](./DIAGNOSIS_API.md)

## 项目结构

```
intelligent-analysis/
├── ia/                           # 核心代码
│   ├── analyzer/                # AI分析模块
│   │   ├── k2_client.py        # AI模型客户端
│   │   ├── batch_optimizer.py # 批量处理优化器
│   │   └── progress_tracker.py # 进度跟踪器
│   ├── diagnosis/              # 故障诊断模块
│   │   ├── analyzer.py         # 诊断分析器
│   │   ├── file_manager.py     # 文件管理器
│   │   ├── handler.py          # 诊断处理器
│   │   └── api.py              # API接口
│   ├── webapp/                 # Web服务
│   │   └── server.py           # FastAPI服务器
│   ├── domain/                 # 领域模型
│   ├── config.py               # 配置管理
│   └── utils/                  # 工具函数
├── models_config.json          # AI模型配置
├── start_server.sh             # 启动脚本
└── DIAGNOSIS_API.md            # API文档
```

## 技术栈

- **后端**: FastAPI + Python 3.8+
- **AI集成**: OpenAI兼容API端点
- **数据处理**: JSON文件存储
- **异步处理**: ThreadPoolExecutor

## 配置说明

配置文件 `models_config.json` 支持：

### AI模型配置
- 多模型端点配置（Claude、GPT、通义千问、Kimi等）
- API密钥管理
- 批量优化参数

示例配置请参考 `models_config.example.json`

## Python示例

```python
import requests

# 一站式提交故障诊断
url = "http://localhost:8000/api/v1/diagnosis/submit"
files = [
    ('files', open('system.log', 'rb')),
    ('files', open('error.log', 'rb'))
]
data = {
    'device_id': 'PC-001',
    'description': '系统频繁蓝屏'
}

response = requests.post(url, files=files, data=data)
result = response.json()

if result['success']:
    diagnosis_id = result['diagnosis_id']
    print(f"诊断ID: {diagnosis_id}")
    print(f"发现问题: {result['result']['summary']['total_issues']}个")
    
    # 查询详细结果
    detail_url = f"http://localhost:8000/api/v1/diagnosis/{diagnosis_id}"
    detail_response = requests.get(detail_url)
    detail = detail_response.json()
    print(detail)
```

## 注意事项

1. 文件大小限制：单个文件建议不超过10MB
2. 支持的文件类型：文本文件（.txt, .log等）、配置文件等
3. AI分析需要配置模型（models_config.json），否则将使用基础分析
4. 分析时间取决于文件大小和AI模型响应时间，通常需要几秒到几分钟

## 开发指南

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 运行服务：
```bash
python3 -m uvicorn ia.webapp.server:app --host 0.0.0.0 --port 8000
```

3. 代码格式化：
```bash
black ia/
```