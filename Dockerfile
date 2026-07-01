# PromiseLink FastAPI Application
# Multi-stage build for production-optimized image
# =============================================================================
# Stage 1: frontend-builder — build H5 static assets with Node.js
# Stage 2: builder — install Python dependencies into virtual environment
# Stage 3: runtime — copy only what's needed, run as non-root user
# =============================================================================

# =============================================================================
# Stage 1: Frontend Builder — Taro H5 build
# =============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# Install dependencies first (cached layer)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy frontend source and build H5 distribution
COPY frontend/ ./
RUN npm run build:h5

# =============================================================================
# Stage 2: Builder — install Python dependencies
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies (removed in final stage)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 3: Runtime — minimal image with non-root user
# =============================================================================
FROM python:3.11-slim AS runtime

# Build-time version label (kept in sync with VERSION file and pyproject.toml)
ARG VERSION=0.7.0

# OCI-standard image labels for registry indexing and traceability
LABEL org.opencontainers.image.title="PromiseLink" \
      org.opencontainers.image.description="AI-driven personal business relationship management assistant (base edition, AGPL v3)" \
      org.opencontainers.image.source="https://github.com/lulin70/PromiseLink" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="AGPL-3.0" \
      org.opencontainers.image.authors="CarryMem Team <team@carrymem.com>"

# Install runtime-only dependencies
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r promiselink \
    && useradd -r -g promiselink -d /app -s /sbin/nologin promiselink

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application code (src/promiselink/ → /app/src/promiselink/)
COPY src/ ./src/

# Copy frontend build output from frontend-builder
# main.py mounts /app/static as the H5 static files root
COPY --from=frontend-builder --chown=promiselink:promiselink /frontend/dist/ /app/static/

# Create data directory for SQLite (owned by non-root user)
RUN mkdir -p /app/data && chown promiselink:promiselink /app/data

# Switch to non-root user
USER promiselink

# Expose port
EXPOSE 8000

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Run from src/ so Python can find promiselink package
WORKDIR /app/src
CMD ["uvicorn", "promiselink.main:app", "--host", "0.0.0.0", "--port", "8000"]
