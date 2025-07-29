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

# Set environment
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('localhost', 8000), timeout=5)" || exit 1

CMD ["uvicorn", "src.seedcore.telemetry.server:app", "--host", "0.0.0.0", "--port", "8000"] 