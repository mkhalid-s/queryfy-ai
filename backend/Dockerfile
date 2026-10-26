# QueryfyAI Backend Dockerfile
# Multi-stage build for smaller production image

# ============================================================================
# BUILDER STAGE - Install dependencies
# ============================================================================
FROM python:3.14-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies to /app/.venv
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================================
# PRODUCTION STAGE - Slim runtime image
# ============================================================================
FROM python:3.14-slim

# Security: Create non-root user
RUN groupadd -r queryfyai && useradd -r -g queryfyai queryfyai

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY --chown=queryfyai:queryfyai . .

# Create directories for data persistence
RUN mkdir -p /app/data/chroma_db && \
    chown -R queryfyai:queryfyai /app/data

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    CHROMA_PERSIST_DIR=/app/data/chroma_db

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Switch to non-root user
USER queryfyai

# Default: Production mode with gunicorn (multiple workers)
# Override with: docker run ... uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
