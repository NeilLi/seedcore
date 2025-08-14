# docker/Dockerfile.app
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gcc g++ make \
        libpq-dev libssl-dev curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY docker/requirements-minimal.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip wheel && \
    pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app

# Copy only essential source code (from parent directory context)
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY docker/ ./docker/

# Ensure models directory exists
RUN mkdir -p /app/src/seedcore/ml/models

# Runtime environment
ENV PYTHONPATH=/app:/app/src \
    PYTHONUNBUFFERED=1 \
    RAY_USAGE_STATS_ENABLED=0

# Expose the API port
EXPOSE 8002

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Health check for the API endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=5).read()" || exit 1

# Copy entrypoint script
COPY docker/app_entrypoint.py /app/app_entrypoint.py

# Default command - will be overridden by deployment
CMD ["python", "/app/app_entrypoint.py"]


