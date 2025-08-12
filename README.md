## Intelligent Analysis（UB 智能分析平台）

本项目已完成前后端解耦：
- 后端：FastAPI + Pydantic + Uvicorn（分层：`domain`/`app`/`infra`/`interfaces`）。只提供标准 JSON API（前缀 `/api/v1`），从 `./archive` 聚合数据，可平滑迁移到 SQLite/DuckDB/ES。
- 前端：React + TypeScript + Vite + Ant Design + ECharts。单页应用（SPA），在浏览器侧渲染聚合视图与交互。

无需数据库，保持“可单机、自包含”的优势；同时通过抽象层设计（`ModelProvider` 等）保留扩展空间。

### 架构一览

- `ia/domain`：Pydantic 模型与领域实体/协议（如 `RunSummary` 等）。
- `ia/app`：用例层，封装业务逻辑（如 `list_runs_usecase`、统计聚合等）。
- `ia/infra`：I/O 与外部集成（K2 客户端、抓取器、存储读写）。
- `ia/interfaces`：HTTP 辅助、缓存、ETag/Cache-Control 等。
- `ia/webapp/server.py`：FastAPI 入口，路由、CORS、GZip、中间件、静态托管。
- `ia/webapp/ui`：React 前端源码；构建产物输出到 `ia/webapp/static/ui` 由后端托管。

关键能力：
- API 设计：分页、排序、过滤、字段裁剪；ETag/缓存；TTL 内存缓存；任务治理（后台线程池 + `/api/v1/jobs/{id}`）。
- 模型可插拔：`ModelProvider`（K2/启发式可选，后续可扩展 DeepSeek、Llama 等）。
- 性能：GZip、ETag、Cache-Control、列表分页化、静态资源托管。

### 可扩展性

- 模型层：实现新的 `ModelProvider`，配置切换即可接入（如 DeepSeek、vLLM/OpenAI 兼容接口）。
- 数据层：当前从 `./archive` 读取；后续可替换为数据库，只需实现同等用例接口的数据访问器。
- 图表组件：前端以 `ChartCard`/ECharts 为基，新增图表仅需封装数据与配置。

### .gitignore 与仓库清理

- 已更新 `.gitignore` 忽略：`node_modules/`、`ia/webapp/static/ui/` 构建产物、归档内报告与索引、运行日志等。
- 移除“生成 dashboard.html”的旧逻辑：前端已承担聚合视图渲染。CLI 中的相关命令改为提示，不再生成 HTML。

### 环境依赖

- Python 3.10+（若在 Python 3.8 运行，已内置 `eval_type_backport` 支持 `|` 联合类型语法）。
- Node.js 18+（用于前端构建）。

### 后端安装与运行

```bash
python -m pip install -r requirements.txt

# 启动（监听 0.0.0.0 以便其他机器访问）
python -m uvicorn ia.webapp.server:app --host 0.0.0.0 --port 8000 --log-level info
```

可选：将 `IA_ARCHIVE` 指向你的归档目录（默认 `./archive`）。后端会托管该目录到 `/files`，用于直接访问 `report.html`。

### 前端构建与托管

```bash
cd ia/webapp/ui
npm ci || npm install
npm run build
# 产物输出到 ia/webapp/static/ui，由后端 /static/ui/ 托管
```

访问 `http://<服务器IP>:8000/` 即可看到 React 界面。

### 容器化运行

构建镜像：

```bash
docker build -t ia-service:latest .
```

运行（挂载主机归档目录）：

```bash
docker run --rm -p 8000:8000 \
  -v $(pwd)/archive:/data/archive \
  -e IA_ARCHIVE=/data/archive \
  --name ia-service ia-service:latest
```

前端构建产物由镜像内 FastAPI 托管；访问 `http://<主机IP>:8000/`。

### 常用 API（/api/v1）

- `GET /api/v1/runs?start&end&page&page_size&sort_by&order&abnormal_only&engine&patch_id&fields`
- `GET /api/v1/run/{rel}`：单 run 详情（含 `meta/summary/anomalies/ub`）
- `GET /api/v1/dashboard/series?metric=...`
- `GET /api/v1/metrics`：可用指标 key 列表
- `GET /api/v1/anomalies/summary`
- `GET /api/v1/anomalies/timeline`
- `POST /api/v1/actions/reanalyze`：自定义分析（时间范围、引擎、数量、patch 列表）
- `POST /api/v1/runs/{rel}/reanalyze`：单个 run 复分析
- `POST /api/v1/actions/crawl-data?days&force`：从源抓取并解析（不触发分析）
- `GET /api/v1/jobs/{id}`：后台任务状态
- `GET/POST /api/v1/analysis/status`：最近一次分析状态

### 页面使用说明

- Dashboard：
  - 顶部筛选（日期/引擎/异常过滤/排序/分页/列可见性），支持 CSV 导出。
  - 图表区包含：总分趋势、占比、Top-N、时间轴、箱线图、严重度叠加线、热力图；可选择指标。
  - “智能分析”支持选择引擎（auto/k2/heuristic）、时间范围、数量、patch 列表；实时显示任务进度。
  - “获取数据”支持增量抓取与强制重解析。
  - 运行列表的“分析/重新分析”按钮可对单个 run 触发分析。

- Run 详情：
  - 展示 `meta/summary` 与异常清单。
  - 可内嵌显示 `report.html`（或新窗口打开）。

### 其他

- CORS 已默认允许所有来源；生产环境建议收敛白名单。
- 若需容器化与 CI/CD，可按后续计划添加 Dockerfile、健康检查与流水线脚本。

### 开发小贴士

- 本地反复开发前端时，可直接运行 `npm run dev`（默认 5173 端口）做热更新；生产环境从 `ia/webapp/static/ui` 托管构建产物。
- 若需要只读缓存或 ETag 行为调优，可在 `ia/interfaces/http_utils.py` 中调整。
