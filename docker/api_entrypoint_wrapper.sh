#!/bin/bash
set -e

echo "🚀 Starting SeedCore API..."

# Set environment variables to prevent file logging BEFORE any Python imports
export DSP_LOG_TO_FILE=false
export DSP_LOG_TO_STDOUT=true
export DSP_LOG_LEVEL=INFO
export LOG_TO_FILE=false
export LOG_TO_STDOUT=true
export PYTHONPATH=/app:/app/src

# Also set these as Python environment variables
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

echo "🔧 Environment variables set:"
echo "  DSP_LOG_TO_FILE=$DSP_LOG_TO_FILE"
echo "  DSP_LOG_TO_STDOUT=$DSP_LOG_TO_STDOUT"
echo "  PYTHONPATH=$PYTHONPATH"

# Check if required files exist
echo "🔍 Checking required files..."
if [ ! -f "/app/logging_config.py" ]; then
    echo "❌ Error: logging_config.py not found in /app/"
    exit 1
fi

if [ ! -d "/app/src" ]; then
    echo "❌ Error: src directory not found in /app/"
    exit 1
fi

if [ ! -f "/app/src/seedcore/telemetry/server.py" ]; then
    echo "❌ Error: server.py not found in /app/src/seedcore/telemetry/"
    exit 1
fi

echo "✅ All required files found"

# Configure logging first
echo "📝 Configuring logging..."
python /app/logging_config.py

# Start the API server with environment variables already set
echo "🌐 Starting uvicorn server..."
echo "🚀 Executing: uvicorn src.seedcore.telemetry.server:app --host 0.0.0.0 --port 8002 --proxy-headers --forwarded-allow-ips *"

# Use exec to replace the shell process with uvicorn
exec python -m uvicorn src.seedcore.telemetry.server:app \
    --host 0.0.0.0 \
    --port 8002 \
    --proxy-headers \
    --forwarded-allow-ips "*"



