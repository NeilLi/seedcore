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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function assertString(value: unknown, field: string): string {
  if (typeof value !== "string") {
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

