#!/usr/bin/env python3
"""
Ray Dashboard Configuration Script

This script configures Ray Dashboard to integrate with Prometheus and Grafana
for enhanced monitoring capabilities.
"""

import os
import json
import subprocess
import time

def setup_ray_dashboard():
    """Configure Ray Dashboard with monitoring integration."""
    
    # Set environment variables for Ray Dashboard
    os.environ['RAY_DASHBOARD_PROMETHEUS_HOST'] = 'prometheus'
    os.environ['RAY_DASHBOARD_PROMETHEUS_PORT'] = '9090'
    os.environ['RAY_DASHBOARD_GRAFANA_HOST'] = 'grafana'
    os.environ['RAY_DASHBOARD_GRAFANA_PORT'] = '3000'
    
    # Create dashboard configuration
    dashboard_config = {
        "dashboard": {
            "prometheus": {
                "host": "prometheus",
                "port": 9090,
                "enabled": True
            },
            "grafana": {
                "host": "grafana", 
                "port": 3000,
                "enabled": True
            },
            "metrics": {
                "enabled": True,
                "export_interval": 30
            }
        }
    }
    
    # Write configuration to file
    config_path = "/etc/ray/dashboard-config.json"
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, 'w') as f:
        json.dump(dashboard_config, f, indent=2)
    
    print(f"✅ Ray Dashboard configuration written to {config_path}")
    print(f"📊 Prometheus: prometheus:9090")
    print(f"📈 Grafana: grafana:3000")
    
    return config_path

if __name__ == "__main__":
    setup_ray_dashboard() 