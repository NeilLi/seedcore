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

export interface PolicyEvaluationProjection {
  disposition: Disposition;
  explanation: {
    trust_gaps: string[];
    missing_prerequisites: string[];
  };
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
    approval_status: assertEnumValue(
      value.approval_status,
      APPROVAL_STATUS_VALUES,
      "approval_status",
    ),
    execution_token_expected: assertBoolean(
      value.execution_token_expected,
      "execution_token_expected",
    ),
    execution_token_present: assertBoolean(
      value.execution_token_present,
      "execution_token_present",
    ),
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
      contract_version: assertString(
        tokenRaw.contract_version,
        "actual_execution_token.contract_version",
      ),
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

function mapBusinessState(verified: boolean, disposition: Disposition): BusinessState {
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
    business_state: summary?.business_state ?? mapBusinessState(report.verified, report.actual_policy_evaluation.disposition),
    disposition: report.actual_policy_evaluation.disposition,
    asset_ref: decision.asset_ref,
    policy_snapshot_ref: decision.policy_snapshot_ref,
    decision_id: decision.decision_id,
    trust_gaps: explanation.trust_gaps,
    missing_prerequisites: explanation.missing_prerequisites,
  };
}
