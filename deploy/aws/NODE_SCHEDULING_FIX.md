# Node Scheduling Fix - Quick Reference

## 🎯 The Problem

Your Kubernetes pods are stuck in `Pending` state because:

- **Nodes are labeled:** `node-type=gpu`
- **Pods require:** `node-type=general`
- **Result:** No nodes match the selector → pods can't schedule

## ✅ Quick Fix (Option 1 - Recommended)

The simplest solution: **add the `node-type=general` label to your GPU nodes**.

### Run this command:

```bash
cd deploy/aws
chmod +x quick-fix-nodes.sh
./quick-fix-nodes.sh
```

### Or manually:

```bash
# Label your node
kubectl label node ip-172-31-32-90.ec2.internal node-type=general --overwrite

# Verify
kubectl get nodes --show-labels | grep node-type

# Watch your pods
kubectl get pods -n seedcore-dev -w
```

This allows your node to accept **both** `node-type=gpu` and `node-type=general` pods, solving the scheduling issue immediately.

---

## 🔄 Alternative Fix (Option 2)

If you want to keep roles separate (GPU vs general compute):

### Remove nodeSelector from databases:

```bash
chmod +x fix-remove-nodeselector.sh
./fix-remove-nodeselector.sh
```

### Or manually:

```bash
# Remove nodeSelector from each service
for svc in postgresql mysql neo4j redis; do
  kubectl -n seedcore-dev patch deployment $svc \
    --type=json \
    -p='[{"op":"remove","path":"/spec/template/spec/nodeSelector"}]'
done
```

Then later, create a separate node group for general workloads:

```bash
eksctl create nodegroup --cluster agentic-ai-cluster \
  --name general-nodes \
  --region us-east-1 \
  --node-type t3.large \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 4 \
  --node-labels node-type=general
```

---

## 📋 Available Scripts

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `quick-fix-nodes.sh` | Adds `node-type=general` label to all nodes | **Start here** - fastest fix |
| `fix-node-labels.sh` | Interactive version with checks and PVC re-apply | When you want validation and control |
| `fix-remove-nodeselector.sh` | Removes nodeSelector from deployments | When you want separate node pools |

---

## 🔍 Verification

After applying the fix, check:

```bash
# 1. Verify node labels
kubectl get nodes --show-labels | grep node-type

# 2. Check pod status
kubectl get pods -n seedcore-dev

# 3. Describe any pending pods
kubectl describe pod <pod-name> -n seedcore-dev

# 4. Watch for scheduling
kubectl get pods -n seedcore-dev -w
```

Expected result: Pods should move from `Pending → ContainerCreating → Running`

---

## 🎯 Recommended Action

For a **production cluster**, I recommend:

1. **Short-term:** Run `./quick-fix-nodes.sh` to fix scheduling immediately
2. **Long-term:** Create separate node groups with proper labels:
   - GPU nodes: `node-type=gpu`
   - General nodes: `node-type=general`
   
Then update your deployments to use appropriate nodeSelectors or keep them flexible for both.

---

## 🐛 Troubleshooting

### Pods still pending?

```bash
# Check events
kubectl get events -n seedcore-dev --sort-by='.lastTimestamp'

# Check PVC status
kubectl get pvc -n seedcore-dev

# Check if storage class is default
kubectl get storageclass
```

### Storage issues?

```bash
# Make sure gp2 storage class exists
kubectl get storageclass gp2

# Set it as default if needed
kubectl patch storageclass gp2 \
  -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```

---

## 📝 Notes

- Option 1 is **reversible** - you can remove labels later if needed
- Both options work, choose based on your long-term architecture plans
- Option 1 is faster and easier for immediate deployment
- Option 2 requires creating additional infrastructure (new node groups)

