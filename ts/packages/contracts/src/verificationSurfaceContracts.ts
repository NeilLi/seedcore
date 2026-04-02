import {
  APPROVAL_STATUS_VALUES,
  BUSINESS_STATE_VALUES,
  DISPOSITION_VALUES,
  type ApprovalStatus,
  type BusinessState,
  type Disposition,
  type SignatureProvenanceEntry,
  type TransferTimelineEntry,
} from "./trustContracts.js";

export const VERIFICATION_SURFACE_VERSION = "seedcore.verification_surface_projection.v1";

export interface VerificationSurfaceProjection {
  contract_version: typeof VERIFICATION_SURFACE_VERSION;
  workflow_id: string;
  workflow_type: string;
  status: BusinessState;
  asset_ref: string;
  summary: {
    from_zone: string;
    to_zone: string;
    current_state: string;
    approval_state: string;
    quarantined: boolean;
  };
  approvals: {
    required: string[];
    completed_by: string[];
    approval_envelope_id: string | null;
    approval_envelope_version: number | null;
  };
  authorization: {
    disposition: Disposition;
    decision_id: string;
    policy_snapshot_ref: string;
    policy_receipt_id: string;
    transition_receipt_ids: string[];
    execution_token_id: string | null;
    forensic_block_id: string | null;
  };
  verification: {
    signature_valid: boolean;
    policy_trace_available: boolean;
    evidence_trace_available: boolean;
    tamper_status: "clear" | "suspect" | "unknown";
  };
  links: {
    replay_ref: string;
    trust_ref: string | null;
    audit_trail_ref: string;
    forensics_ref: string;
  };
}

export interface TransferAuditTrail {
  contract_version: typeof VERIFICATION_SURFACE_VERSION;
  workflow_id: string;
  workflow_type: string;
  business_state: BusinessState;
  request: {
    request_id: string;
    requested_at: string;
    request_summary: string;
    idempotency_key: string | null;
    workflow_type: string;
    action_type: string;
    valid_until: string | null;
  };
  principal: {
    agent_id: string;
    role_profile: string;
    owner_id: string | null;
    delegation_ref: string | null;
    organization_ref: string | null;
    hardware_fingerprint: {
      fingerprint_id: string | null;
      node_id: string | null;
      public_key_fingerprint: string | null;
      attestation_type: string | null;
      key_ref: string | null;
    };
  };
  authority_scope: {
    scope_id: string | null;
    asset_ref: string;
    product_ref: string | null;
    facility_ref: string | null;
    expected_from_zone: string | null;
    expected_to_zone: string | null;
    expected_coordinate_ref: string | null;
    authority_scope_verdict: "matched" | "mismatch" | "unverified";
    mismatch_keys: string[];
  };
  decision: {
    allowed: boolean;
    disposition: Disposition;
    reason_code: string;
    reason: string;
    policy_snapshot_ref: string;
    latency_ms: number | null;
  };
  approvals: {
    approval_status: ApprovalStatus | null;
    required: string[];
    completed_by: string[];
    approval_envelope_id: string | null;
    approval_envelope_version: number | null;
    approval_binding_hash: string | null;
  };
  artifacts: {
    decision_id: string;
    policy_receipt_id: string;
    transition_receipt_ids: string[];
    execution_token_id: string | null;
    audit_id: string;
    forensic_block_id: string | null;
    minted_artifacts: string[];
    obligations: unknown[];
  };
  physical_evidence: {
    current_zone: string | null;
    current_coordinate_ref: string | null;
    telemetry_refs: string[];
    fingerprint_components: {
      economic_hash: string | null;
      physical_presence_hash: string | null;
      reasoning_hash: string | null;
      actuator_hash: string | null;
    };
    replay_status: "pending" | "ready";
    settlement_status: "pending" | "applied" | "rejected" | "unknown";
  };
  links: {
    workflow_projection_ref: string;
    asset_forensics_ref: string;
    replay_artifacts_ref: string | null;
    trust_ref: string | null;
  };
}

export interface AssetForensicProjection {
  contract_version: typeof VERIFICATION_SURFACE_VERSION;
  workflow_id: string;
  business_state: BusinessState;
  disposition: Disposition;
  asset_ref: string;
  decision_id: string;
  policy_snapshot_ref: string;
  approval_envelope_id: string | null;
  approval_envelope_version: number | null;
  approval_binding_hash: string | null;
  policy_receipt_id: string;
  transition_receipt_ids: string[];
  principal_identity: {
    requesting_principal_ref: string;
    approving_principal_refs: string[];
    next_custodian_ref: string | null;
  };
  custody_transition: {
    from_zone: string;
    to_zone: string;
    facility_ref: string;
    custody_point_ref: string;
    expected_current_custodian: string;
    next_custodian: string;
  };
  asset_custody_state: {
    current_custodian_ref: string | null;
    current_zone_ref: string | null;
    custody_point_ref: string | null;
    authority_source: string | null;
  };
  telemetry_refs: string[];
  signer_provenance: SignatureProvenanceEntry[];
  forensic_fingerprint: {
    economic_hash: string | null;
    physical_presence_hash: string | null;
    reasoning_hash: string | null;
    actuator_hash: string | null;
  };
  trust_gaps: string[];
  missing_prerequisites: string[];
  minted_artifacts: string[];
  obligations: unknown[];
  timeline: TransferTimelineEntry[];
  links: {
    workflow_projection_ref: string;
    transfer_audit_trail_ref: string;
    replay_artifacts_ref: string | null;
    trust_ref: string | null;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function assertString(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new Error(`invalid_field:${field}`);
  }
  return value;
}

function assertNullableString(value: unknown, field: string): string | null {
  if (value === null) {
    return null;
  }
  return assertString(value, field);
}

function assertNullableNumber(value: unknown, field: string): number | null {
  if (value === null) {
    return null;
  }
  if (typeof value !== "number") {
    throw new Error(`invalid_field:${field}`);
  }
  return value;
}

function assertBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`invalid_field:${field}`);
  }
  return value;
}

function assertEnumValue<T extends string>(value: unknown, allowed: readonly T[], field: string): T {
  const parsed = assertString(value, field);
  if (!allowed.includes(parsed as T)) {
    throw new Error(`invalid_enum:${field}:${parsed}`);
  }
  return parsed as T;
}

function assertStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new Error(`invalid_field:${field}`);
  }
  return value;
}

function assertUnknownArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return value;
}

function assertTimelineEntry(value: unknown, field: string): TransferTimelineEntry {
  if (!isRecord(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  const artifactRef = value.artifact_ref;
  if (artifactRef !== undefined && artifactRef !== null && typeof artifactRef !== "string") {
    throw new Error(`invalid_field:${field}.artifact_ref`);
  }
  return {
    event_type: assertString(value.event_type, `${field}.event_type`),
    timestamp: assertString(value.timestamp, `${field}.timestamp`),
    summary: assertString(value.summary, `${field}.summary`),
    artifact_ref: artifactRef === undefined ? undefined : (artifactRef as string | null),
  };
}

function assertTimeline(value: unknown, field: string): TransferTimelineEntry[] {
  if (!Array.isArray(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return value.map((entry, index) => assertTimelineEntry(entry, `${field}.${index}`));
}

function assertSignatureProvenance(value: unknown, field: string): SignatureProvenanceEntry {
  if (!isRecord(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return {
    artifact_type: assertString(value.artifact_type, `${field}.artifact_type`),
    signer_type: assertString(value.signer_type, `${field}.signer_type`),
    signer_id: assertString(value.signer_id, `${field}.signer_id`),
    key_ref: assertString(value.key_ref, `${field}.key_ref`),
    attestation_level: assertString(value.attestation_level, `${field}.attestation_level`),
  };
}

function assertSignatureProvenanceArray(value: unknown, field: string): SignatureProvenanceEntry[] {
  if (!Array.isArray(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return value.map((entry, index) => assertSignatureProvenance(entry, `${field}.${index}`));
}

export function parseVerificationSurfaceProjection(value: unknown): VerificationSurfaceProjection {
  if (!isRecord(value)) {
    throw new Error("invalid_verification_surface_projection");
  }
  const summary = isRecord(value.summary) ? value.summary : {};
  const approvals = isRecord(value.approvals) ? value.approvals : {};
  const authorization = isRecord(value.authorization) ? value.authorization : {};
  const verification = isRecord(value.verification) ? value.verification : {};
  const links = isRecord(value.links) ? value.links : {};
  return {
    contract_version: assertString(value.contract_version, "contract_version") as typeof VERIFICATION_SURFACE_VERSION,
    workflow_id: assertString(value.workflow_id, "workflow_id"),
    workflow_type: assertString(value.workflow_type, "workflow_type"),
    status: assertEnumValue(value.status, BUSINESS_STATE_VALUES, "status"),
    asset_ref: assertString(value.asset_ref, "asset_ref"),
    summary: {
      from_zone: assertString(summary.from_zone, "summary.from_zone"),
      to_zone: assertString(summary.to_zone, "summary.to_zone"),
      current_state: assertString(summary.current_state, "summary.current_state"),
      approval_state: assertString(summary.approval_state, "summary.approval_state"),
      quarantined: assertBoolean(summary.quarantined, "summary.quarantined"),
    },
    approvals: {
      required: assertStringArray(approvals.required, "approvals.required"),
      completed_by: assertStringArray(approvals.completed_by, "approvals.completed_by"),
      approval_envelope_id: assertNullableString(approvals.approval_envelope_id, "approvals.approval_envelope_id"),
      approval_envelope_version: assertNullableNumber(
        approvals.approval_envelope_version,
        "approvals.approval_envelope_version",
      ),
    },
    authorization: {
      disposition: assertEnumValue(authorization.disposition, DISPOSITION_VALUES, "authorization.disposition"),
      decision_id: assertString(authorization.decision_id, "authorization.decision_id"),
      policy_snapshot_ref: assertString(authorization.policy_snapshot_ref, "authorization.policy_snapshot_ref"),
      policy_receipt_id: assertString(authorization.policy_receipt_id, "authorization.policy_receipt_id"),
      transition_receipt_ids: assertStringArray(
        authorization.transition_receipt_ids,
        "authorization.transition_receipt_ids",
      ),
      execution_token_id: assertNullableString(authorization.execution_token_id, "authorization.execution_token_id"),
      forensic_block_id: assertNullableString(authorization.forensic_block_id, "authorization.forensic_block_id"),
    },
    verification: {
      signature_valid: assertBoolean(verification.signature_valid, "verification.signature_valid"),
      policy_trace_available: assertBoolean(verification.policy_trace_available, "verification.policy_trace_available"),
      evidence_trace_available: assertBoolean(
        verification.evidence_trace_available,
        "verification.evidence_trace_available",
      ),
      tamper_status: assertEnumValue(
        verification.tamper_status,
        ["clear", "suspect", "unknown"] as const,
        "verification.tamper_status",
      ),
    },
    links: {
      replay_ref: assertString(links.replay_ref, "links.replay_ref"),
      trust_ref: assertNullableString(links.trust_ref, "links.trust_ref"),
      audit_trail_ref: assertString(links.audit_trail_ref, "links.audit_trail_ref"),
      forensics_ref: assertString(links.forensics_ref, "links.forensics_ref"),
    },
  };
}

export function parseTransferAuditTrail(value: unknown): TransferAuditTrail {
  if (!isRecord(value)) {
    throw new Error("invalid_transfer_audit_trail");
  }
  const request = isRecord(value.request) ? value.request : {};
  const principal = isRecord(value.principal) ? value.principal : {};
  const principalFingerprint = isRecord(principal.hardware_fingerprint) ? principal.hardware_fingerprint : {};
  const authorityScope = isRecord(value.authority_scope) ? value.authority_scope : {};
  const decision = isRecord(value.decision) ? value.decision : {};
  const approvals = isRecord(value.approvals) ? value.approvals : {};
  const artifacts = isRecord(value.artifacts) ? value.artifacts : {};
  const physicalEvidence = isRecord(value.physical_evidence) ? value.physical_evidence : {};
  const fingerprintComponents = isRecord(physicalEvidence.fingerprint_components)
    ? physicalEvidence.fingerprint_components
    : {};
  const links = isRecord(value.links) ? value.links : {};
  return {
    contract_version: assertString(value.contract_version, "contract_version") as typeof VERIFICATION_SURFACE_VERSION,
    workflow_id: assertString(value.workflow_id, "workflow_id"),
    workflow_type: assertString(value.workflow_type, "workflow_type"),
    business_state: assertEnumValue(value.business_state, BUSINESS_STATE_VALUES, "business_state"),
    request: {
      request_id: assertString(request.request_id, "request.request_id"),
      requested_at: assertString(request.requested_at, "request.requested_at"),
      request_summary: assertString(request.request_summary, "request.request_summary"),
      idempotency_key: assertNullableString(request.idempotency_key, "request.idempotency_key"),
      workflow_type: assertString(request.workflow_type, "request.workflow_type"),
      action_type: assertString(request.action_type, "request.action_type"),
      valid_until: assertNullableString(request.valid_until, "request.valid_until"),
    },
    principal: {
      agent_id: assertString(principal.agent_id, "principal.agent_id"),
      role_profile: assertString(principal.role_profile, "principal.role_profile"),
      owner_id: assertNullableString(principal.owner_id, "principal.owner_id"),
      delegation_ref: assertNullableString(principal.delegation_ref, "principal.delegation_ref"),
      organization_ref: assertNullableString(principal.organization_ref, "principal.organization_ref"),
      hardware_fingerprint: {
        fingerprint_id: assertNullableString(
          principalFingerprint.fingerprint_id,
          "principal.hardware_fingerprint.fingerprint_id",
        ),
        node_id: assertNullableString(principalFingerprint.node_id, "principal.hardware_fingerprint.node_id"),
        public_key_fingerprint: assertNullableString(
          principalFingerprint.public_key_fingerprint,
          "principal.hardware_fingerprint.public_key_fingerprint",
        ),
        attestation_type: assertNullableString(
          principalFingerprint.attestation_type,
          "principal.hardware_fingerprint.attestation_type",
        ),
        key_ref: assertNullableString(principalFingerprint.key_ref, "principal.hardware_fingerprint.key_ref"),
      },
    },
    authority_scope: {
      scope_id: assertNullableString(authorityScope.scope_id, "authority_scope.scope_id"),
      asset_ref: assertString(authorityScope.asset_ref, "authority_scope.asset_ref"),
      product_ref: assertNullableString(authorityScope.product_ref, "authority_scope.product_ref"),
      facility_ref: assertNullableString(authorityScope.facility_ref, "authority_scope.facility_ref"),
      expected_from_zone: assertNullableString(
        authorityScope.expected_from_zone,
        "authority_scope.expected_from_zone",
      ),
      expected_to_zone: assertNullableString(authorityScope.expected_to_zone, "authority_scope.expected_to_zone"),
      expected_coordinate_ref: assertNullableString(
        authorityScope.expected_coordinate_ref,
        "authority_scope.expected_coordinate_ref",
      ),
      authority_scope_verdict: assertEnumValue(
        authorityScope.authority_scope_verdict,
        ["matched", "mismatch", "unverified"] as const,
        "authority_scope.authority_scope_verdict",
      ),
      mismatch_keys: assertStringArray(authorityScope.mismatch_keys, "authority_scope.mismatch_keys"),
    },
    decision: {
      allowed: assertBoolean(decision.allowed, "decision.allowed"),
      disposition: assertEnumValue(decision.disposition, DISPOSITION_VALUES, "decision.disposition"),
      reason_code: assertString(decision.reason_code, "decision.reason_code"),
      reason: assertString(decision.reason, "decision.reason"),
      policy_snapshot_ref: assertString(decision.policy_snapshot_ref, "decision.policy_snapshot_ref"),
      latency_ms: assertNullableNumber(decision.latency_ms, "decision.latency_ms"),
    },
    approvals: {
      approval_status:
        approvals.approval_status === null
          ? null
          : assertEnumValue(approvals.approval_status, APPROVAL_STATUS_VALUES, "approvals.approval_status"),
      required: assertStringArray(approvals.required, "approvals.required"),
      completed_by: assertStringArray(approvals.completed_by, "approvals.completed_by"),
      approval_envelope_id: assertNullableString(approvals.approval_envelope_id, "approvals.approval_envelope_id"),
      approval_envelope_version: assertNullableNumber(
        approvals.approval_envelope_version,
        "approvals.approval_envelope_version",
      ),
      approval_binding_hash: assertNullableString(approvals.approval_binding_hash, "approvals.approval_binding_hash"),
    },
    artifacts: {
      decision_id: assertString(artifacts.decision_id, "artifacts.decision_id"),
      policy_receipt_id: assertString(artifacts.policy_receipt_id, "artifacts.policy_receipt_id"),
      transition_receipt_ids: assertStringArray(artifacts.transition_receipt_ids, "artifacts.transition_receipt_ids"),
      execution_token_id: assertNullableString(artifacts.execution_token_id, "artifacts.execution_token_id"),
      audit_id: assertString(artifacts.audit_id, "artifacts.audit_id"),
      forensic_block_id: assertNullableString(artifacts.forensic_block_id, "artifacts.forensic_block_id"),
      minted_artifacts: assertStringArray(artifacts.minted_artifacts, "artifacts.minted_artifacts"),
      obligations: assertUnknownArray(artifacts.obligations, "artifacts.obligations"),
    },
    physical_evidence: {
      current_zone: assertNullableString(physicalEvidence.current_zone, "physical_evidence.current_zone"),
      current_coordinate_ref: assertNullableString(
        physicalEvidence.current_coordinate_ref,
        "physical_evidence.current_coordinate_ref",
      ),
      telemetry_refs: assertStringArray(physicalEvidence.telemetry_refs, "physical_evidence.telemetry_refs"),
      fingerprint_components: {
        economic_hash: assertNullableString(
          fingerprintComponents.economic_hash,
          "physical_evidence.fingerprint_components.economic_hash",
        ),
        physical_presence_hash: assertNullableString(
          fingerprintComponents.physical_presence_hash,
          "physical_evidence.fingerprint_components.physical_presence_hash",
        ),
        reasoning_hash: assertNullableString(
          fingerprintComponents.reasoning_hash,
          "physical_evidence.fingerprint_components.reasoning_hash",
        ),
        actuator_hash: assertNullableString(
          fingerprintComponents.actuator_hash,
          "physical_evidence.fingerprint_components.actuator_hash",
        ),
      },
      replay_status: assertEnumValue(
        physicalEvidence.replay_status,
        ["pending", "ready"] as const,
        "physical_evidence.replay_status",
      ),
      settlement_status: assertEnumValue(
        physicalEvidence.settlement_status,
        ["pending", "applied", "rejected", "unknown"] as const,
        "physical_evidence.settlement_status",
      ),
    },
    links: {
      workflow_projection_ref: assertString(links.workflow_projection_ref, "links.workflow_projection_ref"),
      asset_forensics_ref: assertString(links.asset_forensics_ref, "links.asset_forensics_ref"),
      replay_artifacts_ref: assertNullableString(links.replay_artifacts_ref, "links.replay_artifacts_ref"),
      trust_ref: assertNullableString(links.trust_ref, "links.trust_ref"),
    },
  };
}

export function parseAssetForensicProjection(value: unknown): AssetForensicProjection {
  if (!isRecord(value)) {
    throw new Error("invalid_asset_forensic_projection");
  }
  const principalIdentity = isRecord(value.principal_identity) ? value.principal_identity : {};
  const custodyTransition = isRecord(value.custody_transition) ? value.custody_transition : {};
  const forensicFingerprint = isRecord(value.forensic_fingerprint) ? value.forensic_fingerprint : {};
  const assetCustodyState = isRecord(value.asset_custody_state) ? value.asset_custody_state : {};
  const links = isRecord(value.links) ? value.links : {};
  return {
    contract_version: assertString(value.contract_version, "contract_version") as typeof VERIFICATION_SURFACE_VERSION,
    workflow_id: assertString(value.workflow_id, "workflow_id"),
    business_state: assertEnumValue(value.business_state, BUSINESS_STATE_VALUES, "business_state"),
    disposition: assertEnumValue(value.disposition, DISPOSITION_VALUES, "disposition"),
    asset_ref: assertString(value.asset_ref, "asset_ref"),
    decision_id: assertString(value.decision_id, "decision_id"),
    policy_snapshot_ref: assertString(value.policy_snapshot_ref, "policy_snapshot_ref"),
    approval_envelope_id: assertNullableString(value.approval_envelope_id, "approval_envelope_id"),
    approval_envelope_version: assertNullableNumber(value.approval_envelope_version, "approval_envelope_version"),
    approval_binding_hash: assertNullableString(value.approval_binding_hash, "approval_binding_hash"),
    policy_receipt_id: assertString(value.policy_receipt_id, "policy_receipt_id"),
    transition_receipt_ids: assertStringArray(value.transition_receipt_ids, "transition_receipt_ids"),
    principal_identity: {
      requesting_principal_ref: assertString(
        principalIdentity.requesting_principal_ref,
        "principal_identity.requesting_principal_ref",
      ),
      approving_principal_refs: assertStringArray(
        principalIdentity.approving_principal_refs,
        "principal_identity.approving_principal_refs",
      ),
      next_custodian_ref: assertNullableString(
        principalIdentity.next_custodian_ref,
        "principal_identity.next_custodian_ref",
      ),
    },
    custody_transition: {
      from_zone: assertString(custodyTransition.from_zone, "custody_transition.from_zone"),
      to_zone: assertString(custodyTransition.to_zone, "custody_transition.to_zone"),
      facility_ref: assertString(custodyTransition.facility_ref, "custody_transition.facility_ref"),
      custody_point_ref: assertString(custodyTransition.custody_point_ref, "custody_transition.custody_point_ref"),
      expected_current_custodian: assertString(
        custodyTransition.expected_current_custodian,
        "custody_transition.expected_current_custodian",
      ),
      next_custodian: assertString(custodyTransition.next_custodian, "custody_transition.next_custodian"),
    },
    asset_custody_state: {
      current_custodian_ref: assertNullableString(
        assetCustodyState.current_custodian_ref,
        "asset_custody_state.current_custodian_ref",
      ),
      current_zone_ref: assertNullableString(assetCustodyState.current_zone_ref, "asset_custody_state.current_zone_ref"),
      custody_point_ref: assertNullableString(
        assetCustodyState.custody_point_ref,
        "asset_custody_state.custody_point_ref",
      ),
      authority_source: assertNullableString(assetCustodyState.authority_source, "asset_custody_state.authority_source"),
    },
    telemetry_refs: assertStringArray(value.telemetry_refs, "telemetry_refs"),
    signer_provenance: assertSignatureProvenanceArray(value.signer_provenance, "signer_provenance"),
    forensic_fingerprint: {
      economic_hash: assertNullableString(forensicFingerprint.economic_hash, "forensic_fingerprint.economic_hash"),
      physical_presence_hash: assertNullableString(
        forensicFingerprint.physical_presence_hash,
        "forensic_fingerprint.physical_presence_hash",
      ),
      reasoning_hash: assertNullableString(forensicFingerprint.reasoning_hash, "forensic_fingerprint.reasoning_hash"),
      actuator_hash: assertNullableString(forensicFingerprint.actuator_hash, "forensic_fingerprint.actuator_hash"),
    },
    trust_gaps: assertStringArray(value.trust_gaps, "trust_gaps"),
    missing_prerequisites: assertStringArray(value.missing_prerequisites, "missing_prerequisites"),
    minted_artifacts: assertStringArray(value.minted_artifacts, "minted_artifacts"),
    obligations: assertUnknownArray(value.obligations, "obligations"),
    timeline: assertTimeline(value.timeline, "timeline"),
    links: {
      workflow_projection_ref: assertString(links.workflow_projection_ref, "links.workflow_projection_ref"),
      transfer_audit_trail_ref: assertString(links.transfer_audit_trail_ref, "links.transfer_audit_trail_ref"),
      replay_artifacts_ref: assertNullableString(links.replay_artifacts_ref, "links.replay_artifacts_ref"),
      trust_ref: assertNullableString(links.trust_ref, "links.trust_ref"),
    },
  };
}
