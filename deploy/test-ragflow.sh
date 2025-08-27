#!/bin/bash

# Test RAGFlow deployment and connectivity
# This script verifies that RAGFlow is properly deployed and can connect to its dependencies

set -e

NAMESPACE="seedcore-dev"
RAGFLOW_SERVICE="ragflow"

echo "🧪 Testing RAGFlow deployment and connectivity..."

# Check if RAGFlow pod is running
echo "📋 Checking RAGFlow pod status..."
kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=ragflow

# Check RAGFlow service
echo "🔌 Checking RAGFlow service..."
kubectl get svc -n $NAMESPACE $RAGFLOW_SERVICE

# Test RAGFlow health endpoint
echo "🏥 Testing RAGFlow health endpoint..."
kubectl port-forward -n $NAMESPACE svc/$RAGFLOW_SERVICE 8080:8080 &
PF_PID=$!

# Wait for port-forward to be ready
sleep 5

# Test health endpoint
if curl -s http://localhost:8080/health > /dev/null; then
    echo "✅ RAGFlow health check passed"
else
    echo "❌ RAGFlow health check failed"
fi

# Test readiness endpoint
if curl -s http://localhost:8080/ready > /dev/null; then
    echo "✅ RAGFlow readiness check passed"
else
    echo "❌ RAGFlow readiness check failed"
fi

# Stop port-forward
kill $PF_PID 2>/dev/null || true

# Check RAGFlow logs for any errors
echo "📝 Checking RAGFlow logs for errors..."
kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=ragflow --tail=20 | grep -i error || echo "No errors found in recent logs"

# Verify environment variables
echo "🔍 Verifying RAGFlow environment variables..."
kubectl exec -n $NAMESPACE deploy/$RAGFLOW_SERVICE -- env | grep -E "(DATABASE|REDIS|NEO4J)" | head -10

echo ""
echo "🎯 RAGFlow deployment test completed!"
echo ""
echo "💡 To manually test RAGFlow API:"
echo "   kubectl port-forward -n $NAMESPACE svc/$RAGFLOW_SERVICE 8080:8080"
echo "   curl http://localhost:8080/health"
echo "   curl http://localhost:8080/ready"
