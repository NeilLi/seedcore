#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="seedcore-dev"
JOB_NAME="seedcore-bootstrap-dispatchers"
JOB_FILE="k8s/bootstrap-dispatchers-job.yaml"

echo "🚀 Deploying job: $JOB_NAME in namespace: $NAMESPACE"

# Check if job exists
if kubectl get job "$JOB_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ℹ️  Job $JOB_NAME already exists. Deleting..."
  kubectl delete job "$JOB_NAME" -n "$NAMESPACE"
else
  echo "ℹ️  No existing job $JOB_NAME found. Proceeding with fresh apply."
fi

# Apply new job definition
echo "📦 Applying job definition from $JOB_FILE..."
kubectl apply -f "$JOB_FILE" -n "$NAMESPACE"

# Optional: Wait for job to complete
echo "⏳ Waiting for job $JOB_NAME to complete..."
kubectl wait --for=condition=complete job/$JOB_NAME -n "$NAMESPACE" --timeout=300s || {
  echo "❌ Job $JOB_NAME did not complete successfully."
  kubectl logs job/$JOB_NAME -n "$NAMESPACE" || true
  exit 1
}

echo "✅ Job $JOB_NAME completed successfully!"
