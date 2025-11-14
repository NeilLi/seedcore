# ML Service Scaling & GPU Placement Reference

**SeedCore ML Platform — Kubernetes + Ray**

This document explains the *correct and production-safe way* to ensure the `ml_service` deployment runs **only on GPU nodes** in a Kubernetes + Ray cluster.

## Table of Contents

1. [Why Previous Configs Failed](#1-why-previous-configs-failed)
2. [How Ray + Kubernetes GPU Scheduling Works](#2-how-ray--kubernetes-gpu-scheduling-works)
3. [Minimal Changes Needed](#3-minimal-changes-needed)
4. [Full RayCluster GPU Worker Example](#4-full-recommended-raycluster-gpu-worker-example)
5. [Final Ray Serve Deployment Block](#5-final-ray-serve-deployment-block)

---

## 1. Why Previous Configs Failed

### The Temporary Development Config

During development, the following configuration was used:

```yaml
ray_actor_options:
  num_cpus: 0.4
  num_gpus: 0
  memory: 2147483648
  resources: {"head_node": 0.001}
```

### ❌ Problem 1: `num_gpus: 0`

Setting `num_gpus: 0` **forbids Ray from placing the actor onto any GPU node**. Ray's scheduler interprets this as an explicit requirement that the actor should not use GPUs, which prevents it from being scheduled on GPU-enabled nodes.

### ❌ Problem 2: Custom `"head_node"` Resource

Using a custom `"head_node"` resource constraint forces the actor to run on the Ray head node, which typically:
- Lacks GPU resources
- Should be reserved for coordination tasks
- Creates a bottleneck for ML workloads
- Prevents horizontal scaling across worker nodes

This approach is not suitable for production ML workloads that require GPU acceleration.

---

## 2. How Ray + Kubernetes GPU Scheduling Works

Ray will schedule an actor on a GPU node **only if**:

1. **The actor requests GPUs**: The actor sets `num_gpus: 1` (or higher) in its `ray_actor_options`.
2. **The actor requests a custom Ray resource**: The actor requests a custom **Ray resource** that exists only on GPU nodes (e.g., `gpu_worker: 0.001`).
3. **Kubernetes node selection**: The pod is scheduled by Kubernetes using `nodeSelector` or `tolerations` to target GPU nodes.

### The Cleanest and Most Scalable Approach

The recommended approach combines Kubernetes node selection with Ray resource constraints:

1. **Create a Ray resource that only GPU workers have** - This allows Ray to make intelligent placement decisions.
2. **Make MLService request that resource** - This ensures the service is scheduled on GPU nodes.

This approach keeps scheduling logic inside Ray instead of forcing Kubernetes to handle all placement decisions, which provides better integration with Ray's autoscaling and resource management.

---

## 3. Minimal Changes Needed

Follow these three steps to pin MLService to GPU nodes:

### Step 1: Label Your GPU Node

First, label the GPU nodes in your Kubernetes cluster:

```bash
kubectl label node <gpu-node-name> gpu-node=true
```

You can verify the label was applied:

```bash
kubectl get nodes --show-labels | grep gpu-node
```

### Step 2: Add a Ray Resource to the GPU Worker Group

In your `RayCluster.yaml`, add a custom Ray resource to the GPU worker group:

```yaml
workerGroupSpecs:
  - groupName: gpu-workers
    replicas: 1
    rayStartParams:
      resources: "{\"gpu_worker\": 1}"
    template:
      spec:
        nodeSelector:
          gpu-node: "true"
```

**What this does:**

- Only GPU nodes get the `gpu_worker` Ray resource
- Ray can now use that resource for placement decisions
- Kubernetes ensures the worker pod runs on a GPU node via `nodeSelector`

### Step 3: Update MLService to Request `gpu_worker`

Update your Ray Serve deployment block to request the `gpu_worker` resource:

```yaml
- name: ml_service
  import_path: entrypoints.ml_entrypoint:build_ml_service
  route_prefix: /ml
  deployments:
    - name: MLService
      num_replicas: 1
      ray_actor_options:
        num_cpus: 0.4
        num_gpus: 1
        memory: 2147483648
        resources:
          gpu_worker: 0.001
```

**Key points:**

- ✔ `num_gpus: 1` ensures GPU usage and proper GPU device allocation
- ✔ `gpu_worker: 0.001` forces scheduling on the GPU worker node
- ✔ Fractional resource allows multiple small actors to coexist on the same GPU node

---

## 4. Full (Recommended) RayCluster GPU Worker Example

Here's a complete RayCluster configuration that includes GPU worker setup:

```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: seedcore-ray
spec:
  headGroupSpec:
    template:
      spec:
        containers:
          - name: ray-head
            image: your-image
            resources:
              limits:
                cpu: "2"
                memory: "4Gi"
  workerGroupSpecs:
    - groupName: gpu-workers
      replicas: 1
      minReplicas: 1
      maxReplicas: 1
      rayStartParams:
        resources: "{\"gpu_worker\": 1}"
      template:
        spec:
          nodeSelector:
            gpu-node: "true"
          tolerations:
            - key: "nvidia.com/gpu"
              operator: "Exists"
          containers:
            - name: ray-worker
              image: your-image
              resources:
                limits:
                  nvidia.com/gpu: 1
                requests:
                  nvidia.com/gpu: 1
```

### What This Configuration Ensures

- **Kubernetes scheduling**: GPU workers are scheduled ONLY on GPU nodes via `nodeSelector`
- **GPU resource allocation**: Kubernetes allocates GPU devices via `nvidia.com/gpu` resource requests/limits
- **Ray resource exposure**: Ray exposes a `gpu_worker` resource only on those nodes
- **MLService placement**: MLService requests that resource → forced GPU placement
- **Tolerations**: Allows scheduling on nodes with GPU taints (if your cluster uses them)

---

## 5. Final Ray Serve Deployment Block

Here's the complete Ray Serve deployment configuration ready to use:

```yaml
- name: ml_service
  import_path: entrypoints.ml_entrypoint:build_ml_service
  route_prefix: /ml
  deployments:
    - name: MLService
      num_replicas: 1
      ray_actor_options:
        num_cpus: 0.4
        num_gpus: 1
        memory: 2147483648
        resources:
          gpu_worker: 0.001
```

### Configuration Notes

- **`num_replicas: 1`**: Start with a single replica; scale horizontally by increasing this value
- **`num_cpus: 0.4`**: Allocates fractional CPU resources (adjust based on your workload)
- **`num_gpus: 1`**: Ensures one GPU device is allocated per replica
- **`memory: 2147483648`**: Sets memory limit to 2GB (adjust based on model size)
- **`gpu_worker: 0.001`**: Fractional resource request ensures placement on GPU nodes

---

## 🎉 Expected Results

After implementing these changes, your MLService will:

- ✔ Run **only** on GPU-enabled Ray worker pods
- ✔ Never run on CPU nodes or the head node
- ✔ Support multiple GPU workers for horizontal scaling
- ✔ Integrate cleanly with Ray autoscaling and Ray Serve deployment
- ✔ Properly utilize GPU resources for ML inference and training

---

## Additional Resources

If you need help with:

- **Multi-tier cluster design** (CPU → inference, GPU → training)
- **Autoscaler configuration** for burst GPU training windows
- **L2 Distiller → XGBoost GPU training pipeline** integration

Please refer to the main SeedCore documentation or contact the platform team.
