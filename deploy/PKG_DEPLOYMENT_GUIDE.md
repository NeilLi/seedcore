# PKG and HGNN Deployment Guide

## 🎯 Overview

This guide covers deploying SeedCore with **PKG (Policy Knowledge Graph)** and **HGNN (Hypergraph Neural Network)** routing enabled.

## ✅ What's Been Fixed

### 1. PKG WASM Path Configuration
- **Issue**: PKG WASM file path mismatch (`/opt/pkg` vs `/app/opt/pkg`)
- **Fix**: Automated secret update in `setup-ray-serve.sh`
- **Result**: PKG loads successfully on coordinator startup

### 2. OCPS-Based HGNN Routing
- **Issue**: OCPS parameters not properly used for Surprise Score calculation
- **Fix**: Coordinator correctly extracts `params.ocps` and calculates x2
- **Result**: Natural S > 0.6 threshold crossing without force flags

### 3. Verification Script Updates
- **Added**: OCPS method test (now default)
- **Added**: PKG status verification
- **Fixed**: Proto-plan validation (handles empty plans)

---

## 🚀 Quick Start

### Deploy Everything (Fresh Installation)

```bash
cd /home/ubuntu/project/seedcore/deploy
./deploy-seedcore.sh
```

This will:
1. Build Docker image
2. Create Kind cluster
3. Deploy databases (PostgreSQL, MySQL, Redis, Neo4j)
4. Deploy Ray with **automatic PKG setup**
5. Bootstrap organisms and dispatchers
6. Deploy SeedCore API

### Update PKG WASM Only (Existing Deployment)

```bash
# With dummy WASM (testing)
./update-pkg-wasm.sh

# With real WASM binary
./update-pkg-wasm.sh /path/to/policy_rules.wasm
```

---

## 📋 Deployment Steps (Manual)

### Step 1: Update Environment Configuration

Ensure your `/home/ubuntu/project/seedcore/docker/.env` includes:

```bash
# PKG Configuration
COORDINATOR_PKG_ENABLED=1
PKG_WASM_PATH=/app/opt/pkg/policy_rules.wasm
PKG_SNAPSHOT_VERSION=rules@1.3.0+ontology@0.9.1
PKG_EVAL_TIMEOUT_MS=10

# Surprise Score Thresholds
SURPRISE_TAU_FAST=0.35
SURPRISE_TAU_PLAN=0.60
```

### Step 2: Deploy Ray Services

```bash
cd /home/ubuntu/project/seedcore/deploy
./setup-ray-serve.sh
```

The script will automatically:
- Update secret with correct `PKG_WASM_PATH=/app/opt/pkg/policy_rules.wasm`
- Create dummy PKG WASM file at `/app/opt/pkg/policy_rules.wasm` in Ray head pod
- Verify WASM file exists

### Step 3: Verify PKG Status

```bash
# Port-forward to Ray Serve
kubectl -n seedcore-dev port-forward svc/seedcore-svc-serve-svc 8000:8000 &

# Check PKG status
curl http://localhost:8000/pipeline/health | jq .pkg
```

**Expected Output:**
```json
{
  "enabled": true,
  "loaded": true,
  "version": "rules@1.3.0+ontology@0.9.1",
  "path": "/app/opt/pkg/policy_rules.wasm",
  "size_bytes": 140,
  "error": null
}
```

### Step 4: Test HGNN Routing

```bash
# Test with OCPS data (natural S > 0.6)
curl -X POST http://127.0.0.1:8002/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "type": "general_query",
    "description": "High drift anomaly requiring decomposition",
    "params": {
      "ocps": {
        "S_t": 1.0,
        "h": 1.0,
        "h_clr": 0.5,
        "flag_on": true
      },
      "kappa": 0.7,
      "criticality": 0.7
    },
    "drift_score": 0.8,
    "run_immediately": true
  }'
```

**Expected Result:**
- Decision: `hgnn`
- Surprise Score S: ~0.61 (> 0.6)
- OCPS mapping: `ocps` (not `minmax_fallback`)

---

## 🔧 Scripts Reference

### `setup-ray-serve.sh`

Main Ray deployment script with PKG support.

**Features:**
- Automatically configures `PKG_WASM_PATH` in secret
- Creates dummy WASM file for testing
- Verifies file existence after deployment

**Usage:**
```bash
./setup-ray-serve.sh
```

**Environment Variables:**
- `NAMESPACE` - Kubernetes namespace (default: seedcore-dev)
- `RAY_IMAGE` - Docker image (default: seedcore:latest)
- `ENV_FILE_PATH` - Path to .env file (default: ../docker/.env)

### `update-pkg-wasm.sh`

Helper script to update PKG WASM in running deployment.

**Features:**
- Updates secret with correct path
- Uploads real WASM or creates dummy
- Restarts Ray head pod to reload
- Verifies PKG loads successfully

**Usage:**
```bash
# Create/update with dummy WASM
./update-pkg-wasm.sh

# Update with real WASM binary
./update-pkg-wasm.sh /path/to/policy_rules.wasm
```

**What it does:**
1. Finds Ray head pod
2. Updates `PKG_WASM_PATH` in secret
3. Copies WASM file or creates dummy
4. Restarts head pod
5. Waits for coordinator to be ready
6. Verifies PKG status via health endpoint

---

## 🧪 Testing & Verification

### Run Complete Verification

```bash
cd /home/ubuntu/project/seedcore
python scripts/host/verify_seedcore_architecture.py
```

The script will test:
1. ✅ Ray cluster connectivity
2. ✅ Serve deployments
3. ✅ Fast-path routing
4. ✅ **HGNN routing with natural S > 0.6**
5. ✅ **PKG status**
6. ✅ Domain-specific eventizer tags

### Verification with OCPS Method (Default)

```bash
# Uses OCPS data to push S above 0.6 naturally
python scripts/host/verify_seedcore_architecture.py
```

### Verification with Force Flag Method

```bash
# Uses force_hgnn=True flag instead
export USE_OCPS_METHOD=false
python scripts/host/verify_seedcore_architecture.py
```

---

## 📊 Expected Results

### HGNN Routing Test

```
✅ HGNN routing confirmed (decision='hgnn')
✅ Surprise score S=0.610 > tau_plan=0.6 (natural threshold)
✅ HGNN routing confirmed with empty proto_plan
   Proto-plan provenance: ['fallback:router_rules@1.0']
   (Empty proto_plan is expected when no domain-specific tags are present)
```

### PKG Status

```json
{
  "enabled": true,
  "loaded": true,
  "version": "rules@1.3.0+ontology@0.9.1",
  "path": "/app/opt/pkg/policy_rules.wasm",
  "size_bytes": 140,
  "error": null
}
```

### Task Result with OCPS

```sql
decision     | "hgnn"
S            | 0.610
ocps_mapping | "ocps"  -- Not "minmax_fallback"!
x_values     | [0.5, 1.0, 0.5, 0.5, 0.5, 0.6]
proto_plan   | {"tasks": [], "edges": [], "provenance": ["fallback:router_rules@1.0"]}
```

---

## 🔍 Troubleshooting

### PKG Not Loading

**Symptom:**
```json
{"pkg": {"enabled": true, "loaded": false, "error": "file_not_found"}}
```

**Solutions:**

1. **Check WASM file exists:**
```bash
HEAD_POD=$(kubectl -n seedcore-dev get pods -l ray.io/node-type=head --no-headers | awk '{print $1}')
kubectl exec -n seedcore-dev ${HEAD_POD} -- ls -lh /app/opt/pkg/policy_rules.wasm
```

2. **Check environment variable:**
```bash
kubectl exec -n seedcore-dev ${HEAD_POD} -- env | grep PKG_WASM_PATH
# Should output: PKG_WASM_PATH=/app/opt/pkg/policy_rules.wasm
```

3. **Update and restart:**
```bash
./update-pkg-wasm.sh
```

### OCPS Not Used (S Always 0.5)

**Symptom:**
```json
{"ocps": {"mapping": "minmax_fallback"}}
```

**Check:**
1. Task params include OCPS data:
```bash
kubectl exec -n seedcore-dev postgresql-xxx -- psql -U postgres -d seedcore \
  -c "SELECT params->'ocps' FROM tasks WHERE id='<task-id>';"
```

2. Coordinator logs show OCPS extraction:
```bash
kubectl logs -n seedcore-dev ${HEAD_POD} | grep -i ocps
```

### Proto-Plan Always Empty

**Expected Behavior:**
- Empty proto_plan is **normal** when no domain-specific tags are detected
- Proto-plan gets populated when FastEventizer detects domain tags:
  - `vip`, `privacy` → VIP guest handling
  - `hvac_fault` → HVAC diagnostics
  - `allergen` → Food safety protocols
  - `luggage_custody` → Baggage tracking

**To get populated proto-plan:**
```bash
curl -X POST http://127.0.0.1:8002/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "type": "general_query",
    "description": "VIP guest reports room temperature too high, needs immediate assistance",
    "params": {
      "ocps": {"S_t": 1.0, "h": 1.0, "h_clr": 0.5, "flag_on": true},
      "kappa": 0.9,
      "criticality": 0.9
    },
    "run_immediately": true
  }'
```

---

## 🎯 Production Deployment

### Replace Dummy WASM with Real Binary

1. **Build or obtain real PKG WASM:**
```bash
# Example: compile policy rules to WASM
# (Your build process here)
```

2. **Upload to deployment:**
```bash
./update-pkg-wasm.sh /path/to/policy_rules.wasm
```

3. **Verify:**
```bash
curl http://localhost:8000/pipeline/health | jq .pkg
```

### Mount WASM via ConfigMap (Recommended for Production)

1. **Create ConfigMap:**
```bash
kubectl create configmap pkg-wasm \
  --from-file=policy_rules.wasm=/path/to/policy_rules.wasm \
  -n seedcore-dev
```

2. **Update `rayservice.yaml`:**
```yaml
spec:
  rayClusterConfig:
    headGroupSpec:
      template:
        spec:
          volumes:
          - name: pkg-wasm
            configMap:
              name: pkg-wasm
          containers:
          - name: ray-head
            volumeMounts:
            - name: pkg-wasm
              mountPath: /app/opt/pkg
              readOnly: true
```

3. **Redeploy:**
```bash
kubectl apply -f deploy/rayservice.yaml
```

---

## 📚 Architecture Summary

### OCPS Flow

```
1. Task created with params.ocps = {S_t: 1.0, h: 1.0, h_clr: 0.5, flag_on: true}
2. tasks_router.py stores in DB: params = {ocps: {...}, ...}
3. _task_worker reads from DB, sends to coordinator: payload = {params: {...}}
4. Coordinator extracts: ocps = params.get("ocps")
5. SurpriseComputer._x2_ocps(ocps): x2 = (S_t - h_clr)/(h - h_clr) = 1.0
6. Surprise Score: S = 0.25*0.5 + 0.20*1.0 + ... = 0.61 > 0.6
7. Decision: "hgnn" (natural threshold crossing)
```

### PKG Flow

```
1. Coordinator.__init__() loads PKG WASM from PKG_WASM_PATH
2. On task route_and_execute(), PKG evaluates tags + signals
3. If PKG succeeds: proto_plan from PKG with provenance ["pkg:rules@1.3.0..."]
4. If PKG fails/timeout: fallback to router rules with provenance ["fallback:router_rules@1.0"]
5. Result includes PKG metadata: {used: bool, error: str|null, version: str}
```

---

## ✅ Deployment Checklist

- [ ] `.env` file configured with PKG variables
- [ ] `setup-ray-serve.sh` run successfully
- [ ] PKG WASM file created/uploaded
- [ ] Health endpoint shows `pkg.loaded: true`
- [ ] Test task with OCPS data returns S > 0.6
- [ ] Test task shows decision: "hgnn"
- [ ] Verification script passes all tests
- [ ] Domain-specific tags trigger proto-plan population

---

## 📞 Support

For issues or questions:
1. Check coordinator logs: `kubectl logs -n seedcore-dev <head-pod>`
2. Check health endpoint: `curl http://localhost:8000/pipeline/health`
3. Run verification: `python scripts/host/verify_seedcore_architecture.py`
4. Review this guide's troubleshooting section

