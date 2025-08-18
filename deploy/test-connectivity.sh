#!/bin/bash

echo "🔍 Testing Kubernetes service connectivity..."
echo "=============================================="

# Test basic service resolution
echo "📡 Testing service DNS resolution:"
for service in postgres mysql redis neo4j prometheus grafana; do
    if kubectl get svc $service -n seedcore-dev >/dev/null 2>&1; then
        echo "✅ $service service exists"
    else
        echo "❌ $service service missing"
    fi
done

echo ""
echo "🌐 Testing service ports:"
echo "postgres:5432, mysql:3306, redis:6379, neo4j:7474/7687, prometheus:80, grafana:3000"

echo ""
echo "📊 Current service status:"
kubectl get svc -n seedcore-dev | grep -E "(postgres|mysql|redis|neo4j|prometheus|grafana)" | head -10

echo ""
echo "🐳 Current pod status:"
kubectl get pods -n seedcore-dev | grep -E "(postgres|mysql|redis|neo4j|prometheus|grafana)" | head -10

echo ""
echo "🔗 Service connectivity test (from cluster):"
echo "Note: This will only work when pods are ready"

# Test if we can at least resolve the services
echo ""
echo "Testing service resolution from within cluster..."
kubectl run connectivity-test --rm -it --image=busybox:1.36 --restart=Never --namespace=seedcore-dev -- sh -c '
echo "Testing service resolution..." &&
for svc in postgres:5432 mysql:3306 redis:6379 neo4j:7474 neo4j:7687; do
    host=$(echo $svc | cut -d: -f1)
    port=$(echo $svc | cut -d: -f2)
    echo "Testing $host:$port..."
    if nslookup $host >/dev/null 2>&1; then
        echo "✅ $host resolves"
    else
        echo "❌ $host does not resolve"
    fi
done
' 2>/dev/null || echo "Connectivity test pod not ready yet"

echo ""
echo "🎯 Next steps:"
echo "1. Wait for pods to become Ready (may take several minutes)"
echo "2. Run: kubectl get pods -n seedcore-dev -w"
echo "3. Test API connectivity when ready"
echo "4. Use port-forward to access services from your laptop"





