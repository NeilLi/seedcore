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
    from .transfer_approval import (
        TransferApprovalEnvelopeRecord,
        TransferApprovalTransitionEventRecord,
    )
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
from .agent_action_gateway import (
    AgentActionApproval,
    AgentActionAsset,
    AgentActionClosureRecordResponse,
    AgentActionClosureRequest,
    AgentActionClosureResponse,
    AgentActionEvaluateRequest,
    AgentActionEvaluateResponse,
    AgentActionOptions,
    AgentActionPrincipal,
    AgentActionRequestRecordResponse,
    AgentActionSecurityContract,
    AgentActionTelemetry,
    AgentActionWorkflow,
    GATEWAY_CONTRACT_VERSION,
    WORKFLOW_TYPE_RCT,
)
from .evidence_bundle import (
    AttestationProof,
    CoSignature,
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
from .pdp_hot_path import (
    HotPathAssetContext,
    HotPathCheckResult,
    HotPathDecisionView,
    HotPathEvaluateRequest,
    HotPathEvaluateResponse,
    HotPathSignerProvenance,
    HotPathTelemetryContext,
)
from .edge_telemetry import (
    EDGE_TELEMETRY_ENVELOPE_VERSION,
    EdgeTelemetryEnvelopeV0,
    EdgeTelemetrySampleV0,
    EdgeTelemetrySignerV0,
)
from .task_api import Task
from .task_payload import TaskPayload

# Try to build __all__ dynamically to support both full and thin envs
__all__ = [
    "ActionIntent",
    "AgentActionApproval",
    "AgentActionAsset",
    "AgentActionClosureRecordResponse",
    "AgentActionClosureRequest",
    "AgentActionClosureResponse",
    "AgentActionEvaluateRequest",
    "AgentActionEvaluateResponse",
    "AgentActionOptions",
    "AgentActionPrincipal",
    "AgentActionRequestRecordResponse",
    "AgentActionSecurityContract",
    "AgentActionTelemetry",
    "AgentActionWorkflow",
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
    "GATEWAY_CONTRACT_VERSION",
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
    "HotPathAssetContext",
    "HotPathCheckResult",
    "HotPathDecisionView",
    "HotPathEvaluateRequest",
    "HotPathEvaluateResponse",
    "HotPathSignerProvenance",
    "HotPathTelemetryContext",
    "EDGE_TELEMETRY_ENVELOPE_VERSION",
    "EdgeTelemetryEnvelopeV0",
    "EdgeTelemetrySampleV0",
    "EdgeTelemetrySignerV0",
    "Task",
    "TaskPayload",
    "VerificationResult",
    "WORKFLOW_TYPE_RCT",
    "AttestationProof",
    "CoSignature",
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
        "TransferApprovalEnvelopeRecord",
        "TransferApprovalTransitionEventRecord",
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
