#!/usr/bin/env bash
# Get the new pod's name automatically
NEW_POD_NAME=$(kubectl get pods -n seedcore-dev -l app=seedcore-api -o jsonpath='{.items[0].metadata.name}')

# Check for the file inside the new pod
echo "Verifying mount in pod: $NEW_POD_NAME"
kubectl exec -it $NEW_POD_NAME -n seedcore-dev -- bash
