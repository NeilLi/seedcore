"""Coordinator package: core logic split from coordinator_service.

This package provides the core coordinator functionality, including:
- Task routing and execution logic
- Utility functions for task normalization and processing
- Data access objects for persistence
- API models for coordinator endpoints

Modules:
- dao.py: DAOs for telemetry, outbox, and proto plan persistence
- models.py: Pydantic models for API requests/responses
- utils.py: Utility functions for task normalization, redaction, and data processing
- core/: Submodules for routing, policies, plan, and execution (execute.py contains route_and_execute)

Public API:
- Models: AnomalyTriageRequest, AnomalyTriageResponse, TuneCallbackRequest
- DAOs: TaskRouterTelemetryDAO, TaskOutboxDAO, TaskProtoPlanDAO
- Utils: Common utility functions for task processing (see utils.py)
"""

# Import commonly used models for convenience
from .models import (
    AnomalyTriageRequest,
    AnomalyTriageResponse,
    TuneCallbackRequest,
)

# Import DAOs for convenience
from .dao import (
    TaskRouterTelemetryDAO,
    TaskOutboxDAO,
    TaskProtoPlanDAO,
)

# Import utility constants and commonly used functions
from .utils import (
    MAX_STRING_LENGTH,
    DEFAULT_RECURSION_DEPTH,
    normalize_task_dict,
    convert_task_to_dict,
    extract_proto_plan,
    extract_decision,
    extract_from_nested,
    canonicalize_identifier,
    sync_task_identity,
)

__all__ = [
    # Models
    "AnomalyTriageRequest",
    "AnomalyTriageResponse",
    "TuneCallbackRequest",
    # DAOs
    "TaskRouterTelemetryDAO",
    "TaskOutboxDAO",
    "TaskProtoPlanDAO",
    # Constants
    "MAX_STRING_LENGTH",
    "DEFAULT_RECURSION_DEPTH",
    # Utility functions
    "normalize_task_dict",
    "convert_task_to_dict",
    "extract_proto_plan",
    "extract_decision",
    "extract_from_nested",
    "canonicalize_identifier",
    "sync_task_identity",
]
