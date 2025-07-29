fix: resolve 404 errors in Ray dashboard Grafana iframes

## Problem
Ray dashboard was showing "404: Not Found" errors in the Overview and 
Cluster status panels, which embed Grafana dashboards for metrics visualization.

## Root Cause
Inconsistent Grafana URL configuration between docker-compose.yml and 
ray-workers.yml files:
- Main compose file used ${PUBLIC_GRAFANA_URL} environment variable
- Ray workers file had hardcoded IP address
- PUBLIC_GRAFANA_URL environment variable was not defined

## Solution
1. **Standardized configuration**: Updated ray-workers.yml to use the same 
   environment variable pattern as main docker-compose.yml
2. **Environment variable setup**: Added PUBLIC_GRAFANA_URL to env.example 
   with proper documentation
3. **Setup automation**: Created setup-grafana-url.sh script to automatically 
   detect and configure the public IP for Grafana iframe access
4. **Security**: Removed hardcoded IP addresses from version control

## Changes Made
- docker/ray-workers.yml: Use ${PUBLIC_GRAFANA_URL:-http://localhost:3000}
- env.example: Added PUBLIC_GRAFANA_URL configuration section
- docker/setup-grafana-url.sh: New script for automated Grafana URL setup
- .env: Configured with local IP (not committed to version control)

## Testing
- ✅ Ray dashboard accessible at :8265
- ✅ Grafana accessible at :3000  
- ✅ All services running (1 head + 3 workers)
- ✅ Configuration consistent across all Ray components

## Usage
For local development: No action needed (uses localhost:3000)
For production: Run `docker/setup-grafana-url.sh` to auto-configure public IP
Manual setup: Set PUBLIC_GRAFANA_URL in .env file

Fixes: Ray dashboard 404 errors in Grafana metric panels 