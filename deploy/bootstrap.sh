#!/usr/bin/env bash
set -euo pipefail
trap "echo '🛑 Interrupted'; exit 1" INT

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAMESPACE="${NAMESPACE:-seedcore-dev}"
JOB_NAME="seedcore-bootstrap"
JOB_FILE="${SCRIPT_DIR}/k8s/bootstrap-job.yaml"

echo "🚀 Deploying bootstrap job:"
echo "   • Job:       $JOB_NAME"
echo "   • Namespace: $NAMESPACE"
echo "   • File:      $JOB_FILE"

# Namespace safety guard
if [[ -z "$NAMESPACE" ]]; then
  echo "❌ ERROR: NAMESPACE is empty. Aborting."
  exit 1
fi

# File existence guard
if [[ ! -f "$JOB_FILE" ]]; then
  echo "❌ ERROR: Job file not found: $JOB_FILE"
  exit 1
fi

# Check if job already exists
if kubectl get job "$JOB_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ℹ️  Job $JOB_NAME already exists. Deleting..."
  kubectl delete job "$JOB_NAME" -n "$NAMESPACE"
else
  echo "ℹ️  No existing job $JOB_NAME found. Fresh deploy."
fi

# Apply new job definition
echo "📦 Applying job..."
kubectl apply -f "$JOB_FILE" -n "$NAMESPACE"

# Wait for completion
# Increased timeout to 900s (15 minutes) to allow for slow initialization
# Dispatchers need to connect to DB, initialize pools, etc.
TIMEOUT="${BOOTSTRAP_TIMEOUT:-900}"
echo "⏳ Waiting for job to complete (timeout: ${TIMEOUT}s)..."
if ! kubectl wait --for=condition=complete job/$JOB_NAME -n "$NAMESPACE" --timeout="${TIMEOUT}s"; then
  echo "❌ Job $JOB_NAME did not complete successfully."

  echo "🔍 Job describe:"
  kubectl describe job/$JOB_NAME -n "$NAMESPACE" || true

  echo "📝 Recent logs:"
  kubectl logs job/$JOB_NAME -n "$NAMESPACE" --tail=200 || true

  exit 1
fi

echo "✅ Job $JOB_NAME completed successfully!"

# Optional: stream full logs
# kubectl logs job/$JOB_NAME -n "$NAMESPACE" --tail=-1

echo "🎉 Bootstrap done."
