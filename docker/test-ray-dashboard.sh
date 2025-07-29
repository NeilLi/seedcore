#!/bin/bash

# Test script to verify Ray dashboard is working with Python 3.10 fixes
# Based on the playbook suggestions

echo "🧪 Testing Ray Dashboard with Python 3.11 fixes..."

# Test 1: Check if Ray cluster is running
echo "1️⃣ Testing Ray cluster initialization..."
docker compose exec ray-head python - <<'PY'
import ray, sys
try:
    ray.init(address='auto', dashboard_host='0.0.0.0')
    print(f"✅ Ray {ray.__version__} initialized successfully")
    print(f"✅ Python {sys.version}")
    print(f"✅ Dashboard URL: {ray.get_dashboard_url()}")
    ray.shutdown()
except Exception as e:
    print(f"❌ Ray initialization failed: {e}")
    exit(1)
PY

# Test 2: Check dashboard API
echo ""
echo "2️⃣ Testing dashboard API..."
if curl -sf http://localhost:8265/api/version; then
    echo "✅ Dashboard API responding"
else
    echo "❌ Dashboard API not responding"
    echo "📋 Checking dashboard logs..."
    docker compose exec ray-head tail -n 20 /tmp/ray/session_latest/logs/dashboard*.log 2>/dev/null || echo "No dashboard logs found"
fi

# Test 3: Check for common error patterns
echo ""
echo "3️⃣ Checking for common Python 3.10 error patterns..."
docker compose logs ray-head | grep -E "(ImportError|contextfilter|setproctitle)" || echo "✅ No common Python 3.10 errors found"

echo ""
echo "🎉 Ray dashboard test completed!"
echo "📊 Dashboard should be available at: http://localhost:8265" 