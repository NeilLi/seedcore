# Ray Dashboard Monitoring Integration Fix

## Issue
The Ray Dashboard shows: "Time-series charts are hidden because either Prometheus or Grafana server is not detected."

## Root Cause
Ray Dashboard 2.48.0 requires specific configuration to detect Prometheus and Grafana services.

## Solution

### Option 1: Manual Configuration (Recommended)
Since Ray Dashboard doesn't automatically detect our Prometheus and Grafana services, we need to manually configure the integration:

1. **Access Ray Dashboard**: http://YOUR_VM_IP:8265
2. **Go to Settings**: Click the gear icon in the top right
3. **Configure Monitoring**:
   - **Prometheus URL**: `http://prometheus:9090`
   - **Grafana URL**: `http://grafana:3000`
   - **Enable Metrics**: Check the box

### Option 2: Environment Variables
The following environment variables are set in the Ray containers:
- `RAY_DASHBOARD_PROMETHEUS_HOST=prometheus`
- `RAY_DASHBOARD_PROMETHEUS_PORT=9090`
- `RAY_DASHBOARD_GRAFANA_HOST=grafana`
- `RAY_DASHBOARD_GRAFANA_PORT=3000`

### Option 3: Direct Access
You can access the monitoring services directly:

- **Prometheus**: http://YOUR_VM_IP:9090
- **Grafana**: http://YOUR_VM_IP:3000 (admin/seedcore)
- **Ray Dashboard**: http://YOUR_VM_IP:8265

## Verification

### Check Prometheus Targets
```bash
curl http://YOUR_VM_IP:9090/api/v1/targets
```

### Check Grafana Health
```bash
curl http://YOUR_VM_IP:3000/api/health
```

### Check Ray Dashboard
```bash
curl http://YOUR_VM_IP:8265/api/version
```

## Alternative Solution
If the manual configuration doesn't work, you can use the standalone monitoring stack:

1. **Use Prometheus directly**: http://YOUR_VM_IP:9090
2. **Use Grafana directly**: http://YOUR_VM_IP:3000
3. **Configure Grafana to use Prometheus as data source**

This provides the same monitoring capabilities without relying on Ray Dashboard's built-in integration. 