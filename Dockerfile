# PromiseLink FastAPI Application
# Multi-stage build for production-optimized image
# =============================================================================
# Stage 1: Builder — install dependencies into virtual environment
# Stage 2: Runtime — copy only what's needed, run as non-root user
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
# Stage 2: Runtime — minimal image with non-root user
# =============================================================================
FROM python:3.11-slim AS runtime

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
