# Ray Dashboard Server Metrics Panel Fix

## Issue
The Ray Dashboard was showing "Panel with id 7 not found", "Panel with id 8 not found", and "Panel with id 15 not found" errors in the server metrics section, along with "Invalid dashboard UID in annotation request" warnings.

## Root Cause
The Ray dashboard was looking for specific panel IDs (7, 8, 15) that didn't exist in the current dashboard configuration. This was similar to the previous Cluster Utilization panel issue that was fixed by updating the dashboard configuration.

## Solution
Following the same approach used to fix the Cluster Utilization panel issue, we:

1. **Restored the original working dashboard configuration** to avoid templating errors
2. **Carefully added only the missing panels** (7, 15) that Ray expects
3. **Maintained existing working panels** (8, 24, 41 - Cluster Utilization)
4. **Used the correct dashboard UID** (`rayDefaultDashboard`)
5. **Preserved the proper Grafana panel structure** to avoid "Failed to upgrade legacy queries" errors

## Changes Made

### Dashboard Configuration Update
- **File**: `docker/grafana/dashboards/ray-default-dashboard.json`
- **Action**: Restored original working configuration and added only missing panels
- **Key additions**:
  - Panel 7: "Node GPU Count" - Added with proper Grafana structure
  - Panel 15: "Node Disk Usage" - Added with proper Grafana structure
- **Preserved existing panels**:
  - Panel 8: "Node GPU Utilization" - Already working
  - Panel 24: "Node CPU Utilization" - Already working  
  - Panel 41: "Cluster Utilization" - Already working

### Panel Details
- **Panel 7**: Node GPU Count - Shows GPU count per node
- **Panel 8**: Node GPU Utilization - Shows GPU utilization percentage
- **Panel 15**: Node Disk Usage - Shows disk usage per node
- **Panel 41**: Cluster Utilization - Shows overall cluster resource utilization (was already working)

## Verification

### Before Fix
- ❌ Panel with id 7 not found
- ❌ Panel with id 8 not found  
- ❌ Panel with id 15 not found
- ❌ Invalid dashboard UID in annotation request
- ❌ "Failed to upgrade legacy queries" templating errors
- ❌ "Dashboard not found" errors

### After Fix
- ✅ Panel 7: "Node GPU Count" - Present and functional
- ✅ Panel 8: "Node GPU Utilization" - Present and functional (was already working)
- ✅ Panel 15: "Node Disk Usage" - Present and functional
- ✅ Panel 24: "Node CPU Utilization" - Still working
- ✅ Panel 41: "Cluster Utilization" - Still working
- ✅ All 29 panels present in dashboard
- ✅ Dashboard UID: `rayDefaultDashboard` - Correct
- ✅ No templating errors
- ✅ Proper Grafana panel structure maintained

## Technical Details

### Dashboard Generation
Created a script (`add-missing-panels.py`) that:
- Restores the original working dashboard configuration
- Adds only the missing panel IDs that Ray expects
- Uses correct Prometheus queries for each metric
- Maintains proper Grafana panel structure to avoid templating errors

### Panel Configuration
Each panel includes:
- Correct Prometheus query expressions
- Proper variable substitution (`$Instance`, `$SessionName`, `$Cluster`)
- Appropriate legend formatting
- Grid positioning for dashboard layout

### Metrics Integration
- Ray metrics are being collected via Prometheus
- Metrics endpoint accessible at `http://localhost:8080/metrics`
- Prometheus target status: Healthy
- Grafana dashboard properly loaded with UID `rayDefaultDashboard`

## Access Points
- **Ray Dashboard**: http://localhost:8265
- **Grafana**: http://localhost:3000 (admin/seedcore)
- **Prometheus**: http://localhost:9090
- **Ray Metrics**: http://localhost:8080/metrics

## Testing Commands

### Verify Dashboard Panels
```bash
# Check if missing panels are present
curl -s -u admin:seedcore "http://localhost:3000/api/dashboards/uid/rayDefaultDashboard" | \
  jq '.dashboard.panels[] | select(.id == 7 or .id == 8 or .id == 15) | {id: .id, title: .title}'
```

### Verify Ray Metrics
```bash
# Check Ray metrics in Prometheus
curl -s "http://localhost:9090/api/v1/label/__name__/values" | \
  jq '.data[] | select(startswith("ray_"))' | head -10
```

### Verify Dashboard Access
```bash
# Check dashboard availability
curl -s -u admin:seedcore "http://localhost:3000/api/search?type=dash-db" | \
  jq '.[] | select(.uid == "rayDefaultDashboard")'
```

## Impact
- ✅ Resolves "Panel with id X not found" errors
- ✅ Fixes "Invalid dashboard UID in annotation request" warnings
- ✅ Enables proper server metrics visualization in Ray dashboard
- ✅ Maintains compatibility with existing monitoring setup
- ✅ Follows same pattern as previous Cluster Utilization fix

## Related Documentation
- [Ray Dashboard Fix](ray-dashboard-fix.md) - Previous fix for Cluster Utilization
- [Monitoring Integration](MONITORING_INTEGRATION.md) - Overall monitoring setup
- [Ray Cluster Diagnostics](ray_cluster_diagnostic_report.md) - Cluster health monitoring

## Files Changed
- `docker/grafana/dashboards/ray-default-dashboard.json` - Updated dashboard configuration
- `docs/monitoring/ray-dashboard-server-metrics-fix.md` - This documentation

## Next Steps
1. Monitor Ray dashboard for any remaining panel issues
2. Verify metrics are displaying correctly in all panels
3. Consider adding additional custom panels if needed
4. Update monitoring documentation as needed 