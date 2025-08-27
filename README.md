# Intelligent Analysis Platform

An AI-powered platform for analyzing UnixBench test results and detecting performance anomalies.

## Features

- Multi-model AI support (configurable endpoints)
- Batch processing optimization for large datasets
- Real-time progress tracking
- Web dashboard with interactive visualizations
- Automatic fallback to heuristic analysis
- Historical trend analysis

## Configuration

1. Copy the example configuration:
```bash
cp models_config.example.json models_config.json
```

2. Edit `models_config.json` with your API credentials and endpoints

3. Start the server:
```bash
python3 -m uvicorn ia.webapp.server:app --host 0.0.0.0 --port 8000
```

## Usage

Access the web interface at `http://localhost:8000/static/ui/`

## Development

- Frontend: React + TypeScript + Ant Design
- Backend: FastAPI + Python
- AI Integration: OpenAI-compatible API endpoints