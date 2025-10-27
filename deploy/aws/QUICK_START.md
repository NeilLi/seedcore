# Quick Start Guide - Deploy SeedCore to AWS EKS

## ✅ Current Status

- ✅ EKS Cluster: `agentic-ai-cluster` (Kubernetes 1.33.5)
- ✅ KubeRay Operator: Installed and running in `kuberay-system` namespace
- ✅ AWS Credentials: Configured
- ✅ Build Script: Fixed with `--platform linux/amd64` flag

---

## 🚀 Next Steps

### 1. Build and Push Docker Image

Your image is built for **linux/amd64** platform (✅ correct for AWS):

```bash
# From your Mac (already done if you ran ./build.sh)
cd /Users/ningli/project/seedcore
./build.sh  # This now includes --platform linux/amd64

# Push to ECR
# First, set your ECR registry (check .env.aws for ECR_REGISTRY)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <your-ecr-registry>

docker tag seedcore:latest <your-ecr-registry>/seedcore:latest
docker push <your-ecr-registry>/seedcore:latest
```

### 2. Deploy Databases (Optional)

```bash
cd deploy/aws

# Source environment
source .env.aws

# Deploy databases
envsubst < database-deployment.yaml | kubectl apply -f -
```

### 3. Deploy RayService

```bash
cd deploy/aws

# Source environment
source .env.aws

# Deploy RayService (requires KubeRay - ✅ already installed!)
envsubst < rayservice-deployment.yaml | kubectl apply -f -

# Check status
kubectl get rayservice -n ${NAMESPACE}
kubectl get pods -n ${NAMESPACE}
```

### 4. Deploy SeedCore API

```bash
cd deploy/aws

# Source environment
source .env.aws

# Deploy API
envsubst < seedcore-deployment.yaml | kubectl apply -f -

# Check status
kubectl get deployment seedcore-api -n ${NAMESPACE}
kubectl get pods -n ${NAMESPACE}
```

### 5. Access Services

```bash
# Get service endpoints
kubectl get svc -n ${NAMESPACE}

# For LoadBalancer services, get external IP
kubectl get svc seedcore-svc -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# Port-forward for testing (if needed)
kubectl port-forward -n ${NAMESPACE} svc/seedcore-svc 8000:8000
```

---

## 📋 Verification Commands

```bash
# Check KubeRay operator
kubectl get pods -n kuberay-system

# Check RayService
kubectl get rayservice -n ${NAMESPACE}

# Check all pods
kubectl get pods -n ${NAMESPACE}

# Check logs
kubectl logs -f deployment/seedcore-api -n ${NAMESPACE}

# Check Ray logs
kubectl logs -f -n ${NAMESPACE} -l ray.io/node-type=head
```

---

## 🐛 Troubleshooting

### Image Pull Errors

```bash
# Check if image exists in ECR
aws ecr describe-images --repository-name seedcore --region us-east-1

# Verify image is linux/amd64
docker inspect <your-ecr-registry>/seedcore:latest | grep Architecture
# Should show: "Architecture": "amd64"
```

### KubeRay Issues

```bash
# Check KubeRay operator logs
kubectl logs -f -n kuberay-system -l app.kubernetes.io/name=kuberay-operator

# Restart KubeRay operator if needed
kubectl delete pod -n kuberay-system -l app.kubernetes.io/name=kuberay-operator
```

### RayService Not Starting

```bash
# Check RayService status
kubectl get rayservice -n ${NAMESPACE} -o yaml

# Check Ray pod events
kubectl describe pod -n ${NAMESPACE} -l ray.io/node-type=head

# Check Ray logs
kubectl logs -f -n ${NAMESPACE} -l ray.io/node-type=head
```

---

## 📝 Environment Variables

Make sure these are set in `.env.aws`:

```bash
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=570667384381
CLUSTER_NAME=agentic-ai-cluster
NAMESPACE=seedcore  # or your preferred namespace
ECR_REGISTRY=<your-ecr-registry>
ECR_REPO=seedcore
SEEDCORE_IMAGE_TAG=latest
RAY_VERSION=2.33.0
```

---

## 🎉 Success Criteria

When everything is working, you should see:

```bash
$ kubectl get pods -n ${NAMESPACE}
NAME                               READY   STATUS    RESTARTS   AGE
seedcore-api-xxxxx                 1/1     Running   0          5m
seedcore-svc-head-xxxxx            1/1     Running   0          5m
seedcore-svc-worker-xxxxx          1/1     Running   0          5m

$ kubectl get rayservice -n ${NAMESPACE}
NAME           DESIRED   AVAILABLE   STATUS    AGE
seedcore-svc   1         1           Healthy  5m
```

---

## 🔗 Useful Links

- Your cluster: `agentic-ai-cluster` in `us-east-1`
- KubeRay docs: https://ray.io
- EKS docs: https://docs.aws.amazon.com/eks/

