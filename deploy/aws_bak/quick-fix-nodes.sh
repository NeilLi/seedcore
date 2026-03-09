#!/usr/bin/env bash
# Quick Fix for Node Labels - Option 1 (Simplest)
# Labels all nodes with node-type=general to fix scheduling

set -euo pipefail

echo "🔧 Fixing node labels (Option 1)..."

# Load environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/.env.aws"

# Label all nodes with node-type=general
kubectl get nodes -o name | while read -r node; do
    echo "📝 Labeling $node with node-type=general"
    kubectl label node "$node" node-type=general --overwrite
done

# Verify labels
echo ""
echo "✅ Current node labels:"
kubectl get nodes --show-labels | grep node-type

# Set gp2 as default storage class
echo ""
echo "📦 Setting gp2 as default storage class..."
kubectl patch storageclass gp2 -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

echo ""
echo "🎉 Done! Check your pods:"
echo "   kubectl get pods -n $NAMESPACE -w"

