fix(monitoring): resolve Ray dashboard panel integration issues

## Problem
Ray dashboard was showing "Panel with id 41 not found" and "Panel with id 24 not found" errors due to:
- Ray generates its own dashboard UIDs dynamically (e.g., `rayDefaultDashboard`)
- Custom dashboards had incorrect UIDs (`ray-cluster`, `ray-node`)
- Panel IDs didn't match Ray's expected panel structure
- CORS issues preventing metrics access from browser

## Solution
- Import Ray's auto-generated dashboard instead of creating custom ones
- Use correct UID (`rayDefaultDashboard`) that Ray expects
- Configure CORS-enabled proxies for proper metrics access
- Enable anonymous access for Ray dashboard integration

## Changes Made

### Core Fixes
- **docker/grafana/dashboards/ray-default-dashboard.json**: Import Ray's generated dashboard with correct UID
- **docker/nginx.conf**: CORS-enabled proxy for Ray metrics (port 8081)
- **docker/dashboard-proxy.conf**: Dashboard request interceptor (port 8080)
- **docker/prometheus.yml**: Updated to scrape Ray metrics via proxy

### Configuration Updates
- **docker-compose.yml**: Added Ray metrics and dashboard proxy services
- **docker/grafana/provisioning/**: Configured dashboard provisioning
- **docker/grafana/dashboards/**: Removed custom dashboards, added Ray's generated one

### Documentation Updates
- **docs/MONITORING_INTEGRATION.md**: Added comprehensive Ray integration section
- **docker/README.md**: Updated with monitoring access and troubleshooting

## Technical Details

### Ray Dashboard Integration
- Ray generates dashboard JSON with UID `rayDefaultDashboard` during startup
- Dashboard includes all required panel IDs (41, 24, etc.) that Ray expects
- Anonymous access enabled for seamless integration

### CORS Proxy Architecture
- **ray-metrics-proxy** (port 8081): Handles CORS headers for browser access
- **ray-dashboard-proxy** (port 8080): Intercepts Ray dashboard requests
- **Prometheus**: Scrapes metrics via proxy to avoid CORS issues

### Environment Variables
- `RAY_PROMETHEUS_HOST`: http://prometheus:9090
- `RAY_GRAFANA_HOST`: http://grafana:3000
- `RAY_GRAFANA_IFRAME_HOST`: http://localhost:3000 (not IP)
- `RAY_PROMETHEUS_NAME`: Prometheus

## Testing
- ✅ Ray dashboard accessible at http://localhost:8265
- ✅ Grafana dashboard "Default Dashboard" loaded with correct UID
- ✅ Panel IDs 41 and 24 exist and accessible
- ✅ Anonymous access working for Ray dashboard integration
- ✅ CORS proxy serving metrics correctly
- ✅ Prometheus scraping Ray metrics via proxy

## Access Points
- **Ray Dashboard**: http://localhost:8265
- **Grafana**: http://localhost:3000 (admin/seedcore)
- **Prometheus**: http://localhost:9090
- **Ray Metrics**: http://localhost:8080/metrics (via proxy)

## Files Changed
- docker/grafana/dashboards/ray-default-dashboard.json (new)
- docker/nginx.conf (new)
- docker/dashboard-proxy.conf (new)
- docker/prometheus.yml (modified)
- docker-compose.yml (modified)
- docs/MONITORING_INTEGRATION.md (modified)
- docker/README.md (modified)
- docker/grafana/dashboards/ray-cluster-overview.json (removed)
- docker/grafana/dashboards/ray-node-overview.json (removed)

## Impact
- Resolves Ray dashboard panel integration issues
- Enables proper monitoring of distributed computing resources
- Maintains comprehensive observability stack
- Improves developer experience with working monitoring

Closes: Ray dashboard panel integration issues
Related: Monitoring stack integration, CORS configuration 