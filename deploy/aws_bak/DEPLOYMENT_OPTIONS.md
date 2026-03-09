# AWS Deployment Options for SeedCore

## Summary

You have **two deployment paths**:

### Option 1: Deploy SeedCore API Only (No KubeRay Required) ✅ RECOMMENDED

This is the **simplest approach** that works with your existing Docker image:

1. **What it does:** Deploys only the SeedCore API as a regular Kubernetes Deployment
2. **No KubeRay needed:** Uses standard Kubernetes Deployments
3. **Your image works:** Uses the `seedcore:latest` image you built on macOS with `--platform linux/amd64`

**To deploy:**
```bash
# 1. Set up AWS environment
source deploy/aws/.env.aws

# 2. Build and push your image (from your Mac)
cd /Users/ningli/project/seedcore
docker build --platform linux/amd64 -f docker/Dockerfile -t seedcore:latest .
docker tag seedcore:latest ${ECR_REGISTRY}/seedcore:latest
docker push ${ECR_REGISTRY}/seedcore:latest

# 3. Update kubeconfig
aws eks update-kubeconfig --region us-east-1 --name agentic-ai-cluster

# 4. Deploy SeedCore API (no KubeRay needed)
kubectl apply -f deploy/aws/seedcore-deployment.yaml
```

**Skip these installation steps** in aws-init.sh:
- ❌ KubeRay operator (not needed for SeedCore API)
- ✅ Database services (deploy as needed)
- ✅ AWS Load Balancer Controller (recommended)

---

### Option 2: Deploy Full Ray Services (Requires KubeRay)

This deploys the full SeedCore Ray service with distributed execution:

1. **What it does:** Deploys RayService with all Ray applications
2. **Requires KubeRay:** Needs KubeRay operator installed first
3. **More complex:** Requires KubeRay CRDs and operator

**To deploy:**
```bash
# 1. Install KubeRay operator manually (ONE TIME ONLY)
kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/v1.4.2/helm-chart/kuberay-operator/crds/base/crd.yaml
kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/v1.4.2/helm-chart/kuberay-operator/templates/manager.yaml

# 2. Wait for operator to be ready
kubectl wait --for=condition=available --timeout=300s deployment/kuberay-operator -n kuberay-system

# 3. Deploy Ray service
kubectl apply -f deploy/aws/rayservice-deployment.yaml
```

---

## Your Current Situation

✅ **You have:**
- Built Docker image with `--platform linux/amd64` flag
- EKS cluster: `agentic-ai-cluster` running Kubernetes 1.33.5
- AWS credentials configured
- Kubectl configured

❌ **You're missing:**
- KubeRay operator (only needed for Option 2)

---

## Recommendation

**Start with Option 1** (SeedCore API deployment) because:
1. No KubeRay installation needed
2. Simpler to debug
3. Your Docker image works perfectly
4. You can always add Ray services later

Once Option 1 is working, you can:
- Test the API endpoints
- Verify database connectivity
- Monitor pod health
- Then optionally add KubeRay for full Ray services

---

## Quick Start (Option 1)

```bash
# Navigate to project
cd /Users/ningli/project/seedcore

# Load AWS credentials from .env.aws (create this file from env.aws.example)
source deploy/aws/.env.aws

# OR export AWS credentials directly:
# export AWS_ACCESS_KEY_ID=<your-key>
# export AWS_SECRET_ACCESS_KEY=<your-secret>
# export AWS_SESSION_TOKEN=<your-token>  # Only for temporary credentials
export AWS_REGION=us-east-1
export CLUSTER_NAME=agentic-ai-cluster

# Update kubeconfig
aws eks update-kubeconfig --region us-east-1 --name agentic-ai-cluster

# Create namespace
kubectl create namespace seedcore

# Deploy SeedCore API
envsubst < deploy/aws/seedcore-deployment.yaml | kubectl apply -f -

# Check status
kubectl get pods -n seedcore
kubectl logs -f deployment/seedcore-api -n seedcore
```

---

## Troubleshooting

### Image pull issues:
```bash
# Check if image exists in ECR
aws ecr describe-images --repository-name seedcore --region us-east-1

# Re-tag and push if needed
docker tag seedcore:latest ${ECR_REGISTRY}/seedcore:latest
docker push ${ECR_REGISTRY}/seedcore:latest
```

### Build for AWS:
```bash
# Build with correct platform
docker build --platform linux/amd64 -f docker/Dockerfile -t seedcore:latest .
```

---

## Next Steps

1. **Deploy with Option 1** (no KubeRay)
2. **Test the API** endpoints
3. **Check logs** for any issues
4. **Add databases** if needed (postgres, neo4j, redis)
5. **Optionally add KubeRay** later for Ray services

---

## File Reference

- `seedcore-deployment.yaml` → Regular K8s Deployment (Option 1)
- `rayservice-deployment.yaml` → RayService (Option 2, needs KubeRay)
- `build.sh` → Build script with `--platform linux/amd64`
- `deploy/aws/build-and-push.sh` → Push to ECR

Your build.sh now has the correct `--platform linux/amd64` flag! 🎉

