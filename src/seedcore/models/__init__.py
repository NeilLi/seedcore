"""
Database models for SeedCore.

This module provides SQLAlchemy models for tasks and facts.
All imports are safe and don't trigger runtime dependencies.
"""
import logging

try:
    from .task import Task as DatabaseTask, TaskStatus, Base as TaskBase
    from .fact import Fact, Base as FactBase
    from .governance_audit import GovernedExecutionAudit
    from .source_registration import (
        SourceRegistration,
        SourceRegistrationArtifact,
        SourceRegistrationMeasurement,
        SourceRegistrationStatus,
        RegistrationDecision,
        RegistrationDecisionStatus,
        TrackingEvent,
        TrackingEventType,
        TrackingEventSourceKind,
    )
except ImportError as e:
    logging.getLogger(__name__).debug(f"Skipping SQLAlchemy model imports in thin environment: {e}")

from .action_intent import (
    ActionIntent,
    ExecutionToken,
    PolicyCase,
    PolicyCaseAssessment,
    PolicyDecision,
    TwinSnapshot,
)
from .evidence_bundle import EvidenceBundle, ExecutionReceipt
from .task_api import Task
from .task_payload import TaskPayload

# Try to build __all__ dynamically to support both full and thin envs
__all__ = [
    "ActionIntent",
    "ExecutionToken",
    "PolicyCase",
    "PolicyCaseAssessment",
    "PolicyDecision",
    "TwinSnapshot",
    "EvidenceBundle",
    "ExecutionReceipt",
    "Task",
    "TaskPayload",
]
try:
    __all__.extend([
        "DatabaseTask",
        "TaskStatus",
        "TaskBase",
        "Fact",
        "FactBase",
        "GovernedExecutionAudit",
        "SourceRegistration",
        "SourceRegistrationArtifact",
        "SourceRegistrationMeasurement",
        "SourceRegistrationStatus",
        "RegistrationDecision",
        "RegistrationDecisionStatus",
        "TrackingEvent",
        "TrackingEventType",
        "TrackingEventSourceKind",
    ])
except NameError:
    pass
