"""
Services Package

This package contains standalone microservices that can be deployed independently
via Ray Serve. Each service has a clear responsibility and well-defined interfaces.

Services:
- state_service: Collects and aggregates system state from distributed components
- energy_service: Computes energy metrics from unified state data
- eventizer_service: Deterministic text processing for task classification and routing
"""



