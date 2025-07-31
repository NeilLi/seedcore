# Monitoring & Diagnostics Documentation

This directory contains documentation for monitoring, diagnostics, and analysis tools.

## 📊 Monitoring Tools

- **[ray_cluster_diagnostic_report.md](ray_cluster_diagnostic_report.md)** - Ray cluster diagnostic report
- **[ray-dashboard-fix.md](ray-dashboard-fix.md)** - Ray dashboard fix documentation
- **[ray-cluster-diagnostics.md](ray-cluster-diagnostics.md)** - Ray cluster diagnostic procedures
- **[MONITORING_INTEGRATION.md](MONITORING_INTEGRATION.md)** - Monitoring system integration guide
- **[RAY_LOGGING_GUIDE.md](RAY_LOGGING_GUIDE.md)** - Ray logging and monitoring guide
- **[AGENT_DISTRIBUTION_ANALYSIS.md](AGENT_DISTRIBUTION_ANALYSIS.md)** - Agent distribution analysis guide

## 🔧 Ray Serve Troubleshooting

For Ray Serve troubleshooting and debugging, see the guides directory:

- **[Ray Serve Troubleshooting Guide](../guides/ray_serve_troubleshooting.md)** - Comprehensive troubleshooting guide
- **[Ray Serve Debugging Commands](../guides/ray_serve_debugging_commands.md)** - Quick reference for debugging commands

## 📈 Observability Stack

- **Ray Dashboard**: http://localhost:8265
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000
- **Node Exporter**: http://localhost:9100

## 🚀 Quick Start

1. **Check cluster status**:
   ```bash
   docker ps | grep ray
   ```

2. **View Ray Serve applications**:
   ```bash
   curl -s http://localhost:8265/api/serve/applications/ | jq .
   ```

3. **Test endpoints**:
   ```bash
   curl http://localhost:8000/
   ```

4. **Check logs**:
   ```bash
   docker logs seedcore-ray-head --tail 20
   docker logs seedcore-ray-serve-1 --tail 20
   ```

## 📚 Related Documentation

- **Ray Serve Guides**: See `../guides/` for Ray Serve troubleshooting and debugging
- **Docker Setup**: See `../../docker/README.md` for Docker configuration
- **Ray Serve Pattern**: See `../../docker/RAY_SERVE_PATTERN.md` for deployment patterns
- **API Reference**: See `../api-reference/` for API documentation
- **ML Models**: See `../ml/` for machine learning model documentation 