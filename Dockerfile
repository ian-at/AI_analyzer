# syntax=docker/dockerfile:1
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Copy project
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY ia ./ia
COPY README.md ./README.md

# Env and ports
ENV IA_ARCHIVE=/data/archive
VOLUME ["/data/archive"]
EXPOSE 8000

# Non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Start
CMD ["python", "-m", "uvicorn", "ia.webapp.server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
