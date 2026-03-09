# NIM Services Deployment Guide

## Overview

The NIM (NVIDIA Inference Microservice) services are integrated into the SeedCore deployment:

1. **NIM Retrieval** - Embedding and retrieval service
2. **NIM Llama** - LLM inference service (requires GPU nodes)

## What Was Added

### Enhanced `deploy_nim_services()` Function

The function now includes:

✅ **Secret Creation** - Creates placeholder secrets for NIM services
✅ **Error Handling** - Better error messages and log checking
✅ **GPU Detection** - Automatically detects GPU nodes for NIM Llama
✅ **Status Reporting** - Shows deployment and service status
✅ **Conditional Deployment** - Skips NIM Llama if no GPU nodes available

### Key Features

#### 1. Automatic Secret Creation
```bash
# Creates placeholder secrets if they don't exist
- nim-retrieval-secret
- nim-llama-secret
```

**Note:** Update these secrets with actual values in production!

#### 2. GPU Node Detection
- Automatically checks for GPU nodes before deploying NIM Llama
- Skips deployment if GPU nodes are not available
- Deletes failed deployment if GPU is unavailable

#### 3. Better Error Messages
- Shows pod logs on failure
- Reports deployment status
- Continues deployment even if one service fails

#### 4. Optional Deployment
Deploy without NIM services if images aren't ready:

```bash
SKIP_NIM=true ./deploy-all.sh deploy
```

## Deployment Configuration

### Storage Requirements

The deployment automatically creates PVCs:

- `nim-model-pvc` - 50Gi for retrieval models
- `nim-llama-model-pvc` - 100Gi for LLM models

### Resource Requirements

**NIM Retrieval:**
- CPU: 2000m request, 4000m limit
- Memory: 4Gi request, 8Gi limit
- 2 replicas

**NIM Llama:**
- CPU: 2000m request, 4000m limit
- Memory: 8Gi request, 16Gi limit
- GPU: 1 NVIDIA GPU
- 1 replica (GPU limited)

### ConfigMaps

ConfigMaps are auto-created from the YAML files:

- `nim-retrieval-config` - NIM Retrieval configuration
- `nim-llama-config` - NIM Llama configuration

## Deployment Flow

1. **Create Namespace** ✅
2. **Deploy RBAC** ✅
3. **Create Storage PVCs** ✅
4. **Deploy Databases** ✅
5. **Deploy Ray Service** ✅
6. **Deploy SeedCore API** ✅
7. **Deploy NIM Services** ← Enhanced function here
8. **Deploy Ingress** ✅

## Usage

### Deploy Everything (including NIM)

```bash
cd /Users/ningli/project/seedcore/deploy/aws
./deploy-all.sh deploy
```

### Deploy Without NIM Services

```bash
SKIP_NIM=true ./deploy-all.sh deploy
```

### Check NIM Status

```bash
# Get NIM pods
kubectl get pods -n seedcore-dev -l app=nim-retrieval
kubectl get pods -n seedcore-dev -l app=nim-llama

# Check logs
kubectl logs -n seedcore-dev -l app=nim-retrieval --tail=50
kubectl logs -n seedcore-dev -l app=nim-llama --tail=50

# Check services
kubectl get svc -n seedcore-dev -l app=nim-retrieval
kubectl get svc -n seedcore-dev -l app=nim-llama
```

## Environment Variables

Make sure these are set in `.env.aws`:

```bash
# ECR Repositories
ECR_NIM_REPO=${ECR_REGISTRY}/nim-retrieval
ECR_LLAMA_REPO=${ECR_REGISTRY}/nim-llama

# Image Tags
NIM_RETRIEVAL_TAG=latest
NIM_LLAMA_TAG=latest

# Storage
STORAGE_CLASS=gp3  # or gp2, or your custom storage class

# Skip NIM (optional)
SKIP_NIM=false  # Set to true to skip NIM services
```

## Prerequisites

### For NIM Retrieval:
- ECR repository with retrieval model image
- No special hardware required

### For NIM Llama:
- ECR repository with Llama model image
- GPU nodes labeled with `node-type: gpu`
- GPU drivers installed on nodes
- NVIDIA device plugin deployed in the cluster

### Check GPU Nodes

```bash
# Check if GPU nodes exist
kubectl get nodes -l node-type=gpu

# Check GPU availability
kubectl describe node <gpu-node-name> | grep nvidia.com/gpu

# Check if NVIDIA device plugin is running
kubectl get pods -n kube-system | grep nvidia
```

## Troubleshooting

### NIM Retrieval Not Starting

```bash
# Check pod status
kubectl get pods -n seedcore-dev -l app=nim-retrieval

# Check pod logs
kubectl logs -n seedcore-dev -l app=nim-retrieval --tail=50

# Check events
kubectl describe pod -n seedcore-dev -l app=nim-retrieval
```

### NIM Llama Pod Pending

```bash
# Check if GPU resources are available
kubectl describe node | grep -A 5 Capacity

# Check pending reasons
kubectl describe pod -n seedcore-dev -l app=nim-llama | grep -A 10 Events

# Check node selectors
kubectl get nodes --show-labels | grep node-type
```

### Image Pull Errors

```bash
# Verify image exists in ECR
aws ecr describe-images --repository-name nim-retrieval --region us-east-1
aws ecr describe-images --repository-name nim-llama --region us-east-1

# Check image pull secrets
kubectl get secrets -n seedcore-dev | grep regcred

# Pull image manually to test
docker pull ${ECR_REGISTRY}/nim-retrieval:latest
docker pull ${ECR_REGISTRY}/nim-llama:latest
```

### Secrets Not Found

Update the placeholder secrets with actual values:

```bash
# Update retrieval secret
kubectl create secret generic nim-retrieval-secret \
  --from-literal=model_api_key="your-api-key" \
  --from-literal=encryption_key="your-encryption-key" \
  --dry-run=client -o yaml | kubectl apply -f -

# Update llama secret
kubectl create secret generic nim-llama-secret \
  --from-literal=model_api_key="your-api-key" \
  --from-literal=encryption_key="your-encryption-key" \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods to pick up new secrets
kubectl delete pod -n seedcore-dev -l app=nim-retrieval
kubectl delete pod -n seedcore-dev -l app=nim-llama
```

## Production Checklist

- [ ] Update NIM secrets with actual values
- [ ] Verify ECR images exist and are accessible
- [ ] Ensure GPU nodes are available for NIM Llama
- [ ] Test NIM services independently before full deployment
- [ ] Configure proper resource limits
- [ ] Set up monitoring for NIM services
- [ ] Configure backup for model storage
- [ ] Update ConfigMaps with production settings
- [ ] Set up autoscaling policies
- [ ] Configure network policies if needed

## References

- Configuration: `nim-retrieval-deployment.yaml`, `nim-llama-deployment.yaml`
- Deployment script: `deploy-all.sh` (lines 216-273)
- Storage: PVCs created in `deploy_storage()` function
- Build scripts: `build-and-push.sh` (includes NIM build functions)

