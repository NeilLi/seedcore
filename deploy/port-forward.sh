#!/bin/bash

# Define the Kubernetes namespace you are working in
NAMESPACE="seedcore-dev"

# Find the head service using the reliable 'node-type=head' label
# This works without needing to know the specific cluster name
echo "🔎 Finding Ray head service in namespace '${NAMESPACE}'..."
HEAD_SVC=$(kubectl -n "${NAMESPACE}" get svc \
  -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')

# Check if the service was found
if [ -z "$HEAD_SVC" ]; then
  echo "❌ Ray head service not found. Make sure your Ray cluster is running."
  exit 1
fi

echo "✅ Found head service: ${HEAD_SVC}"
echo "🚀 Starting port-forwarding... (Press Ctrl+C to stop)"

# Port-forward the Dashboard (8265) and a port for Ray Serve (8001 -> 8000)
kubectl -n "${NAMESPACE}" port-forward "svc/${HEAD_SVC}" 8265:8265 &
kubectl -n "${NAMESPACE}" port-forward "svc/${HEAD_SVC}" 8001:8000 &

# Wait for all background jobs to finish (i.e., wait for user to press Ctrl+C)
wait