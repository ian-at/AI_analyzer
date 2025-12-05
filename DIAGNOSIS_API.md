# 故障诊断AI平台 API 使用指南

## 概述

故障诊断AI平台允许用户上传故障日志和文件，通过AI模型进行智能分析，获得故障原因和解决方案。

## API端点

### 1. 一站式提交（推荐）

**POST** `/api/v1/diagnosis/submit`

一次性创建诊断任务、上传文件并开始分析。

**请求参数：**
- `device_id` (可选): 设备ID
- `description` (可选): 故障描述
- `files`: 文件列表（multipart/form-data）

**示例：**
```bash
curl -X POST "http://localhost:8000/api/v1/diagnosis/submit" \
  -F "device_id=PC-001" \
  -F "description=系统频繁蓝屏" \
  -F "files=@/path/to/log1.txt" \
  -F "files=@/path/to/log2.txt"
```

**响应：**
```json
{
  "success": true,
  "diagnosis_id": "abc123def456",
  "files_uploaded": 2,
  "result": {
    "summary": {
      "total_issues": 3,
      "severity_counts": {
        "critical": 1,
        "high": 1,
        "medium": 1,
        "low": 0
      }
    },
    "issues": [...]
  }
}
```

### 2. 分步提交

#### 2.1 创建诊断任务

**POST** `/api/v1/diagnosis/create`

**请求参数：**
- `device_id` (可选): 设备ID
- `description` (可选): 故障描述

**响应：**
```json
{
  "success": true,
  "diagnosis_id": "abc123def456",
  "message": "诊断任务创建成功，请上传文件"
}
```

#### 2.2 上传文件

**POST** `/api/v1/diagnosis/{diagnosis_id}/upload`

**请求参数：**
- `files`: 文件列表（multipart/form-data）

**响应：**
```json
{
  "success": true,
  "diagnosis_id": "abc123def456",
  "files": [
    {
      "filename": "log1.txt",
      "size": 1024,
      "file_path": "...",
      "hash": "..."
    }
  ]
}
```

#### 2.3 开始分析

**POST** `/api/v1/diagnosis/{diagnosis_id}/analyze`

**响应：**
```json
{
  "success": true,
  "diagnosis_id": "abc123def456",
  "result": {
    "summary": {...},
    "issues": [...]
  }
}
```

### 3. 查询诊断结果

**GET** `/api/v1/diagnosis/{diagnosis_id}`

**响应：**
```json
{
  "success": true,
  "diagnosis": {
    "diagnosis_id": "abc123def456",
    "device_id": "PC-001",
    "status": "completed",
    "created_at": "2024-01-01T00:00:00Z",
    "completed_at": "2024-01-01T00:01:00Z",
    "analysis_result": {
      "summary": {...},
      "issues": [...]
    }
  }
}
```

### 4. 列出诊断任务

**GET** `/api/v1/diagnosis/`

**查询参数：**
- `device_id` (可选): 按设备ID过滤
- `limit` (可选): 返回数量限制，默认50

**响应：**
```json
{
  "success": true,
  "diagnoses": [
    {
      "diagnosis_id": "abc123def456",
      "device_id": "PC-001",
      "status": "completed",
      "created_at": "2024-01-01T00:00:00Z",
      "file_count": 2
    }
  ],
  "total": 1
}
```

## 分析结果格式

### Summary（汇总）

```json
{
  "total_issues": 3,
  "severity_counts": {
    "critical": 1,
    "high": 1,
    "medium": 1,
    "low": 0
  },
  "analysis_engine": {
    "name": "kimi",
    "version": "1.0"
  },
  "analysis_time": "2024-01-01T00:01:00Z"
}
```

### Issue（问题）

```json
{
  "issue_type": "软件错误",
  "severity": "critical",
  "confidence": 0.9,
  "title": "内核崩溃检测",
  "description": "在日志中发现内核panic错误...",
  "root_causes": [
    {
      "cause": "内存溢出导致系统崩溃",
      "likelihood": 0.85,
      "evidence": "日志显示内存使用率达到99%"
    }
  ],
  "evidence": {
    "error_messages": ["Kernel panic: Out of memory"],
    "log_excerpts": ["..."]
  },
  "suggested_solutions": [
    "检查内存使用情况：free -h",
    "查看系统日志：journalctl -k",
    "检查是否有内存泄漏的进程"
  ],
  "related_files": ["log1.txt"]
}
```

## 状态说明

- `pending`: 已创建，等待上传文件
- `files_uploaded`: 文件已上传，等待分析
- `analyzing`: 正在分析中
- `completed`: 分析完成
- `failed`: 分析失败

## Python示例

```python
import requests

# 一站式提交
url = "http://localhost:8000/api/v1/diagnosis/submit"
files = [
    ('files', open('log1.txt', 'rb')),
    ('files', open('log2.txt', 'rb'))
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
