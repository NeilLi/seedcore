#!/bin/bash
set -e

echo "🚀 Starting SeedCore API..."
echo "📁 Current working directory: $(pwd)"
echo "📁 Directory contents: $(ls -la)"
echo "🔍 Python path: $PYTHONPATH"
echo "🔍 Entrypoint script location: $(which /app/api_entrypoint.sh)"
echo "🔍 Entrypoint script permissions: $(ls -la /app/api_entrypoint.sh)"
echo "🔍 Home directory: $HOME"
echo "🔍 User: $(whoami)"

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

if [ ! -f "/app/src/seedcore/main.py" ]; then
    echo "❌ Error: main.py not found in /app/src/seedcore/"
    exit 1
fi

echo "✅ All required files found"

# Configure logging first
echo "📝 Configuring logging..."
python /app/logging_config.py

# Import DSP patch to prevent file logging issues
echo "🔧 Importing DSP patch..."
cd /app && python -c "from seedcore.cognitive import dsp_patch" 2>/dev/null || echo "⚠️  DSP patch import failed, continuing..."

# Start the API server
echo "🌐 Starting uvicorn server..."
echo "🚀 Executing: uvicorn src.seedcore.main:app --host 0.0.0.0 --port 8002 --proxy-headers --forwarded-allow-ips *"
exec uvicorn src.seedcore.main:app \
    --host 0.0.0.0 \
    --port 8002 \
    --proxy-headers \
    --forwarded-allow-ips "*"
