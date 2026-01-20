#!/bin/bash

# Safer Cleanup Script for Kubernetes Data Stores
# Removes Neo4j, Redis, MySQL, and PostgreSQL Helm releases
# Optional: Remove Persistent Volume Claims (PVCs)
#
# Usage:
#   ./cleanup-datastores.sh [namespace] [--with-pvc] [--dry-run]
#
# Examples:
#   ./cleanup-datastores.sh
#   ./cleanup-datastores.sh seedcore-staging --with-pvc
#   ./cleanup-datastores.sh my-namespace --dry-run

set -euo pipefail

# ---------------------------
# Parse arguments
# ---------------------------
NAMESPACE=${1:-seedcore-dev}
WITH_PVC=false
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --with-pvc) WITH_PVC=true ;;
    --dry-run)  DRY_RUN=true ;;
  esac
done

echo "🧹 Cleaning up data stores in namespace: ${NAMESPACE}"
if [ "$DRY_RUN" = true ]; then
  echo "⚠️  Dry-run mode enabled: no resources will actually be deleted."
fi

# ---------------------------
# Preconditions
# ---------------------------
if ! command -v helm &> /dev/null; then
  echo "❌ helm not found. Please install Helm before running this script."
  exit 1
fi

if ! command -v kubectl &> /dev/null; then
  echo "❌ kubectl not found. Please install kubectl before running this script."
  exit 1
fi

# ---------------------------
# Function to uninstall Helm releases
# ---------------------------
uninstall_release() {
  local release=$1
  echo "🗑️  Removing $release..."
  if [ "$DRY_RUN" = true ]; then
    echo "   → Would run: helm uninstall $release -n $NAMESPACE --wait"
  else
    helm uninstall "$release" -n "$NAMESPACE" --wait || echo "   ⚠️  $release not found, skipping."
  fi
}

# ---------------------------
# Cleanup Helm releases
# ---------------------------
#uninstall_release "neo4j"
#uninstall_release "redis"
#uninstall_release "mysql"
uninstall_release "postgresql"

# ---------------------------
# Optional PVC cleanup
# ---------------------------
if [ "$WITH_PVC" = true ]; then
  echo "🗑️  Removing Persistent Volume Claims in namespace: $NAMESPACE..."
  if [ "$DRY_RUN" = true ]; then
    echo "   → Would run: kubectl delete pvc -n $NAMESPACE -l app.kubernetes.io/name"
  else
    kubectl delete pvc -n "$NAMESPACE" -l app.kubernetes.io/name || echo "   ⚠️  No PVCs found."
  fi
else
  echo "⚠️  PVCs were not removed. Use --with-pvc if you want to delete volumes (this will delete stored data)."
fi

# ---------------------------
# Done
# ---------------------------
echo "✅ Cleanup complete for namespace: $NAMESPACE"
