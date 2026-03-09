#!/usr/bin/env bash
# AWS EKS Bootstrap Organism Script
# Deploys organism bootstrap job for AWS EKS deployment

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

JOB_NAME="seedcore-bootstrap-organism"
JOB_FILE="${SCRIPT_DIR}/bootstrap-organism-job.yaml"

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
  name: seedcore-bootstrap-organism
  namespace: ${NAMESPACE}
  labels:
    app: seedcore
    component: bootstrap-organism
spec:
  completions: 1
  parallelism: 1
  backoffLimit: 3
  template:
    metadata:
      labels:
        app: seedcore
        component: bootstrap-organism
    spec:
      serviceAccountName: seedcore-service-account
      restartPolicy: Never
      containers:
      - name: bootstrap-organism
        image: ${ECR_REPO}:${SEEDCORE_IMAGE_TAG}
        imagePullPolicy: Always
        command: ["python", "/app/bootstraps/bootstrap_entry.py"]
        env:
        # Tell the entrypoint to only init the organism and exit
        - name: BOOTSTRAP_MODE
          value: "organism"
        - name: EXIT_AFTER_BOOTSTRAP
          value: "true"

        # Ray connectivity
        - name: RAY_ADDRESS
          value: "ray://${RAY_HEAD_SVC}:${RAY_HEAD_PORT}"
        - name: RAY_NAMESPACE
          value: "${SEEDCORE_NS}"
        - name: SEEDCORE_NS
          value: "${SEEDCORE_NS}"
        - name: RUNNING_IN_CLUSTER
          value: "1"

        # DB DSN
        - name: SEEDCORE_PG_DSN
          value: "postgresql://postgres:${POSTGRES_PASSWORD}@postgresql.${NAMESPACE}.svc.cluster.local:5432/seedcore"

        # HTTP fallback for init_organism.py
        - name: SERVE_BASE_URL
          value: "http://seedcore-svc-serve-svc.${NAMESPACE}.svc.cluster.local:8000"
        - name: ORGANISM_URL
          value: "http://seedcore-svc-serve-svc.${NAMESPACE}.svc.cluster.local:8000/organism"
        
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


