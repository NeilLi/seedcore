#!/bin/bash

# Adjusted to match your cluster's control plane container name
KIND_NODE="seedcore-dev-control-plane"

echo "🎯 Targeting KIND node: ${KIND_NODE}"
echo "-------------------------------------"

echo "🔎 Identifying images in use by the cluster..."
# Get all images currently used by pods in the cluster and store them in a variable
# Using jsonpath with a range is slightly more robust
USED_IMAGES=$(kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}' | sort -u)

echo "✅ Found the following used images:"
echo "${USED_IMAGES}"
echo "-------------------------------------"

echo "🔎 Finding all images present on the control plane node..."
# Get all images from the crictl runtime inside the node container
ALL_IMAGES=$(docker exec "${KIND_NODE}" crictl images --output json | jq -r '.images[].repoTags | .[]' | grep -v "<none>")

echo "🧹 Starting cleanup of unused images..."

# Loop through every image found on the node
for img in $ALL_IMAGES; do
  # Check if the image from the node exists in the list of used images
  if ! echo "${USED_IMAGES}" | grep -q "^${img}$"; then
    echo "  - 🗑️ Deleting unused image: ${img}"
    # If not in use, execute the remove command inside the node container
    docker exec "${KIND_NODE}" crictl rmi "${img}"
  else
    echo "  - ✅ Keeping used image: ${img}"
  fi
done

echo "🎉 Cleanup complete!"
