#!/usr/bin/env bash
# AWS EKS Bootstrap Dispatchers Script
# Deploys dispatchers bootstrap job for AWS EKS deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables
if [ -f "${SCRIPT_DIR}/.env.aws" ]; then
    source "${SCRIPT_DIR}/.env.aws"
else
    echo "ERROR: Environment file not found: ${SCRIPT_DIR}/.env.aws"
    echo "Please run ./aws-init.sh first to set up the environment"
    exit 1
fi

JOB_NAME="seedcore-bootstrap-dispatchers"
JOB_FILE="${SCRIPT_DIR}/bootstrap-dispatchers-job.yaml"

echo "🚀 Deploying job: $JOB_NAME in namespace: $NAMESPACE"

# Check if job exists
if kubectl get job "$JOB_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ℹ️  Job $JOB_NAME already exists. Deleting..."
  kubectl delete job "$JOB_NAME" -n "$NAMESPACE"
else
  echo "ℹ️  No existing job $JOB_NAME found. Proceeding with fresh apply."
fi

# Create bootstrap job manifest for AWS deployment
cat > "$JOB_FILE" << EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: seedcore-bootstrap-dispatchers
  namespace: ${NAMESPACE}
  labels:
    app: seedcore
    component: bootstrap-dispatchers
spec:
  completions: 1
  parallelism: 1
  backoffLimit: 3
  template:
    metadata:
      labels:
        app: seedcore
        component: bootstrap-dispatchers
    spec:
      serviceAccountName: seedcore-service-account
      restartPolicy: Never
      containers:
      - name: bootstrap-dispatchers
        image: ${ECR_REPO}:${SEEDCORE_IMAGE_TAG}
        imagePullPolicy: Always
        command: ["python", "/app/bootstraps/bootstrap_entry.py"]
        env:
        # Tell the entrypoint to only init dispatchers and exit
        - name: BOOTSTRAP_MODE
          value: "dispatchers"
        - name: EXIT_AFTER_BOOTSTRAP
          value: "true"

        # Dispatcher bring-up options
        - name: FORCE_REPLACE_DISPATCHERS
          value: "true"
        - name: DISPATCHER_COUNT
          value: "2"
        - name: SEEDCORE_GRAPH_DISPATCHERS
          value: "1"
        - name: DGLBACKEND
          value: "pytorch"

        # Ray connectivity
        - name: RAY_ADDRESS
          value: "ray://${RAY_HEAD_SVC}:${RAY_HEAD_PORT}"
        - name: RAY_NAMESPACE
          value: "${SEEDCORE_NS}"
        - name: SEEDCORE_NS
          value: "${SEEDCORE_NS}"
        - name: RUNNING_IN_CLUSTER
          value: "1"

        # Database for dispatchers/reaper/graph-dispatchers
        - name: SEEDCORE_PG_DSN
          value: "postgresql://postgres:${POSTGRES_PASSWORD}@postgresql.${NAMESPACE}.svc.cluster.local:5432/seedcore"

        # Optional tuning passed into actors
        - name: OCPS_DRIFT_THRESHOLD
          value: "0.5"
        - name: COGNITIVE_TIMEOUT_S
          value: "8.0"
        - name: COGNITIVE_MAX_INFLIGHT
          value: "64"
        - name: FAST_PATH_LATENCY_SLO_MS
          value: "1000"
        - name: MAX_PLAN_STEPS
          value: "16"
        
        resources:
          requests:
            cpu: "100m"
            memory: "512Mi"
          limits:
            cpu: "200m"
            memory: "1Gi"
EOF

# Apply new job definition
echo "📦 Applying job definition from $JOB_FILE..."
kubectl apply -f "$JOB_FILE" -n "$NAMESPACE"

# Wait for job to complete
echo "⏳ Waiting for job $JOB_NAME to complete..."
kubectl wait --for=condition=complete job/$JOB_NAME -n "$NAMESPACE" --timeout=600s || {
  echo "❌ Job $JOB_NAME did not complete successfully."
  kubectl logs job/$JOB_NAME -n "$NAMESPACE" || true
  exit 1
}

echo "✅ Job $JOB_NAME completed successfully!"

# Clean up generated file
rm -f "$JOB_FILE"


