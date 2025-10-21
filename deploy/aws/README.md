# SeedCore AWS EKS Deployment Guide

This directory contains all the necessary configuration files and scripts to deploy SeedCore to Amazon EKS (Elastic Kubernetes Service).

## 🏗️ Architecture Overview

The AWS deployment includes:

- **EKS Cluster**: Managed Kubernetes cluster with auto-scaling node groups
- **SeedCore API**: Main REST API service
- **Ray Service**: Distributed computing cluster with Ray Serve
- **NIM Services**: Retrieval and Llama model services
- **Databases**: PostgreSQL, MySQL, Neo4j, and Redis
- **Ingress**: AWS Application Load Balancer with SSL termination
- **Storage**: EBS volumes for persistent data

## 📁 Directory Structure

```
deploy/aws/
├── README.md                           # This file
├── env.aws.example                     # Environment configuration template
├── eks-cluster.yaml                    # EKS cluster configuration
├── nodegroup.yaml                      # Node group configurations
├── rbac.yaml                          # RBAC and service account configuration
├── database-deployment.yaml            # Database services
├── rayservice-deployment.yaml          # Ray cluster and serve configuration
├── seedcore-deployment.yaml            # Main SeedCore API service
├── nim-retrieval-deployment.yaml       # NIM retrieval service
├── nim-llama-deployment.yaml           # NIM Llama service
├── ingress.yaml                        # Ingress and load balancer configuration
├── aws-init.sh                        # AWS initialization script
├── build-and-push.sh                  # Docker image build and push script
└── deploy-all.sh                      # Main deployment script
```

## 🚀 Quick Start

### Prerequisites

1. **AWS CLI** - [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
2. **eksctl** - [Installation Guide](https://eksctl.io/introduction/installation/)
3. **kubectl** - [Installation Guide](https://kubernetes.io/docs/tasks/tools/)
4. **Docker** - [Installation Guide](https://docs.docker.com/get-docker/)
5. **envsubst** - Usually included with `gettext` package

### 1. Configure Environment

```bash
# Copy the environment template
cp env.aws.example .env.aws

# Edit the configuration
nano .env.aws
```

**Required Configuration:**
- `AWS_REGION`: Your preferred AWS region (e.g., `us-east-1`)
- `AWS_ACCOUNT_ID`: Your AWS account ID
- `CLUSTER_NAME`: Name for your EKS cluster
- `NAMESPACE`: Kubernetes namespace (e.g., `seedcore-prod`)
- `INGRESS_HOST`: Your domain name for the ingress

### 2. Initialize AWS Infrastructure

```bash
# Run the initialization script
./aws-init.sh
```

This script will:
- Check prerequisites
- Configure AWS CLI
- Create ECR repositories
- Create EKS cluster
- Install required operators (KubeRay, ALB Controller, cert-manager)
- Set up kubectl configuration

### 3. Create Environment Resources

```bash
# Create ConfigMaps and Secrets from env.example
./create-env-resources.sh
```

This script will:
- Parse `/Users/ningli/project/seedcore/docker/env.example`
- Create `seedcore-env` ConfigMap with non-sensitive configuration
- Create `seedcore-env-secret` Secret with sensitive data (passwords, API keys)
- Create `seedcore-client-env` ConfigMap with AWS-specific service URLs

### 4. Build and Push Docker Images

```bash
# Build and push all images to ECR
./build-and-push.sh
```

This script will:
- Build SeedCore Docker image
- Build NIM service images (with placeholders)
- Push all images to ECR

### 5. Deploy SeedCore

```bash
# Deploy all services
./deploy-all.sh
```

This script will:
- Deploy RBAC configuration
- Deploy persistent storage (PVCs)
- Create environment resources from env.example
- Deploy database services
- Initialize databases
- Deploy Ray service
- Bootstrap components (organism + dispatchers)
- Deploy SeedCore API
- Deploy NIM services
- Deploy ingress configuration

## 🔧 Configuration Details

### Bootstrap Components

The AWS deployment includes dedicated bootstrap scripts that match the original `deploy-seedcore.sh` structure:

**Bootstrap Scripts:**
- `bootstrap_organism.sh` - Initializes the organism service
- `bootstrap_dispatchers.sh` - Sets up dispatchers and graph dispatchers

**Key Features:**
- **AWS-Optimized**: Uses ECR images and proper service discovery
- **Environment Integration**: Loads configuration from `.env.aws`
- **Job Management**: Creates and manages Kubernetes Jobs
- **Error Handling**: Comprehensive logging and timeout handling
- **Resource Management**: Proper CPU and memory limits

**Manual Bootstrap Execution:**
```bash
# Deploy organism bootstrap only
./bootstrap_organism.sh

# Deploy dispatchers bootstrap only
./bootstrap_dispatchers.sh

# Deploy both (via main deployment)
./deploy-all.sh
```

### Environment Variable Handling

The AWS deployment automatically processes the `docker/env.example` file to create Kubernetes resources:

**ConfigMaps Created:**
- `seedcore-env`: Non-sensitive configuration from env.example
- `seedcore-client-env`: AWS-specific service URLs and configuration

**Secrets Created:**
- `seedcore-env-secret`: Sensitive data (passwords, API keys) from env.example

**Key Features:**
- Automatically filters sensitive vs non-sensitive variables
- Converts Docker service names to Kubernetes service URLs
- Uses AWS-specific passwords from `.env.aws`
- Handles placeholder values appropriately

**Manual Environment Resource Management:**
```bash
# Create environment resources manually
./create-env-resources.sh create

# Delete environment resources
./create-env-resources.sh delete

# Show help
./create-env-resources.sh help
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region for deployment | `us-east-1` |
| `AWS_ACCOUNT_ID` | Your AWS account ID | Required |
| `CLUSTER_NAME` | EKS cluster name | `seedcore-eks-cluster` |
| `NAMESPACE` | Kubernetes namespace | `seedcore-prod` |
| `ECR_REPO` | ECR repository for SeedCore | Auto-generated |
| `NODE_INSTANCE_TYPE` | EC2 instance type for nodes | `t3.large` |
| `MIN_NODES` | Minimum number of nodes | `2` |
| `MAX_NODES` | Maximum number of nodes | `10` |
| `DESIRED_NODES` | Desired number of nodes | `3` |
| `STORAGE_CLASS` | EBS storage class | `gp3` |
| `STORAGE_SIZE` | Default storage size | `20Gi` |

### EKS Cluster Configuration

The cluster is configured with:
- **VPC**: Custom VPC with public and private subnets
- **Node Groups**: 
  - General purpose nodes (CPU-optimized)
  - GPU nodes (for ML workloads)
  - Spot instances (for cost optimization)
- **Add-ons**: VPC CNI, CoreDNS, kube-proxy, EBS CSI driver
- **Logging**: CloudWatch cluster logging enabled

### Service Configuration

#### SeedCore API
- **Replicas**: 2 (configurable)
- **Resources**: 2 CPU, 4Gi memory
- **Health Checks**: Readiness, startup, and liveness probes
- **Load Balancer**: Network Load Balancer

#### Ray Service
- **Head Node**: 4 CPU, 16Gi memory
- **Worker Nodes**: 4 CPU, 16Gi memory each
- **GPU Workers**: 1 GPU per node
- **Ray Version**: 2.33.0

#### NIM Services
- **Retrieval Service**: 2 replicas, 4 CPU, 8Gi memory
- **Llama Service**: 1 replica, 4 CPU, 16Gi memory, 1 GPU

#### Databases
- **PostgreSQL**: 1 replica, 1 CPU, 2Gi memory
- **MySQL**: 1 replica, 1 CPU, 2Gi memory
- **Neo4j**: 1 replica, 1 CPU, 4Gi memory
- **Redis**: 1 replica, 0.5 CPU, 1Gi memory

## 🌐 Accessing Services

### Service URLs

After deployment, services will be available at:

- **SeedCore API**: `http://<load-balancer-url>/api`
- **Ray Serve**: `http://<load-balancer-url>/ml`
- **Cognitive Service**: `http://<load-balancer-url>/cognitive`
- **Pipeline Service**: `http://<load-balancer-url>/pipeline`
- **Ops Service**: `http://<load-balancer-url>/ops`
- **Organism Service**: `http://<load-balancer-url>/organism`
- **NIM Retrieval**: `http://<load-balancer-url>/nim/retrieval`
- **NIM Llama**: `http://<load-balancer-url>/nim/llama`

### Health Checks

- **API Health**: `http://<load-balancer-url>/health`
- **API Readiness**: `http://<load-balancer-url>/readyz`

### Ray Dashboard

- **Dashboard**: `http://<load-balancer-url>/ray-dashboard`

## 🔍 Monitoring and Debugging

### Check Deployment Status

```bash
# Show all resources
./deploy-all.sh status

# Check pods
kubectl get pods -n $NAMESPACE

# Check services
kubectl get services -n $NAMESPACE

# Check ingress
kubectl get ingress -n $NAMESPACE
```

### View Logs

```bash
# SeedCore API logs
kubectl logs -f deployment/seedcore-api -n $NAMESPACE

# Ray head logs
kubectl logs -f deployment/seedcore-svc-head -n $NAMESPACE

# Database logs
kubectl logs -f deployment/postgresql -n $NAMESPACE
```

### Access Pods

```bash
# Access SeedCore API pod
kubectl exec -it deployment/seedcore-api -n $NAMESPACE -- /bin/bash

# Access Ray head pod
kubectl exec -it deployment/seedcore-svc-head -n $NAMESPACE -- /bin/bash
```

## 🛠️ Maintenance

### Scaling Services

```bash
# Scale SeedCore API
kubectl scale deployment seedcore-api --replicas=3 -n $NAMESPACE

# Scale Ray workers
kubectl scale deployment seedcore-svc-worker --replicas=5 -n $NAMESPACE
```

### Updating Images

```bash
# Update image tag in .env.aws
export SEEDCORE_IMAGE_TAG=v2.0.0

# Rebuild and push
./build-and-push.sh

# Update deployment
kubectl set image deployment/seedcore-api seedcore-api=$ECR_REPO:$SEEDCORE_IMAGE_TAG -n $NAMESPACE
```

### Backup and Restore

```bash
# Backup PVCs
kubectl get pvc -n $NAMESPACE -o yaml > pvc-backup.yaml

# Restore PVCs
kubectl apply -f pvc-backup.yaml
```

## 🧹 Cleanup

### Remove All Resources

```bash
# Clean up all deployed resources
./deploy-all.sh cleanup

# Delete EKS cluster
eksctl delete cluster --name $CLUSTER_NAME --region $AWS_REGION

# Delete ECR repositories
aws ecr delete-repository --repository-name seedcore --force --region $AWS_REGION
aws ecr delete-repository --repository-name nim-retrieval --force --region $AWS_REGION
aws ecr delete-repository --repository-name nim-llama --force --region $AWS_REGION
```

## 🔒 Security Considerations

### IAM Roles and Policies

The deployment creates the following IAM resources:
- **EKS Cluster Role**: For the EKS service
- **Node Group Role**: For EC2 instances
- **Service Account Role**: For SeedCore pods
- **ALB Controller Role**: For load balancer management

### Network Security

- **VPC**: Isolated network with public/private subnets
- **Security Groups**: Restrictive inbound/outbound rules
- **Network Policies**: Kubernetes network policies for pod-to-pod communication
- **WAF**: Optional Web Application Firewall integration

### Data Encryption

- **EBS Volumes**: Encrypted at rest
- **EKS Secrets**: Encrypted using AWS KMS
- **TLS**: SSL/TLS termination at the load balancer

## 📊 Cost Optimization

### Spot Instances

The deployment includes spot instance node groups for cost optimization:
- **Spot Nodes**: For non-critical workloads
- **On-Demand Nodes**: For critical services
- **Mixed Strategy**: Automatic failover between spot and on-demand

### Resource Management

- **Horizontal Pod Autoscaler**: Automatic scaling based on metrics
- **Cluster Autoscaler**: Automatic node scaling
- **Resource Requests/Limits**: Proper resource allocation

### Monitoring Costs

```bash
# Check resource usage
kubectl top nodes
kubectl top pods -n $NAMESPACE

# Check storage usage
kubectl get pvc -n $NAMESPACE
```

## 🆘 Troubleshooting

### Common Issues

#### Pod Not Starting
```bash
# Check pod events
kubectl describe pod <pod-name> -n $NAMESPACE

# Check pod logs
kubectl logs <pod-name> -n $NAMESPACE
```

#### Service Not Accessible
```bash
# Check service endpoints
kubectl get endpoints -n $NAMESPACE

# Check ingress status
kubectl describe ingress seedcore-ingress -n $NAMESPACE
```

#### Database Connection Issues
```bash
# Check database pods
kubectl get pods -l app=postgresql -n $NAMESPACE

# Test database connection
kubectl exec -it deployment/postgresql -n $NAMESPACE -- psql -U postgres -d seedcore
```

### Debug Commands

```bash
# Check cluster events
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp'

# Check resource quotas
kubectl describe resourcequota -n $NAMESPACE

# Check persistent volumes
kubectl get pv
kubectl get pvc -n $NAMESPACE
```

## 📚 Additional Resources

- [EKS User Guide](https://docs.aws.amazon.com/eks/latest/userguide/)
- [KubeRay Documentation](https://ray-project.github.io/kuberay/)
- [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

## 🤝 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review the logs for error messages
3. Check AWS CloudWatch logs
4. Open an issue in the repository

---

**Note**: This deployment is designed for production use with proper security, monitoring, and scaling configurations. Make sure to review and customize the configuration according to your specific requirements.
