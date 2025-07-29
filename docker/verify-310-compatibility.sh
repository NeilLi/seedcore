#!/bin/bash

# Comprehensive verification script for Ray 2.48.0 + Python 3.10 compatibility
# Tests all three key fixes mentioned in the playbook

set -e

echo "🔍 Verifying Python 3.10 + Ray 2.48.0 Dashboard Compatibility"
echo "================================================================"

# Test 1: Check Python version and Ray version
echo ""
echo "1️⃣ Checking Python and Ray versions..."
docker compose exec ray-head python -c "
import sys, ray
print(f'✅ Python version: {sys.version}')
print(f'✅ Ray version: {ray.__version__}')
print(f'✅ Python 3.10 detected: {sys.version_info >= (3, 10)}')
"

# Test 2: Check critical package versions
echo ""
echo "2️⃣ Checking critical package versions..."
docker compose exec ray-head python -c "
import pkg_resources
import sys

critical_packages = {
    'setproctitle': '1.3.3',
    'aiohttp-jinja2': '1.5.1', 
    'jinja2': '3.1',
    'grpcio': '1.63.0'
}

for package, min_version in critical_packages.items():
    try:
        version = pkg_resources.get_distribution(package).version
        if package == 'jinja2':
            # jinja2 should be < 3.1
            if pkg_resources.parse_version(version) < pkg_resources.parse_version('3.1'):
                print(f'✅ {package}: {version} (correctly < 3.1)')
            else:
                print(f'❌ {package}: {version} (should be < 3.1)')
        else:
            # Other packages should be >= min_version
            if pkg_resources.parse_version(version) >= pkg_resources.parse_version(min_version):
                print(f'✅ {package}: {version} (>= {min_version})')
            else:
                print(f'❌ {package}: {version} (should be >= {min_version})')
    except pkg_resources.DistributionNotFound:
        print(f'❌ {package}: not installed')
"

# Test 3: Check for import errors
echo ""
echo "3️⃣ Testing critical imports..."
docker compose exec ray-head python -c "
try:
    import setproctitle
    print('✅ setproctitle imports successfully')
except ImportError as e:
    print(f'❌ setproctitle import failed: {e}')

try:
    import aiohttp_jinja2
    print('✅ aiohttp_jinja2 imports successfully')
except ImportError as e:
    print(f'❌ aiohttp_jinja2 import failed: {e}')

try:
    from jinja2 import contextfilter
    print('❌ contextfilter still available (should be removed in Jinja2 3.1+)')
except ImportError:
    print('✅ contextfilter properly removed (good for Python 3.10)')
"

# Test 4: Check Ray cluster initialization
echo ""
echo "4️⃣ Testing Ray cluster initialization..."
docker compose exec ray-head python -c "
import ray
import sys

try:
    ray.init(address='auto', dashboard_host='0.0.0.0')
    print('✅ Ray cluster initialized successfully')
    print(f'✅ Dashboard URL: {ray.get_dashboard_url()}')
    ray.shutdown()
except Exception as e:
    print(f'❌ Ray initialization failed: {e}')
    sys.exit(1)
"

# Test 5: Check dashboard API responsiveness
echo ""
echo "5️⃣ Testing dashboard API..."
if curl -sf --max-time 10 http://localhost:8265/api/version > /dev/null; then
    echo "✅ Dashboard API responding"
    curl -s http://localhost:8265/api/version | head -1
else
    echo "❌ Dashboard API not responding"
    echo "📋 Checking dashboard logs..."
    docker compose exec ray-head tail -n 20 /tmp/ray/session_latest/logs/dashboard*.log 2>/dev/null || echo "No dashboard logs found"
fi

# Test 6: Check for common error patterns in logs
echo ""
echo "6️⃣ Scanning for common Python 3.10 error patterns..."
ERRORS_FOUND=0

# Check for setproctitle errors
if docker compose logs ray-head 2>/dev/null | grep -q "setproctitle"; then
    echo "❌ Found setproctitle errors in logs"
    ERRORS_FOUND=1
fi

# Check for contextfilter errors  
if docker compose logs ray-head 2>/dev/null | grep -q "contextfilter"; then
    echo "❌ Found contextfilter errors in logs"
    ERRORS_FOUND=1
fi

# Check for ImportError patterns
if docker compose logs ray-head 2>/dev/null | grep -q "ImportError.*setproctitle\|ImportError.*contextfilter"; then
    echo "❌ Found ImportError patterns in logs"
    ERRORS_FOUND=1
fi

if [ $ERRORS_FOUND -eq 0 ]; then
    echo "✅ No common Python 3.10 error patterns found"
fi

# Test 7: Check port accessibility
echo ""
echo "7️⃣ Checking port accessibility..."
if netstat -tlnp 2>/dev/null | grep -q ":8265 "; then
    echo "✅ Dashboard port 8265 is listening"
else
    echo "❌ Dashboard port 8265 not listening"
fi

if netstat -tlnp 2>/dev/null | grep -q ":52365 "; then
    echo "✅ Agent gRPC port 52365 is listening"
else
    echo "❌ Agent gRPC port 52365 not listening"
fi

if netstat -tlnp 2>/dev/null | grep -q ":52366 "; then
    echo "✅ Agent HTTP port 52366 is listening"
else
    echo "❌ Agent HTTP port 52366 not listening"
fi

# Test 8: Check Ray temp directory
echo ""
echo "8️⃣ Checking Ray temp directory..."
if docker compose exec ray-head ls -la /home/ray/ray_tmp 2>/dev/null; then
    echo "✅ Ray temp directory exists and is accessible"
else
    echo "❌ Ray temp directory not accessible"
fi

# Test 9: Check Ray port allocation in logs
echo ""
echo "9️⃣ Checking Ray port allocation..."
if docker compose logs ray-head 2>/dev/null | grep -q "dashboard_agent_grpc.*52365"; then
    echo "✅ Agent gRPC correctly bound to 52365"
else
    echo "❌ Agent gRPC not bound to 52365"
fi

if docker compose logs ray-head 2>/dev/null | grep -q "dashboard_agent_http.*52366"; then
    echo "✅ Agent HTTP correctly bound to 52366"
else
    echo "❌ Agent HTTP not bound to 52366"
fi

echo ""
echo "🎉 Compatibility verification completed!"
echo "📊 Dashboard should be available at: http://localhost:8265"
echo ""
echo "If any tests failed, check the logs with:"
echo "  docker compose logs ray-head"
echo ""
echo "For detailed dashboard logs:"
echo "  docker compose exec ray-head tail -f /tmp/ray/session_latest/logs/dashboard.log" 