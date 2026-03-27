export const DISPOSITION_VALUES = ["allow", "deny", "quarantine", "escalate"] as const;
export type Disposition = (typeof DISPOSITION_VALUES)[number];

export const APPROVAL_STATUS_VALUES = [
  "PENDING",
  "PARTIALLY_APPROVED",
  "APPROVED",
  "EXPIRED",
  "REVOKED",
  "SUPERSEDED",
] as const;
export type ApprovalStatus = (typeof APPROVAL_STATUS_VALUES)[number];

export const BUSINESS_STATE_VALUES = [
  "verified",
  "rejected",
  "quarantined",
  "review_required",
  "verification_failed",
] as const;
export type BusinessState = (typeof BUSINESS_STATE_VALUES)[number];

export const TRANSFER_READINESS_VALUES = [
  "ready",
  "blocked",
  "quarantined",
  "review_required",
] as const;
export type TransferReadiness = (typeof TRANSFER_READINESS_VALUES)[number];

export interface TransferTrustSummary {
  verified: boolean;
  business_state: BusinessState;
  disposition: Disposition;
  approval_status: ApprovalStatus;
  execution_token_expected: boolean;
  execution_token_present: boolean;
  verification_error_code: string | null;
  checks: string[];
}

export interface TransferPolicyEvaluationProjection {
  disposition: Disposition;
  execution_token_expected: boolean;
}

export interface TransferVerificationProjection {
  verified: boolean;
  error_code: string | null;
  checks: string[];
  policy: TransferPolicyEvaluationProjection;
}

export interface GovernedDecisionArtifactProjection {
  decision_id: string;
  action_intent_ref: string;
  policy_snapshot_ref: string;
  disposition: Disposition;
  asset_ref: string;
}

export interface PolicyReceiptPayloadProjection {
  policy_receipt_id: string;
  policy_snapshot_ref: string;
  action_intent_ref: string;
  disposition: Disposition;
}

export interface PolicyObligationProjection {
  obligation_type?: string;
  reference?: string;
  details?: unknown;
  [key: string]: unknown;
}

export interface PolicyExplanationProjection {
  trust_gaps: string[];
  missing_prerequisites: string[];
  matched_policy_refs: string[];
  authority_path_summary: string[];
  minted_artifacts: string[];
  obligations: PolicyObligationProjection[];
}

export interface PolicyEvaluationProjection {
  disposition: Disposition;
  explanation: PolicyExplanationProjection;
  governed_decision_artifact: GovernedDecisionArtifactProjection;
  policy_receipt_payload: PolicyReceiptPayloadProjection;
  execution_token_spec: { intent_ref: string; asset_ref: string; policy_snapshot_ref: string } | null;
}

export interface ExecutionTokenProjection {
  token_id: string;
  intent_id: string;
  issued_at: string;
  valid_until: string;
  contract_version: string;
}

export interface TransferVerificationReport {
  verified: boolean;
  checks: string[];
  error_code: string | null;
  actual_policy_evaluation: PolicyEvaluationProjection;
  actual_execution_token: ExecutionTokenProjection | null;
}

export interface TransferProofView {
  business_state: BusinessState;
  disposition: Disposition;
  verified: boolean;
  verification_error_code: string | null;
  approval_status: ApprovalStatus | null;
  asset_ref: string;
  intent_ref: string;
  decision_id: string;
  policy_receipt_id: string;
  execution_token_id: string | null;
  checks: string[];
}

export interface AssetProofView {
  business_state: BusinessState;
  disposition: Disposition;
  asset_ref: string;
  policy_snapshot_ref: string;
  decision_id: string;
  trust_gaps: string[];
  missing_prerequisites: string[];
}

export interface TransferTimelineEntry {
  event_type: string;
  timestamp: string;
  summary: string;
  artifact_ref?: string | null;
}

export interface TransferStatusLinks {
  review: string;
  asset_forensics: string;
  public_trust?: string;
  verify?: string;
}

export interface AssetForensicLinks {
  transfer_review: string;
  public_trust?: string;
  replay_artifacts?: string;
}

export interface SignatureProvenanceEntry {
  artifact_type: string;
  signer_type: string;
  signer_id: string;
  key_ref: string;
  attestation_level: string;
}

export interface PrincipalIdentityView {
  requesting_principal_ref: string;
  approving_principal_refs: string[];
  next_custodian_ref: string | null;
}

export interface CustodyTransitionView {
  from_zone: string;
  to_zone: string;
  facility_ref: string;
  custody_point_ref: string;
  expected_current_custodian: string;
  next_custodian: string;
}

export interface TransferStatusView {
  business_state: BusinessState;
  disposition: Disposition;
  approval_status: ApprovalStatus;
  transfer_readiness: TransferReadiness;
  current_step: string;
  pending_roles: string[];
  blocker_codes: string[];
  verified: boolean;
  verification_error_code: string | null;
  checks: string[];
  timeline: TransferTimelineEntry[];
  links: TransferStatusLinks;
}

export interface AssetForensicView {
  business_state: BusinessState;
  disposition: Disposition;
  asset_ref: string;
  decision_id: string;
  policy_snapshot_ref: string;
  approval_envelope_id: string | null;
  principal_identity: PrincipalIdentityView;
  custody_transition: CustodyTransitionView;
  telemetry_refs: string[];
  signature_provenance: SignatureProvenanceEntry[];
  trust_gaps: string[];
  missing_prerequisites: string[];
  minted_artifacts: string[];
  obligations: unknown[];
  timeline: TransferTimelineEntry[];
  links: AssetForensicLinks;
}

export interface TransferViewContext {
  approval_envelope_id?: string | null;
  pending_roles?: string[];
  timeline?: TransferTimelineEntry[];
  principal_identity?: Partial<PrincipalIdentityView>;
  custody_transition?: Partial<CustodyTransitionView>;
  telemetry_refs?: string[];
  signature_provenance?: SignatureProvenanceEntry[];
  blocker_codes?: string[];
  current_step?: string;
  public_trust_url?: string;
  verify_url?: string;
  replay_artifacts_url?: string;
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

function assertBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
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

function assertStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new Error(`invalid_field:${field}`);
  }
  return value;
}

function assertEnumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  field: string,
): T {
  const parsed = assertString(value, field);
  if (!allowed.includes(parsed as T)) {
    throw new Error(`invalid_enum:${field}:${parsed}`);
  }
  return parsed as T;
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

function assertTransferStatusLinks(value: unknown, field: string): TransferStatusLinks {
  if (!isRecord(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return {
    review: assertString(value.review, `${field}.review`),
    asset_forensics: assertString(value.asset_forensics, `${field}.asset_forensics`),
    public_trust:
      value.public_trust === undefined ? undefined : assertString(value.public_trust, `${field}.public_trust`),
    verify: value.verify === undefined ? undefined : assertString(value.verify, `${field}.verify`),
  };
}

function assertAssetForensicLinks(value: unknown, field: string): AssetForensicLinks {
  if (!isRecord(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return {
    transfer_review: assertString(value.transfer_review, `${field}.transfer_review`),
    public_trust:
      value.public_trust === undefined ? undefined : assertString(value.public_trust, `${field}.public_trust`),
    replay_artifacts:
      value.replay_artifacts === undefined
        ? undefined
        : assertString(value.replay_artifacts, `${field}.replay_artifacts`),
  };
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

function assertPrincipalIdentity(value: unknown, field: string): PrincipalIdentityView {
  if (!isRecord(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return {
    requesting_principal_ref: assertString(value.requesting_principal_ref, `${field}.requesting_principal_ref`),
    approving_principal_refs: assertStringArray(value.approving_principal_refs, `${field}.approving_principal_refs`),
    next_custodian_ref:
      value.next_custodian_ref === null
        ? null
        : assertString(value.next_custodian_ref, `${field}.next_custodian_ref`),
  };
}

function assertCustodyTransition(value: unknown, field: string): CustodyTransitionView {
  if (!isRecord(value)) {
    throw new Error(`invalid_field:${field}`);
  }
  return {
    from_zone: assertString(value.from_zone, `${field}.from_zone`),
    to_zone: assertString(value.to_zone, `${field}.to_zone`),
    facility_ref: assertString(value.facility_ref, `${field}.facility_ref`),
    custody_point_ref: assertString(value.custody_point_ref, `${field}.custody_point_ref`),
    expected_current_custodian: assertString(
      value.expected_current_custodian,
      `${field}.expected_current_custodian`,
    ),
    next_custodian: assertString(value.next_custodian, `${field}.next_custodian`),
  };
}

export function parseTransferTrustSummary(value: unknown): TransferTrustSummary {
  if (!isRecord(value)) {
    throw new Error("invalid_summary_payload");
  }

  const verificationError = value.verification_error_code;
  if (verificationError !== null && typeof verificationError !== "string") {
    throw new Error("invalid_field:verification_error_code");
  }

  return {
    verified: assertBoolean(value.verified, "verified"),
    business_state: assertEnumValue(value.business_state, BUSINESS_STATE_VALUES, "business_state"),
    disposition: assertEnumValue(value.disposition, DISPOSITION_VALUES, "disposition"),
    approval_status: assertEnumValue(value.approval_status, APPROVAL_STATUS_VALUES, "approval_status"),
    execution_token_expected: assertBoolean(value.execution_token_expected, "execution_token_expected"),
    execution_token_present: assertBoolean(value.execution_token_present, "execution_token_present"),
    verification_error_code: verificationError as string | null,
    checks: assertStringArray(value.checks, "checks"),
  };
}

export function parseTransferVerificationReport(value: unknown): TransferVerificationReport {
  if (!isRecord(value)) {
    throw new Error("invalid_verification_payload");
  }

  const actualPolicyEvalRaw = value.actual_policy_evaluation;
  if (!isRecord(actualPolicyEvalRaw)) {
    throw new Error("invalid_field:actual_policy_evaluation");
  }
  const explanationRaw = actualPolicyEvalRaw.explanation;
  if (!isRecord(explanationRaw)) {
    throw new Error("invalid_field:explanation");
  }

  const decisionRaw = actualPolicyEvalRaw.governed_decision_artifact;
  if (!isRecord(decisionRaw)) {
    throw new Error("invalid_field:governed_decision_artifact");
  }

  const receiptRaw = actualPolicyEvalRaw.policy_receipt_payload;
  if (!isRecord(receiptRaw)) {
    throw new Error("invalid_field:policy_receipt_payload");
  }

  const executionTokenSpecRaw = actualPolicyEvalRaw.execution_token_spec;
  let executionTokenSpec: PolicyEvaluationProjection["execution_token_spec"] = null;
  if (executionTokenSpecRaw !== null) {
    if (!isRecord(executionTokenSpecRaw)) {
      throw new Error("invalid_field:execution_token_spec");
    }
    executionTokenSpec = {
      intent_ref: assertString(executionTokenSpecRaw.intent_ref, "execution_token_spec.intent_ref"),
      asset_ref: assertString(executionTokenSpecRaw.asset_ref, "execution_token_spec.asset_ref"),
      policy_snapshot_ref: assertString(
        executionTokenSpecRaw.policy_snapshot_ref,
        "execution_token_spec.policy_snapshot_ref",
      ),
    };
  }

  const tokenRaw = value.actual_execution_token;
  let token: ExecutionTokenProjection | null = null;
  if (tokenRaw !== null) {
    if (!isRecord(tokenRaw)) {
      throw new Error("invalid_field:actual_execution_token");
    }
    token = {
      token_id: assertString(tokenRaw.token_id, "actual_execution_token.token_id"),
      intent_id: assertString(tokenRaw.intent_id, "actual_execution_token.intent_id"),
      issued_at: assertString(tokenRaw.issued_at, "actual_execution_token.issued_at"),
      valid_until: assertString(tokenRaw.valid_until, "actual_execution_token.valid_until"),
      contract_version: assertString(tokenRaw.contract_version, "actual_execution_token.contract_version"),
    };
  }

  return {
    verified: assertBoolean(value.verified, "verified"),
    checks: assertStringArray(value.checks, "checks"),
    error_code: assertNullableString(value.error_code, "error_code"),
    actual_policy_evaluation: {
      disposition: assertEnumValue(actualPolicyEvalRaw.disposition, DISPOSITION_VALUES, "disposition"),
      explanation: {
        trust_gaps: assertStringArray(explanationRaw.trust_gaps, "explanation.trust_gaps"),
        missing_prerequisites: assertStringArray(
          explanationRaw.missing_prerequisites,
          "explanation.missing_prerequisites",
        ),
        matched_policy_refs: assertStringArray(
          explanationRaw.matched_policy_refs ?? [],
          "explanation.matched_policy_refs",
        ),
        authority_path_summary: assertStringArray(
          explanationRaw.authority_path_summary ?? [],
          "explanation.authority_path_summary",
        ),
        minted_artifacts: assertStringArray(
          explanationRaw.minted_artifacts ?? [],
          "explanation.minted_artifacts",
        ),
        obligations: assertUnknownArray(explanationRaw.obligations ?? [], "explanation.obligations") as PolicyObligationProjection[],
      },
      governed_decision_artifact: {
        decision_id: assertString(decisionRaw.decision_id, "governed_decision_artifact.decision_id"),
        action_intent_ref: assertString(
          decisionRaw.action_intent_ref,
          "governed_decision_artifact.action_intent_ref",
        ),
        policy_snapshot_ref: assertString(
          decisionRaw.policy_snapshot_ref,
          "governed_decision_artifact.policy_snapshot_ref",
        ),
        disposition: assertEnumValue(
          decisionRaw.disposition,
          DISPOSITION_VALUES,
          "governed_decision_artifact.disposition",
        ),
        asset_ref: assertString(decisionRaw.asset_ref, "governed_decision_artifact.asset_ref"),
      },
      policy_receipt_payload: {
        policy_receipt_id: assertString(receiptRaw.policy_receipt_id, "policy_receipt_payload.policy_receipt_id"),
        policy_snapshot_ref: assertString(
          receiptRaw.policy_snapshot_ref,
          "policy_receipt_payload.policy_snapshot_ref",
        ),
        action_intent_ref: assertString(
          receiptRaw.action_intent_ref,
          "policy_receipt_payload.action_intent_ref",
        ),
        disposition: assertEnumValue(
          receiptRaw.disposition,
          DISPOSITION_VALUES,
          "policy_receipt_payload.disposition",
        ),
      },
      execution_token_spec: executionTokenSpec,
    },
    actual_execution_token: token,
  };
}

export function parseTransferStatusView(value: unknown): TransferStatusView {
  if (!isRecord(value)) {
    throw new Error("invalid_transfer_status_payload");
  }
  return {
    business_state: assertEnumValue(value.business_state, BUSINESS_STATE_VALUES, "business_state"),
    disposition: assertEnumValue(value.disposition, DISPOSITION_VALUES, "disposition"),
    approval_status: assertEnumValue(value.approval_status, APPROVAL_STATUS_VALUES, "approval_status"),
    transfer_readiness: assertEnumValue(value.transfer_readiness, TRANSFER_READINESS_VALUES, "transfer_readiness"),
    current_step: assertString(value.current_step, "current_step"),
    pending_roles: assertStringArray(value.pending_roles, "pending_roles"),
    blocker_codes: assertStringArray(value.blocker_codes, "blocker_codes"),
    verified: assertBoolean(value.verified, "verified"),
    verification_error_code: assertNullableString(value.verification_error_code, "verification_error_code"),
    checks: assertStringArray(value.checks, "checks"),
    timeline: assertTimeline(value.timeline, "timeline"),
    links: assertTransferStatusLinks(value.links, "links"),
  };
}

export function parseAssetForensicView(value: unknown): AssetForensicView {
  if (!isRecord(value)) {
    throw new Error("invalid_asset_forensic_payload");
  }
  return {
    business_state: assertEnumValue(value.business_state, BUSINESS_STATE_VALUES, "business_state"),
    disposition: assertEnumValue(value.disposition, DISPOSITION_VALUES, "disposition"),
    asset_ref: assertString(value.asset_ref, "asset_ref"),
    decision_id: assertString(value.decision_id, "decision_id"),
    policy_snapshot_ref: assertString(value.policy_snapshot_ref, "policy_snapshot_ref"),
    approval_envelope_id:
      value.approval_envelope_id === null
        ? null
        : assertString(value.approval_envelope_id, "approval_envelope_id"),
    principal_identity: assertPrincipalIdentity(value.principal_identity, "principal_identity"),
    custody_transition: assertCustodyTransition(value.custody_transition, "custody_transition"),
    telemetry_refs: assertStringArray(value.telemetry_refs, "telemetry_refs"),
    signature_provenance: assertSignatureProvenanceArray(
      value.signature_provenance,
      "signature_provenance",
    ),
    trust_gaps: assertStringArray(value.trust_gaps, "trust_gaps"),
    missing_prerequisites: assertStringArray(value.missing_prerequisites, "missing_prerequisites"),
    minted_artifacts: assertStringArray(value.minted_artifacts, "minted_artifacts"),
    obligations: assertUnknownArray(value.obligations, "obligations"),
    timeline: assertTimeline(value.timeline, "timeline"),
    links: assertAssetForensicLinks(value.links, "links"),
  };
}

export function toVerificationProjection(summary: TransferTrustSummary): TransferVerificationProjection {
  return {
    verified: summary.verified,
    error_code: summary.verification_error_code,
    checks: summary.checks,
    policy: {
      disposition: summary.disposition,
      execution_token_expected: summary.execution_token_expected,
    },
  };
}

export function mapBusinessState(verified: boolean, disposition: Disposition): BusinessState {
  if (!verified) {
    return "verification_failed";
  }
  switch (disposition) {
    case "allow":
      return "verified";
    case "deny":
      return "rejected";
    case "quarantine":
      return "quarantined";
    case "escalate":
      return "review_required";
  }
}

export function deriveTransferReadiness(
  disposition: Disposition,
  approvalStatus: ApprovalStatus,
  executionTokenPresent: boolean,
  missingPrerequisites: string[],
): TransferReadiness {
  if (missingPrerequisites.some((value) => value.includes("approval"))) {
    return "blocked";
  }
  switch (disposition) {
    case "allow":
      return approvalStatus === "APPROVED" && executionTokenPresent ? "ready" : "blocked";
    case "deny":
      return "blocked";
    case "quarantine":
      return "quarantined";
    case "escalate":
      return "review_required";
  }
}

function deriveBlockerCodes(
  report: TransferVerificationReport,
  disposition: Disposition,
  context: TransferViewContext,
): string[] {
  if (context.blocker_codes && context.blocker_codes.length > 0) {
    return [...context.blocker_codes];
  }

  const explanation = report.actual_policy_evaluation.explanation;
  const blockers = [...explanation.missing_prerequisites];
  if (disposition === "quarantine") {
    blockers.push(...explanation.trust_gaps);
  }
  if (disposition === "escalate") {
    for (const obligation of explanation.obligations) {
      if (typeof obligation?.reference === "string") {
        blockers.push(obligation.reference);
      } else if (typeof obligation?.obligation_type === "string") {
        blockers.push(obligation.obligation_type);
      }
    }
  }
  return blockers;
}

function deriveCurrentStep(
  readiness: TransferReadiness,
  approvalStatus: ApprovalStatus,
  verified: boolean,
  context: TransferViewContext,
): string {
  if (context.current_step) {
    return context.current_step;
  }
  if (!verified) {
    return "verification_failed";
  }
  if (approvalStatus !== "APPROVED") {
    return "awaiting_approval";
  }
  switch (readiness) {
    case "ready":
      return "transfer_ready";
    case "blocked":
      return "blocked";
    case "quarantined":
      return "quarantine_review";
    case "review_required":
      return "human_review_required";
  }
}

function defaultPrincipalIdentity(context: TransferViewContext): PrincipalIdentityView {
  return {
    requesting_principal_ref: context.principal_identity?.requesting_principal_ref ?? "unknown",
    approving_principal_refs: context.principal_identity?.approving_principal_refs ?? [],
    next_custodian_ref: context.principal_identity?.next_custodian_ref ?? null,
  };
}

function defaultCustodyTransition(context: TransferViewContext): CustodyTransitionView {
  return {
    from_zone: context.custody_transition?.from_zone ?? "unknown",
    to_zone: context.custody_transition?.to_zone ?? "unknown",
    facility_ref: context.custody_transition?.facility_ref ?? "unknown",
    custody_point_ref: context.custody_transition?.custody_point_ref ?? "unknown",
    expected_current_custodian: context.custody_transition?.expected_current_custodian ?? "unknown",
    next_custodian: context.custody_transition?.next_custodian ?? "unknown",
  };
}

export function toTransferProofView(
  report: TransferVerificationReport,
  summary?: TransferTrustSummary,
): TransferProofView {
  const decision = report.actual_policy_evaluation.governed_decision_artifact;
  const receipt = report.actual_policy_evaluation.policy_receipt_payload;
  const disposition = report.actual_policy_evaluation.disposition;
  return {
    business_state: summary?.business_state ?? mapBusinessState(report.verified, disposition),
    disposition,
    verified: report.verified,
    verification_error_code: summary?.verification_error_code ?? report.error_code,
    approval_status: summary?.approval_status ?? null,
    asset_ref: decision.asset_ref,
    intent_ref: decision.action_intent_ref,
    decision_id: decision.decision_id,
    policy_receipt_id: receipt.policy_receipt_id,
    execution_token_id: report.actual_execution_token?.token_id ?? null,
    checks: report.checks,
  };
}

export function toAssetProofView(
  report: TransferVerificationReport,
  summary?: TransferTrustSummary,
): AssetProofView {
  const decision = report.actual_policy_evaluation.governed_decision_artifact;
  const explanation = report.actual_policy_evaluation.explanation;
  return {
    business_state:
      summary?.business_state ?? mapBusinessState(report.verified, report.actual_policy_evaluation.disposition),
    disposition: report.actual_policy_evaluation.disposition,
    asset_ref: decision.asset_ref,
    policy_snapshot_ref: decision.policy_snapshot_ref,
    decision_id: decision.decision_id,
    trust_gaps: explanation.trust_gaps,
    missing_prerequisites: explanation.missing_prerequisites,
  };
}

export function toTransferStatusView(
  report: TransferVerificationReport,
  summary: TransferTrustSummary,
  context: TransferViewContext,
): TransferStatusView {
  const explanation = report.actual_policy_evaluation.explanation;
  const readiness = deriveTransferReadiness(
    summary.disposition,
    summary.approval_status,
    summary.execution_token_present,
    explanation.missing_prerequisites,
  );
  return {
    business_state: summary.business_state,
    disposition: summary.disposition,
    approval_status: summary.approval_status,
    transfer_readiness: readiness,
    current_step: deriveCurrentStep(readiness, summary.approval_status, report.verified, context),
    pending_roles: context.pending_roles ?? [],
    blocker_codes: deriveBlockerCodes(report, summary.disposition, context),
    verified: report.verified,
    verification_error_code: summary.verification_error_code ?? report.error_code,
    checks: report.checks,
    timeline: context.timeline ?? [],
    links: {
      review: "",
      asset_forensics: "",
      public_trust: context.public_trust_url,
      verify: context.verify_url,
    },
  };
}

export function toAssetForensicView(
  report: TransferVerificationReport,
  summary: TransferTrustSummary,
  context: TransferViewContext,
): AssetForensicView {
  const decision = report.actual_policy_evaluation.governed_decision_artifact;
  const explanation = report.actual_policy_evaluation.explanation;
  return {
    business_state: summary.business_state,
    disposition: summary.disposition,
    asset_ref: decision.asset_ref,
    decision_id: decision.decision_id,
    policy_snapshot_ref: decision.policy_snapshot_ref,
    approval_envelope_id: context.approval_envelope_id ?? null,
    principal_identity: defaultPrincipalIdentity(context),
    custody_transition: defaultCustodyTransition(context),
    telemetry_refs: context.telemetry_refs ?? [],
    signature_provenance: context.signature_provenance ?? [],
    trust_gaps: explanation.trust_gaps,
    missing_prerequisites: explanation.missing_prerequisites,
    minted_artifacts: explanation.minted_artifacts,
    obligations: explanation.obligations,
    timeline: context.timeline ?? [],
    links: {
      transfer_review: "",
      public_trust: context.public_trust_url,
      replay_artifacts: context.replay_artifacts_url,
    },
  };
}
