#!/bin/bash
set -euo pipefail

# Adjust to match your cluster's control plane container name
KIND_NODE="seedcore-dev-control-plane"

# Skip list: images we always want to keep locally
SKIP_IMAGES=("seedcore-api:kind" "seedcore-serve:latest" "kindest/node:v1.30.0")

echo "🎯 Targeting KIND node: ${KIND_NODE}"
echo "-------------------------------------"

echo "🔎 Identifying images in use by the cluster..."
USED_IMAGES=$(kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}' | sort -u)

echo "✅ Found the following used images:"
echo "${USED_IMAGES}"
echo "-------------------------------------"

echo "🔎 Finding all images present on the control plane node..."
ALL_IMAGES=$(docker exec "${KIND_NODE}" crictl images --output json | jq -r '.images[].repoTags | .[]' | grep -v "<none>")

echo "🧹 Starting cleanup of unused images..."

for img in $ALL_IMAGES; do
  # Check if the image is in the skip list
  if printf '%s\n' "${SKIP_IMAGES[@]}" | grep -qx "$img"; then
    echo "  - 🔒 Skipping protected image: ${img}"
    continue
  fi

  # Check if the image is currently in use by the cluster
  if ! echo "${USED_IMAGES}" | grep -qx "$img"; then
    echo "  - 🗑️ Deleting unused image: ${img}"
    docker exec "${KIND_NODE}" crictl rmi "${img}" || echo "    ⚠️ Failed to delete ${img}, skipping."
  else
    echo "  - ✅ Keeping used image: ${img}"
  fi
done

echo "🎉 Cleanup complete!"
