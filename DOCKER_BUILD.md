# Docker 构建和运行指南

## 构建镜像

```bash
# 在项目根目录执行
docker build -t intelligent-analysis:latest .
```

## 运行容器

### 基本运行（需要配置AI参数）

```bash
docker run -itd \
  --name ia-container \
  -p 8000:8000 \
  -v /path/to/data:/app/archive \
  -e OPENAI_API_KEY=your_api_key \
  -e OPENAI_API_BASE=your_base_url \
  -e OPENAI_MODEL=kimi-k2-0711-preview \
  intelligent-analysis:latest
```

### 高级配置运行

```bash
docker run -itd \
  --name ia-container \
  -p 8000:8000 \
  -v /data/intelligent-analysis/archive:/app/archive \
  -e OPENAI_API_KEY=your_api_key \
  -e OPENAI_API_BASE=https://api.moonshot.cn/v1 \
  -e OPENAI_MODEL=kimi-k2-0711-preview \
  -e OPENAI_VERIFY_SSL=true \
  -e OPENAI_TIMEOUT=60 \
  -e HEURISTIC_HIGH_THRESHOLD=0.8 \
  -e HEURISTIC_MEDIUM_THRESHOLD=0.5 \
  -e SOURCE_URL=http://IP:Port/results/ \
  intelligent-analysis:latest
```

### 使用配置文件运行

```bash
# 如果您有config.json文件，可以挂载到容器中
docker run -itd \
  --name ia-container \
  -p 8000:8000 \
  -v /path/to/data:/app/archive \
  -v /path/to/config.json:/app/config.json \
  intelligent-analysis:latest
```

## 访问服务

服务启动后可通过以下地址访问：
- Web界面: http://localhost:8000
- API文档: http://localhost:8000/docs

## 端口说明

- 容器内部端口: 8000
- 对外映射端口: 8000 (可自定义)

## 数据卷

- `/app/archive`: 数据存储目录，建议挂载外部存储
- `/app/config.json`: 可选，配置文件挂载点

## 环境变量配置

### 必需的环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OPENAI_API_KEY` | AI模型的API密钥 | `sk-xxxxx` |
| `OPENAI_BASE_URL` | AI模型的基础URL | `https://api.moonshot.cn/v1` |

### 可选的环境变量

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `OPENAI_MODEL` | AI模型名称 | `kimi-k2-0711-preview` | `gpt-4` |
| `OPENAI_VERIFY_SSL` | 是否验证SSL证书 | `true` | `false` |
| `OPENAI_TIMEOUT` | 请求超时时间(秒) | `60` | `120` |
| `HEURISTIC_HIGH_THRESHOLD` | 高风险阈值 | `0.8` | `0.9` |
| `HEURISTIC_MEDIUM_THRESHOLD` | 中风险阈值 | `0.5` | `0.6` |
| `IA_ARCHIVE` | 数据存储路径 | `/app/archive` | `/data/archive` |
| `SOURCE_URL` | UB的HTML数据存储路径 | `http://10.42.39.161/results/` | `http://10.10.10.10:8080/results` |

## 健康检查

容器包含健康检查，可通过以下命令查看状态：
```bash
docker ps
docker inspect ia-container
```

## 镜像信息

- 前端构建: node:18-alpine
- 后端运行: python:3.10-slim
- 服务端口: 8000
- 运行用户: root
- 配置方式: 环境变量 + 可选配置文件挂载

## 注意事项

1. **配置优先级**: 环境变量 > 挂载的config.json文件 > 默认配置
2. **必需参数**: `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` 是必需的环境变量
3. **数据持久化**: 确保挂载 `/app/archive` 目录以保存分析数据
4. **网络访问**: 容器需要访问外部AI服务的网络权限
