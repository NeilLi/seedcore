# SeedCore Documentation

Welcome to the SeedCore documentation! This directory contains comprehensive documentation organized for maximum efficiency and ease of use.

## 📚 Documentation Structure

### 🚀 [Guides](./guides/) - User and Developer Guides
- **[Getting Started](./guides/getting-started/)** - Quick start guides and tutorials
  - [XGBoost Quickstart](./guides/getting-started/xgboost_quickstart.md)
  - [Quick Reference](./guides/getting-started/QUICK_REFERENCE.md)
  - [Next Steps](./guides/getting-started/NEXT_STEPS.md)
- **[Hyperparameter Tuning](./guides/hyperparameter-tuning/)** - ✅ **NEW** - Automated ML model optimization
  - [Hyperparameter Tuning Guide](./guides/hyperparameter-tuning/HYPERPARAMETER_TUNING_GUIDE.md)
  - [Quick Reference](./guides/hyperparameter-tuning/QUICK_REFERENCE.md)
- **[Deployment](./guides/deployment/)** - Deployment and infrastructure guides
  - [Docker Setup Guide](./guides/deployment/docker-setup-guide.md)
  - [Ray Workers Guide](./guides/deployment/ray-workers-guide.md)
- **[Troubleshooting](./guides/troubleshooting/)** - Common issues and solutions
  - [Ray Serve Troubleshooting](./guides/troubleshooting/ray_serve_troubleshooting.md)
  - [Service Dependencies](./guides/troubleshooting/service-dependencies-and-restart-behavior.md)
- **[Best Practices](./guides/best-practices/)** - Best practices and recommendations
  - [Ray Serve Pattern](./guides/best-practices/RAY_SERVE_PATTERN.md)
  - [Optimization Summary](./guides/best-practices/OPTIMIZATION_SUMMARY.md)

### 🔌 [API](./api/) - API Documentation
- **[Reference](./api/reference/)** - API reference documentation
  - [XGBoost Daily Reference](./api/reference/xgboost_daily_reference.md)
- **[Examples](./api/examples/)** - API usage examples
  - [XGBoost Integration](./api/examples/xgboost_integration.md)
  - [XGBoost COA Integration](./api/examples/xgboost_coa_integration.md)
- **[Schemas](./api/schemas/)** - Data schemas and models

### 🏗️ [Architecture](./architecture/) - System Architecture
- **[Overview](./architecture/overview/)** - High-level architecture
  - [Main Index](./architecture/overview/MAIN_INDEX.md)
  - [Index](./architecture/overview/INDEX.md)
- **[Components](./architecture/components/)** - Component documentation
  - [Reports](./architecture/components/reports/)
  - [Energy Model](./architecture/components/energy-model/)
- **[Decisions](./architecture/decisions/)** - Architecture decision records
  - [Commit Messages](./architecture/decisions/commit-messages/)

### 📊 [Monitoring](./monitoring/) - Monitoring and Observability
- **[Setup](./monitoring/setup/)** - Monitoring setup guides
  - [Monitoring Integration](./monitoring/setup/MONITORING_INTEGRATION.md)
  - [Ray Logging Guide](./monitoring/setup/RAY_LOGGING_GUIDE.md)
- **[Dashboards](./monitoring/dashboards/)** - Dashboard documentation
  - [Ray Dashboard Fixes](./monitoring/dashboards/RAY_DASHBOARD_FIXES.md)
- **[Alerts](./monitoring/alerts/)** - Alert configuration

### 🚀 [Releases](./releases/) - Release Documentation
- **[Changelog](./releases/changelog/)** - Release changelogs
- **[Migration](./releases/migration/)** - Migration guides
- **[Notes](./releases/notes/)** - Release notes
  - [Production Readiness 2024-06](./releases/notes/2024-06-production-readiness.md)
  - [Production Readiness 2025-07](./releases/notes/2025-07-production-readiness.md)

### 📜 [Historical](./historical/) - Historical and Archived Docs
- **[Fixes](./historical/fixes/)** - Version-specific fixes
  - [Ray 2.20.0 Fixes](./historical/fixes/)
  - [Ray 2.9 Fixes](./historical/fixes/)
  - [Ray Serve Fixes](./historical/fixes/)
- **[Upgrades](./historical/upgrades/)** - Upgrade documentation
  - [Version Update Summary](./historical/upgrades/VERSION_UPDATE_SUMMARY.md)
- **[Deprecated](./historical/deprecated/)** - Deprecated features

## 🎯 Quick Navigation

### For New Users
1. Start with [XGBoost Quickstart](./guides/getting-started/xgboost_quickstart.md)
2. Review [Quick Reference](./guides/getting-started/QUICK_REFERENCE.md)
3. Try [Hyperparameter Tuning](./guides/hyperparameter-tuning/QUICK_REFERENCE.md) for model optimization
4. Follow [Next Steps](./guides/getting-started/NEXT_STEPS.md)

### For Developers
1. Check [API Reference](./api/reference/) for endpoints
2. Review [Best Practices](./guides/best-practices/) for patterns
3. Use [Troubleshooting](./guides/troubleshooting/) for issues

### For DevOps
1. Follow [Docker Setup Guide](./guides/deployment/docker-setup-guide.md)
2. Configure [Monitoring](./monitoring/setup/)
3. Review [Deployment Guides](./guides/deployment/)

### For Troubleshooting
1. Check [Ray Serve Troubleshooting](./guides/troubleshooting/ray_serve_troubleshooting.md)
2. Review [Service Dependencies](./guides/troubleshooting/service-dependencies-and-restart-behavior.md)
3. Use [Debugging Commands](./guides/troubleshooting/ray_serve_debugging_commands.md)

## 📋 Documentation Standards

### File Naming
- Use lowercase with underscores for file names
- Use descriptive names that indicate content
- Group related files with common prefixes

### Content Structure
- Start with a clear title and overview
- Include practical examples
- Provide step-by-step instructions
- Link to related documentation

### Maintenance
- Keep documentation up to date with code changes
- Archive historical documents in [historical](./historical/)
- Update this README when adding new sections

## 🔗 Related Resources

- [Docker Resources](../docker/README.md) - Docker configuration and deployment
- [Project README](../README.md) - Main project documentation
- [Reorganization Plan](./REORGANIZATION_PLAN.md) - Details about this reorganization

## 🤝 Contributing

When adding new documentation:
1. Place files in the appropriate subdirectory
2. Update this README with new links
3. Follow the existing naming conventions
4. Include practical examples and clear instructions

## 📞 Support

For questions about documentation:
1. Check the [troubleshooting guides](./guides/troubleshooting/)
2. Review [historical fixes](./historical/fixes/) for similar issues
3. Consult the [API reference](./api/reference/) for technical details 