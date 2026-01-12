"""
Services Package

This package contains standalone microservices that can be deployed independently
via Ray Serve. Each service has a clear responsibility and well-defined interfaces.

Services:
- state_service: Collects and aggregates system state from distributed components
- energy_service: Computes energy metrics from unified state data
- eventizer_service: Deterministic text processing for task classification and routing
"""

from .eventizer_service import EventizerService
from .fact_service import FactManagerService
from seedcore.ops.eventizer.fact_dao import FactDAO

# Optional import - eventizer_features may not exist in all deployments
try:
    from seedcore.ops.eventizer.eventizer_features import features_from_payload
    __all__ = [
        "EventizerService",
        "FactManagerService",
        "FactDAO",
        "features_from_payload",
    ]
except ImportError:
    # eventizer_features not available (e.g., in test environments)
    __all__ = [
        "EventizerService",
        "FactManagerService",
        "FactDAO",
    ]

