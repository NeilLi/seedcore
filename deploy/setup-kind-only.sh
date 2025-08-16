#!/bin/bash
set -euo pipefail

CLUSTER_NAME="seedcore-dev"

echo "🚀 Starting Kind cluster only..."

# Check if cluster already exists
if kind get clusters | grep -q "$CLUSTER_NAME"; then
    echo "⚠️  Cluster $CLUSTER_NAME already exists"
    read -p "Do you want to delete and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🗑️  Deleting existing cluster..."
        kind delete cluster --name "$CLUSTER_NAME"
    else
        echo "✅ Using existing cluster"
        exit 0
    fi
fi

# Create Kind cluster
echo "📦 Creating Kind cluster with kindest/node:v1.30.0..."
kind create cluster --name "$CLUSTER_NAME" --image kindest/node:v1.30.0 --config kind-config.yaml

# Verify cluster
echo "🔍 Verifying cluster..."
kubectl cluster-info --context "kind-$CLUSTER_NAME"

echo "✅ Kind cluster '$CLUSTER_NAME' is ready!"
echo ""
echo "�� Useful commands:"
echo "   - Check nodes: kubectl get nodes"
echo "   - Check context: kubectl config current-context"
echo "   - Switch context: kubectl config use-context kind-seedcore-dev"
echo "   - Delete cluster: kind delete cluster --name $CLUSTER_NAME"
