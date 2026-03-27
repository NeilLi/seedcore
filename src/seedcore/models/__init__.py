"""
Database models for SeedCore.

This module provides SQLAlchemy models for tasks and facts.
All imports are safe and don't trigger runtime dependencies.
"""
import logging

try:
    from .task import Task as DatabaseTask, TaskStatus, Base as TaskBase
    from .fact import Fact, Base as FactBase
    from .asset_custody import AssetCustodyState
    from .custody_graph import (
        CustodyDisputeCase,
        CustodyDisputeEvent,
        CustodyGraphEdge,
        CustodyGraphNode,
        CustodyTransitionEvent,
    )
    from .digital_twin import DigitalTwinEventJournal, DigitalTwinHistory, DigitalTwinState
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
    AuthorityLevel,
    DelegatedAuthority,
    DelegationConstraint,
    ExecutionToken,
    OwnerTwin,
    PolicyCase,
    PolicyCaseAssessment,
    PolicyDecision,
    TwinRevisionStage,
    TwinSnapshot,
)
from .evidence_bundle import (
    AttestationProof,
    EvidenceBundle,
    HALCaptureEnvelope,
    KeyBindingProof,
    PolicyReceipt,
    ReplayProof,
    TransitionReceipt,
    TransparencyProof,
    TrustBundle,
    TrustBundleKey,
    TrustBundleTransparencyConfig,
    TrustProof,
)
from .replay import (
    PublicTrustReference,
    ReplayProjectionKind,
    ReplayRecord,
    ReplayTimelineEvent,
    ReplayVerificationStatus,
    TrustCertificate,
    TrustPageProjection,
    VerificationResult,
)
from .task_api import Task
from .task_payload import TaskPayload

# Try to build __all__ dynamically to support both full and thin envs
__all__ = [
    "ActionIntent",
    "AuthorityLevel",
    "DelegatedAuthority",
    "DelegationConstraint",
    "ExecutionToken",
    "OwnerTwin",
    "PolicyCase",
    "PolicyCaseAssessment",
    "PolicyDecision",
    "TwinRevisionStage",
    "TwinSnapshot",
    "EvidenceBundle",
    "HALCaptureEnvelope",
    "KeyBindingProof",
    "PolicyReceipt",
    "PublicTrustReference",
    "ReplayProof",
    "ReplayProjectionKind",
    "ReplayRecord",
    "ReplayTimelineEvent",
    "ReplayVerificationStatus",
    "TransparencyProof",
    "TrustCertificate",
    "TrustBundle",
    "TrustBundleKey",
    "TrustBundleTransparencyConfig",
    "TrustProof",
    "TrustPageProjection",
    "TransitionReceipt",
    "Task",
    "TaskPayload",
    "VerificationResult",
    "AttestationProof",
]
try:
    __all__.extend([
        "DatabaseTask",
        "TaskStatus",
        "TaskBase",
        "Fact",
        "FactBase",
        "AssetCustodyState",
        "CustodyGraphNode",
        "CustodyGraphEdge",
        "CustodyTransitionEvent",
        "CustodyDisputeCase",
        "CustodyDisputeEvent",
        "DigitalTwinState",
        "DigitalTwinHistory",
        "DigitalTwinEventJournal",
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
