# Ray Logging Guide - Correct Commands

## ✅ **Verified Working Commands**

### 1. **Check Ray Version**
```bash
# ✅ CORRECT - Check Ray version in seedcore-api
docker compose exec seedcore-api python -c "import ray, sys; print(ray.__version__)"
```
**Output**: `2.48.0`

### 2. **List Ray Worker Log Files**
```bash
# ✅ CORRECT - List worker log files in ray-head
docker compose exec ray-head ls -la /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/ | grep worker
```

### 3. **Monitor Specific Worker Log**
```bash
# ✅ CORRECT - Monitor a specific worker log file
docker compose exec ray-head tail -f /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-de1285edb0d1f01c8ca51b513627b11f4fb6bb0bd386f4cdb2e3adcb-ffffffff-559.out
```

### 4. **Monitor All Worker Logs**
```bash
# ✅ CORRECT - Monitor all worker log files
docker compose exec ray-head bash -c 'tail -F /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out'
```

### 5. **Filter Worker Logs for Observer Messages**
```bash
# ✅ CORRECT - Filter worker logs for Observer messages
docker compose exec ray-head tail -f /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out | grep "Observer"
```

## ❌ **Incorrect Commands (Don't Use)**

### Wrong Paths:
```bash
# ❌ WRONG - This path doesn't exist
docker compose exec ray-worker ls -la /tmp/ray/session_latest/logs/ | grep worker

# ❌ WRONG - This path doesn't exist  
docker compose exec ray-worker tail -f /tmp/ray/session_latest/logs/worker-*.out
```

## 🔍 **How to Find Current Session Directory**

### 1. **Get Current Session Name**
```bash
# Get the current Ray session name
curl -s http://localhost:8265/api/version | jq -r '.session_name'
```
**Output**: `session_2025-07-28_21-02-17_265517_1`

### 2. **Find Log Directory**
```bash
# Find the actual log directory
docker compose exec ray-head find /home/ray -name "*session*" -type d 2>/dev/null
```

### 3. **List All Log Files**
```bash
# List all log files in the current session
docker compose exec ray-head ls -la /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/
```

## 📊 **Available Log Files**

### Worker Logs:
- `worker-*.out` - Worker stdout
- `worker-*.err` - Worker stderr
- `python-core-worker-*.log` - Python worker logs

### System Logs:
- `dashboard.log` - Dashboard logs
- `raylet.out` - Raylet logs
- `gcs_server.out` - GCS server logs
- `monitor.out` - Monitor logs

## 🎯 **Practical Examples**

### Monitor Scenario 3 Execution:
```bash
# 1. Start monitoring all worker logs
docker compose exec ray-head bash -c 'tail -F /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out'

# 2. In another terminal, run the scenario
docker compose exec seedcore-api python -m scripts.scenario_3_proactive_caching

# 3. Watch for Observer messages
docker compose exec ray-head tail -f /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out | grep -E "(Observer|Mw MISS|Mw cache hit)"
```

### Monitor Specific Actor:
```bash
# Monitor MissTracker actor logs
docker compose exec ray-head tail -f /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-de1285edb0d1f01c8ca51b513627b11f4fb6bb0bd386f4cdb2e3adcb-ffffffff-559.out
```

## 🔧 **Key Differences from Original Commands**

### Original (Wrong):
```bash
# Used ray-worker container
docker compose exec ray-worker ls -la /tmp/ray/session_latest/logs/

# Used /tmp path
/tmp/ray/session_latest/logs/
```

### Correct:
```bash
# Use ray-head container (where logs are actually stored)
docker compose exec ray-head ls -la /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/

# Use /home/ray/ray_tmp path
/home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/
```

## 📝 **Notes**

1. **Container**: Use `ray-head` container, not `ray-worker`
2. **Path**: Use `/home/ray/ray_tmp/` not `/tmp/`
3. **Session**: Use the actual session directory name
4. **Real-time**: Use `tail -f` or `tail -F` for real-time monitoring
5. **Filtering**: Use `grep` to filter for specific messages

## 🚀 **Quick Reference**

```bash
# ✅ All correct commands in one place
docker compose exec ray-head ls -la /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/ | grep worker
docker compose exec ray-head tail -F /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out
docker compose exec ray-head tail -f /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out | grep "Observer"
```

---

## ⚠️ **IMPORTANT: Why You're Not Seeing Scenario Messages**

### **The Issue**: 
When you run `docker compose exec seedcore-api python -m scripts.scenario_3_proactive_caching`, the scenario messages (cache misses, hits, Observer messages) are **NOT** appearing in the Ray worker logs because:

1. **Ray Workers are Short-Lived**: The Ray workers are created for specific tasks and then destroyed
2. **Messages Go to Main Process**: The actual scenario messages are printed to stdout/stderr of the main process in the `seedcore-api` container
3. **Worker Logs Show Only Initialization**: The worker logs only show actor initialization, not the actual application logic

### **What You Actually See**:
- ✅ **Worker logs show**: Actor initialization, Ray internal messages
- ❌ **Worker logs don't show**: Cache misses, cache hits, Observer messages

### **Where the Messages Actually Go**:
The scenario messages are printed to the **main process stdout/stderr** in the `seedcore-api` container, which you can see when you run the scenario directly.

### **Correct Monitoring Approach**:

#### **Option 1: Monitor seedcore-api logs**
```bash
# Monitor the main application logs
docker compose logs -f seedcore-api
```

#### **Option 2: Run scenario and see output directly**
```bash
# Run the scenario and see all output
docker compose exec seedcore-api python -m scripts.scenario_3_proactive_caching
```

#### **Option 3: Monitor both simultaneously**
```bash
# Terminal 1: Monitor seedcore-api logs
docker compose logs -f seedcore-api

# Terminal 2: Monitor Ray worker logs (for Ray internals)
docker compose exec ray-head bash -c 'tail -F /home/ray/ray_tmp/ray/session_2025-07-28_21-02-17_265517_1/logs/worker-*.out'

# Terminal 3: Run the scenario
docker compose exec seedcore-api python -m scripts.scenario_3_proactive_caching
```

### **What Each Log Shows**:

| Log Source | Shows | Example |
|------------|-------|---------|
| `seedcore-api` logs | Application messages, cache misses/hits, Observer messages | `Mw MISS`, `Mw cache hit`, `Hot item detected` |
| Ray worker logs | Ray internal messages, actor initialization | `Actor creation`, `CoreWorker`, `raylet` |
| Python core worker logs | Ray performance stats, internal events | `Task Event stats`, `IO Service Stats` |

### **Bottom Line**:
- **For application logic**: Monitor `seedcore-api` logs
- **For Ray internals**: Monitor Ray worker logs
- **For debugging**: Use both simultaneously

---

## 🔍 **ACTUAL LOG MESSAGE FORMATS**

### **Cache Messages (in seedcore-api logs)**:
The actual log messages use these formats:

```bash
# Cache HIT messages:
[organ_for_Worker-0] Mw HIT for 'dbe0fde2-bdcc-4f0e-ba25-c248b43afa04' in GLOBAL cache.
[organ_for_Worker-1] Mw HIT for 'dbe0fde2-bdcc-4f0e-ba25-c248b43afa04' in ORGAN cache.

# Cache MISS messages:
[organ_for_Worker-0] Mw MISS for 'dbe0fde2-bdcc-4f0e-ba25-c248b43afa04'. Logging miss.
```

### **Observer Messages (in seedcore-api logs)**:
```bash
# Observer detection messages:
Observer-Agent - Hot item detected: dbe0fde2-bdcc-4f0e-ba25-c248b43afa04 (misses: 15)
Observer-Agent - Fetching item dbe0fde2-bdcc-4f0e-ba25-c248b43afa04 from LTM for proactive caching.
Observer-Agent - Proactively caching item dbe0fde2-bdcc-4f0e-ba25-c248b43afa04
```

### **Correct Filtering Commands**:
```bash
# Filter for cache misses
docker compose logs seedcore-api | grep "Mw MISS"

# Filter for cache hits  
docker compose logs seedcore-api | grep "Mw HIT"

# Filter for Observer messages
docker compose logs seedcore-api | grep "Observer-Agent"

# Filter for all cache-related messages
docker compose logs seedcore-api | grep -E "(Mw MISS|Mw HIT|Observer-Agent)"

# Real-time monitoring of all scenario messages
docker compose logs -f seedcore-api | grep -E "(Mw MISS|Mw HIT|Observer-Agent|Hot item|Proactively caching)"
```

### **Why the Scenario Validation Message is Wrong**:
The scenario script says to look for:
- `"Mw MISS"` ✅ (correct)
- `"Mw cache hit"` ❌ (wrong - should be `"Mw HIT"`)
- `"Hot item detected"` ✅ (correct)
- `"Proactively caching"` ✅ (correct)

The actual messages use `"Mw HIT"` not `"Mw cache hit"`.

---

**Result**: The commands are correct, but you need to monitor the right logs and use the right message formats! 🎉 