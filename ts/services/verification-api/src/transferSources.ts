import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import {
  ApprovalStatus,
  AssetForensicView,
  AssetProofView,
  BusinessState,
  Disposition,
  SignatureProvenanceEntry,
  TransferProofView,
  TransferStatusView,
  TransferTimelineEntry,
  TransferTrustSummary,
  TransferVerificationReport,
  mapBusinessState,
  parseTransferTrustSummary,
  parseTransferVerificationReport,
  toAssetForensicView,
  toAssetProofView,
  toTransferProofView,
  toTransferStatusView,
} from "@seedcore/contracts";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, "../../../..");
const COMMAND_CWD = process.env.INIT_CWD ?? process.cwd();
const DEFAULT_TRANSFER_DIR = "rust/fixtures/transfers/allow_case";
const DEFAULT_TRANSFER_ROOT = "rust/fixtures/transfers";
const DEFAULT_RUNTIME_API_BASE = process.env.SEEDCORE_RUNTIME_API_BASE ?? "http://127.0.0.1:8002/api/v1";

export type TransferSourceMode = "fixture" | "runtime";

export interface TransferSourceQuery {
  source: TransferSourceMode;
  dir?: string;
  root?: string;
  audit_id?: string;
  intent_id?: string;
  subject_id?: string;
}

export interface TransferCatalogItem {
  id: string;
  dir?: string;
  source: TransferSourceMode;
  query: string;
  summary: TransferTrustSummary;
  status_preview: {
    transfer_readiness: string;
    current_step: string;
    top_blocker: string | null;
  };
  links: {
    status: string;
    review: string;
    asset_forensics: string;
  };
}

export interface TransferScenario {
  summary: TransferTrustSummary;
  transfer_proof: TransferProofView;
  asset_proof: AssetProofView;
  status: TransferStatusView;
  asset_forensics: AssetForensicView;
}

type RuntimeLookupKey = "audit_id" | "intent_id" | "subject_id";
const TRANSFER_RUNTIME_LOOKUP_KEYS: RuntimeLookupKey[] = ["audit_id", "intent_id"];
const FORENSIC_RUNTIME_LOOKUP_KEYS: RuntimeLookupKey[] = ["audit_id", "intent_id", "subject_id"];

interface RuntimeReplayView {
  replay_id?: string;
  subject_id?: string;
  subject_type?: string;
  intent_id?: string;
  audit_record_id?: string;
  public_id?: string;
  public_ref?: string;
  trust_ref?: string;
  verification_ref?: string;
  authz_graph?: Record<string, unknown>;
  governed_receipt?: Record<string, unknown>;
  policy_receipt?: Record<string, unknown>;
  evidence_bundle?: Record<string, unknown>;
  verification_status?: Record<string, unknown>;
  signer_chain?: Array<Record<string, unknown>>;
  replay_timeline?: Array<Record<string, unknown>>;
  audit_record?: Record<string, unknown>;
  asset_custody_state?: Record<string, unknown> | null;
  transition_receipts?: Array<Record<string, unknown>>;
}

function resolveVerifyBinary(): string {
  const override = process.env.SEEDCORE_VERIFY_BIN?.trim();
  if (override) {
    return override;
  }
  const candidates = [
    path.resolve(COMMAND_CWD, "rust/target/release/seedcore-verify"),
    path.resolve(COMMAND_CWD, "rust/target/debug/seedcore-verify"),
    path.resolve(REPO_ROOT, "rust/target/release/seedcore-verify"),
    path.resolve(REPO_ROOT, "rust/target/debug/seedcore-verify"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return "seedcore-verify";
}

export function resolveFixtureDir(rawPath?: string | null): string {
  const input = (rawPath ?? "").trim() || DEFAULT_TRANSFER_DIR;
  if (path.isAbsolute(input)) {
    return input;
  }
  const candidates = [path.resolve(COMMAND_CWD, input), path.resolve(REPO_ROOT, input)];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return path.resolve(COMMAND_CWD, input);
}

function requireFixtureDir(rawPath?: string | null): string {
  const input = (rawPath ?? "").trim();
  if (!input) {
    throw new Error("invalid_fixture_lookup:dir");
  }
  return resolveFixtureDir(input);
}

export function resolveTransferRoot(rawPath?: string | null): string {
  const input = (rawPath ?? "").trim() || DEFAULT_TRANSFER_ROOT;
  if (path.isAbsolute(input)) {
    return input;
  }
  const candidates = [path.resolve(COMMAND_CWD, input), path.resolve(REPO_ROOT, input)];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return path.resolve(COMMAND_CWD, input);
}

function runVerifier(command: "summarize-transfer" | "verify-transfer", dir: string): unknown {
  const verifyBin = resolveVerifyBinary();
  const output = execFileSync(verifyBin, [command, "--dir", dir], {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return JSON.parse(output);
}

function readJsonFile(filePath: string): unknown {
  return JSON.parse(readFileSync(filePath, "utf-8"));
}

function readOptionalJsonFile(dir: string, name: string): Record<string, unknown> {
  const filePath = path.join(dir, name);
  if (!existsSync(filePath)) {
    return {};
  }
  const parsed = readJsonFile(filePath);
  return isRecord(parsed) ? parsed : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback = "unknown"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function arrayOfStrings(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === "string" && entry.length > 0);
}

function objectArray(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is Record<string, unknown> => isRecord(entry));
}

function buildQueryString(query: TransferSourceQuery): string {
  const params = new URLSearchParams();
  params.set("source", query.source);
  if (query.source === "fixture") {
    params.set("dir", resolveFixtureDir(query.dir));
  } else {
    if (query.audit_id) {
      params.set("audit_id", query.audit_id);
    }
    if (query.intent_id) {
      params.set("intent_id", query.intent_id);
    }
    if (query.subject_id) {
      params.set("subject_id", query.subject_id);
    }
  }
  return params.toString();
}

function buildStatusLinks(query: TransferSourceQuery) {
  const qs = buildQueryString(query);
  return {
    review: `/api/v1/transfers/review?${qs}`,
    asset_forensics: `/api/v1/assets/forensics?${qs}`,
  };
}

function buildForensicLinks(query: TransferSourceQuery) {
  const qs = buildQueryString(query);
  return {
    transfer_review: `/api/v1/transfers/review?${qs}`,
  };
}

function fixtureTimeline(
  approvalEnvelope: Record<string, unknown>,
  telemetrySummary: Record<string, unknown>,
  report: TransferVerificationReport,
): TransferTimelineEntry[] {
  const timeline: TransferTimelineEntry[] = [];
  const createdAt = optionalString(approvalEnvelope.created_at);
  if (createdAt) {
    timeline.push({
      event_type: "approval_envelope_created",
      timestamp: createdAt,
      summary: `Approval envelope ${stringValue(approvalEnvelope.approval_envelope_id)} created`,
      artifact_ref: optionalString(approvalEnvelope.approval_envelope_id),
    });
  }

  for (const approval of objectArray(approvalEnvelope.required_approvals)) {
    const approvedAt = optionalString(approval.approved_at);
    if (!approvedAt) {
      continue;
    }
    timeline.push({
      event_type: "approval_recorded",
      timestamp: approvedAt,
      summary: `${stringValue(approval.role)} ${stringValue(approval.status)} by ${stringValue(approval.principal_ref)}`,
      artifact_ref: optionalString(approval.approval_ref),
    });
  }

  const observedAt = optionalString(telemetrySummary.observed_at);
  if (observedAt) {
    timeline.push({
      event_type: "telemetry_observed",
      timestamp: observedAt,
      summary: `Telemetry snapshot observed at ${observedAt}`,
    });
  }

  const token = report.actual_execution_token;
  if (token) {
    timeline.push({
      event_type: "execution_token_minted",
      timestamp: token.issued_at,
      summary: `Execution token ${token.token_id} minted`,
      artifact_ref: token.token_id,
    });
  }

  timeline.push({
    event_type: "policy_evaluated",
    timestamp: token?.issued_at ?? observedAt ?? createdAt ?? "unknown",
    summary: `Disposition ${report.actual_policy_evaluation.disposition} verified`,
    artifact_ref: report.actual_policy_evaluation.policy_receipt_payload.policy_receipt_id,
  });

  return timeline.sort((left, right) => left.timestamp.localeCompare(right.timestamp));
}

function extractFixturePendingRoles(approvalEnvelope: Record<string, unknown>): string[] {
  return objectArray(approvalEnvelope.required_approvals)
    .filter((approval) => stringValue(approval.status) !== "APPROVED")
    .map((approval) => stringValue(approval.role))
    .filter((role) => role !== "unknown");
}

function extractTelemetryRefs(
  assetState: Record<string, unknown>,
  telemetrySummary: Record<string, unknown>,
): string[] {
  const refs = arrayOfStrings(assetState.evidence_refs);
  const observedAt = optionalString(telemetrySummary.observed_at);
  if (observedAt) {
    refs.push(`telemetry_observed:${observedAt}`);
  }
  return refs;
}

function extractFixtureSignatureProvenance(reportRaw: unknown): SignatureProvenanceEntry[] {
  if (!isRecord(reportRaw)) {
    return [];
  }
  const provenance: SignatureProvenanceEntry[] = [];
  const token = isRecord(reportRaw.actual_execution_token) ? reportRaw.actual_execution_token : undefined;
  if (token && isRecord(token.signature)) {
    provenance.push({
      artifact_type: "execution_token",
      signer_type: stringValue(token.signature.signer_type),
      signer_id: stringValue(token.signature.signer_id),
      key_ref: stringValue(token.signature.key_ref),
      attestation_level: stringValue(token.signature.attestation_level),
    });
  }
  return provenance;
}

function buildFixtureScenario(query: TransferSourceQuery): TransferScenario {
  const dir = requireFixtureDir(query.dir);
  if (!existsSync(dir)) {
    throw new Error(`fixture_not_found:${dir}`);
  }

  const rawSummary = runVerifier("summarize-transfer", dir);
  const rawReport = runVerifier("verify-transfer", dir);
  const rawReportRecord = isRecord(rawReport) ? rawReport : {};
  const summary = parseTransferTrustSummary(rawSummary);
  const report = parseTransferVerificationReport(rawReport);
  const approvalEnvelope = readOptionalJsonFile(dir, "input.approval_envelope.json");
  const actionIntent = readOptionalJsonFile(dir, "input.action_intent.json");
  const assetState = readOptionalJsonFile(dir, "input.asset_state.json");
  const telemetrySummary = readOptionalJsonFile(dir, "input.telemetry_summary.json");
  const timeline = fixtureTimeline(approvalEnvelope, telemetrySummary, report);
  const links = buildStatusLinks(query);
  const forensicLinks = buildForensicLinks(query);

  const status = toTransferStatusView(report, summary, {
    approval_envelope_id: optionalString(approvalEnvelope.approval_envelope_id) ?? null,
    approval_envelope_version: optionalNumber(approvalEnvelope.version) ?? null,
    approval_binding_hash: optionalString(approvalEnvelope.approval_binding_hash) ?? null,
    policy_receipt_id:
      optionalString((rawReportRecord.policy_receipt_payload as Record<string, unknown> | undefined)?.policy_receipt_id) ??
      null,
    transition_receipt_ids: [],
    pending_roles: extractFixturePendingRoles(approvalEnvelope),
    timeline,
    principal_identity: {
      requesting_principal_ref:
        optionalString(actionIntent.principal_agent_id) ?? stringValue(approvalEnvelope.from_custodian_ref),
      approving_principal_refs: objectArray(approvalEnvelope.required_approvals)
        .map((approval) => optionalString(approval.principal_ref))
        .filter((entry): entry is string => Boolean(entry)),
      next_custodian_ref: optionalString(approvalEnvelope.to_custodian_ref) ?? null,
    },
    custody_transition: {
      from_zone: stringValue((approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.from_zone),
      to_zone: stringValue((approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.to_zone),
      facility_ref: stringValue((approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.facility_ref),
      custody_point_ref: stringValue(
        (approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.custody_point_ref,
      ),
      expected_current_custodian:
        optionalString(assetState.current_custodian_ref) ?? stringValue(approvalEnvelope.from_custodian_ref),
      next_custodian: stringValue(approvalEnvelope.to_custodian_ref),
    },
    telemetry_refs: extractTelemetryRefs(assetState, telemetrySummary),
    signature_provenance: extractFixtureSignatureProvenance(rawReport),
    asset_custody_state: {
      current_custodian_ref: optionalString(assetState.current_custodian_ref) ?? null,
      current_zone_ref: optionalString(assetState.current_zone_ref ?? assetState.current_zone) ?? null,
      custody_point_ref: optionalString(assetState.custody_point_ref) ?? null,
      authority_source: optionalString(assetState.authority_source) ?? null,
    },
  });

  const transferProof = toTransferProofView(report, summary, {
    approval_envelope_id: optionalString(approvalEnvelope.approval_envelope_id) ?? null,
    approval_envelope_version: optionalNumber(approvalEnvelope.version) ?? null,
    approval_binding_hash: optionalString(approvalEnvelope.approval_binding_hash) ?? null,
    policy_receipt_id:
      optionalString((rawReportRecord.policy_receipt_payload as Record<string, unknown> | undefined)?.policy_receipt_id) ??
      null,
    transition_receipt_ids: [],
  });
  const assetProof = toAssetProofView(report, summary);
  const assetForensics = toAssetForensicView(report, summary, {
    approval_envelope_id: optionalString(approvalEnvelope.approval_envelope_id) ?? null,
    approval_envelope_version: optionalNumber(approvalEnvelope.version) ?? null,
    approval_binding_hash: optionalString(approvalEnvelope.approval_binding_hash) ?? null,
    policy_receipt_id:
      optionalString((rawReportRecord.policy_receipt_payload as Record<string, unknown> | undefined)?.policy_receipt_id) ??
      null,
    transition_receipt_ids: [],
    timeline,
    principal_identity: {
      requesting_principal_ref:
        optionalString(actionIntent.principal_agent_id) ?? stringValue(approvalEnvelope.from_custodian_ref),
      approving_principal_refs: objectArray(approvalEnvelope.required_approvals)
        .map((approval) => optionalString(approval.principal_ref))
        .filter((entry): entry is string => Boolean(entry)),
      next_custodian_ref: optionalString(approvalEnvelope.to_custodian_ref) ?? null,
    },
    custody_transition: {
      from_zone: stringValue((approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.from_zone),
      to_zone: stringValue((approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.to_zone),
      facility_ref: stringValue((approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.facility_ref),
      custody_point_ref: stringValue(
        (approvalEnvelope.transfer_context as Record<string, unknown> | undefined)?.custody_point_ref,
      ),
      expected_current_custodian:
        optionalString(assetState.current_custodian_ref) ?? stringValue(approvalEnvelope.from_custodian_ref),
      next_custodian: stringValue(approvalEnvelope.to_custodian_ref),
    },
    telemetry_refs: extractTelemetryRefs(assetState, telemetrySummary),
    signature_provenance: extractFixtureSignatureProvenance(rawReport),
    asset_custody_state: {
      current_custodian_ref: optionalString(assetState.current_custodian_ref) ?? null,
      current_zone_ref: optionalString(assetState.current_zone_ref ?? assetState.current_zone) ?? null,
      custody_point_ref: optionalString(assetState.custody_point_ref) ?? null,
      authority_source: optionalString(assetState.authority_source) ?? null,
    },
  });

  status.links = {
    ...status.links,
    ...links,
  };
  assetForensics.links = {
    ...assetForensics.links,
    ...forensicLinks,
  };

  return {
    summary,
    transfer_proof: transferProof,
    asset_proof: assetProof,
    status,
    asset_forensics: assetForensics,
  };
}

function assertSingleLookup(query: TransferSourceQuery, keys: RuntimeLookupKey[]): [RuntimeLookupKey, string] {
  const provided = keys
    .map((key) => [key, query[key]] as const)
    .filter((entry): entry is [RuntimeLookupKey, string] => typeof entry[1] === "string" && entry[1].trim().length > 0);
  if (provided.length !== 1) {
    throw new Error(`invalid_runtime_lookup:${keys.join("|")}`);
  }
  return provided[0];
}

function makeRuntimeLookupQuery(key: RuntimeLookupKey, value: string): TransferSourceQuery {
  if (key === "audit_id") {
    return { source: "runtime", audit_id: value };
  }
  if (key === "intent_id") {
    return { source: "runtime", intent_id: value };
  }
  return { source: "runtime", subject_id: value };
}

function deriveRuntimeTransferLookup(view: RuntimeReplayView, query: TransferSourceQuery): TransferSourceQuery {
  if (query.audit_id) {
    return { source: "runtime", audit_id: query.audit_id };
  }
  if (query.intent_id) {
    return { source: "runtime", intent_id: query.intent_id };
  }
  const auditRecord = isRecord(view.audit_record) ? view.audit_record : {};
  const auditId = optionalString(view.audit_record_id) ?? optionalString(auditRecord.id);
  if (auditId) {
    return { source: "runtime", audit_id: auditId };
  }
  const intentId = optionalString(view.intent_id) ?? optionalString(auditRecord.intent_id);
  if (intentId) {
    return { source: "runtime", intent_id: intentId };
  }
  throw new Error("invalid_runtime_lookup:audit_id|intent_id");
}

function deriveRuntimeForensicLookup(view: RuntimeReplayView, query: TransferSourceQuery): TransferSourceQuery {
  if (query.audit_id || query.intent_id || query.subject_id) {
    const [key, value] = assertSingleLookup(query, FORENSIC_RUNTIME_LOOKUP_KEYS);
    return makeRuntimeLookupQuery(key, value);
  }
  const transferLookup = deriveRuntimeTransferLookup(view, query);
  if (transferLookup.audit_id || transferLookup.intent_id) {
    return transferLookup;
  }
  const subjectId = optionalString(view.subject_id);
  if (!subjectId) {
    throw new Error("invalid_runtime_lookup:audit_id|intent_id|subject_id");
  }
  return { source: "runtime", subject_id: subjectId };
}

function replayArtifactsUrl(query: TransferSourceQuery): string {
  const [key, value] = assertSingleLookup(query, FORENSIC_RUNTIME_LOOKUP_KEYS);
  const params = new URLSearchParams();
  params.set("projection", "internal");
  params.set(key, value);
  if (key === "subject_id") {
    params.set("subject_type", "asset");
  }
  return `${DEFAULT_RUNTIME_API_BASE}/replay/artifacts?${params.toString()}`;
}

function extractPublicTrustUrl(view: RuntimeReplayView): string | undefined {
  const candidates = [
    optionalString(view.public_id),
    optionalString(view.public_ref),
    optionalString(view.trust_ref),
    optionalString((isRecord(view.audit_record) ? view.audit_record : {}).public_id),
    optionalString((isRecord(view.audit_record) ? view.audit_record : {}).trust_ref),
    optionalString(
      ((isRecord(view.audit_record) ? view.audit_record.policy_decision : undefined) as Record<string, unknown> | undefined)
        ?.trust_ref,
    ),
  ];
  const trustId = candidates.find((entry): entry is string => typeof entry === "string" && entry.length > 0);
  if (!trustId) {
    return undefined;
  }
  const normalized = trustId.startsWith("trust:") ? trustId.slice("trust:".length) : trustId;
  return `${DEFAULT_RUNTIME_API_BASE}/trust/${encodeURIComponent(normalized)}`;
}

async function fetchRuntimeJson(
  pathName: string,
  init?: RequestInit,
): Promise<unknown> {
  const response = await fetch(`${DEFAULT_RUNTIME_API_BASE}${pathName}`, init);
  if (!response.ok) {
    throw new Error(`runtime_fetch_failed:${response.status}:${response.statusText}`);
  }
  return response.json();
}

function deriveRuntimeApprovalStatus(view: RuntimeReplayView): ApprovalStatus {
  const auditRecord = isRecord(view.audit_record) ? view.audit_record : {};
  const policyDecision = isRecord(auditRecord.policy_decision) ? auditRecord.policy_decision : {};
  const requiredApprovals = arrayOfStrings(policyDecision.required_approvals);
  const approvalContext = isRecord(
    ((auditRecord.action_intent as Record<string, unknown> | undefined)?.action as Record<string, unknown> | undefined)
      ?.parameters,
  )
    ? (((auditRecord.action_intent as Record<string, unknown>).action as Record<string, unknown>).parameters as Record<string, unknown>)
    : {};
  const approvalState = isRecord(approvalContext.approval_context) ? approvalContext.approval_context : {};
  const approvedBy = arrayOfStrings(approvalState.approved_by);

  if (requiredApprovals.length === 0) {
    return "APPROVED";
  }
  if (approvedBy.length === 0) {
    return "PENDING";
  }
  if (approvedBy.length >= requiredApprovals.length) {
    return "APPROVED";
  }
  return "PARTIALLY_APPROVED";
}

function runtimeTrustGapCodes(view: RuntimeReplayView): string[] {
  const authzGraph = isRecord(view.authz_graph) ? view.authz_graph : {};
  const trustGaps = objectArray(authzGraph.trust_gaps);
  if (trustGaps.length > 0) {
    return trustGaps
      .map((entry) => optionalString(entry.code))
      .filter((entry): entry is string => Boolean(entry));
  }
  const auditRecord = isRecord(view.audit_record) ? view.audit_record : {};
  const governedReceipt = isRecord((auditRecord.policy_decision as Record<string, unknown> | undefined)?.governed_receipt)
    ? ((auditRecord.policy_decision as Record<string, unknown>).governed_receipt as Record<string, unknown>)
    : {};
  return arrayOfStrings(governedReceipt.trust_gap_codes);
}

function extractRuntimeChecks(view: RuntimeReplayView): string[] {
  const verification = isRecord(view.verification_status) ? view.verification_status : {};
  const artifactResults = isRecord(verification.artifact_results) ? verification.artifact_results : {};
  const checks: string[] = [];
  for (const [key, value] of Object.entries(artifactResults)) {
    if (Array.isArray(value)) {
      if (
        value.every((entry) =>
          isRecord(entry)
            ? entry.verified === true || entry.valid === true || entry.error === null || entry.error_code === null
            : false,
        )
      ) {
        checks.push(`${key}_verified`);
      }
      continue;
    }
    if (!isRecord(value)) {
      continue;
    }
    if (value.verified === true || value.valid === true || value.error === null || value.error_code === null) {
      checks.push(`${key}_verified`);
    }
  }
  return checks.length > 0 ? checks : arrayOfStrings(verification.issues);
}

function runtimeTimeline(view: RuntimeReplayView): TransferTimelineEntry[] {
  return objectArray(view.replay_timeline).map((entry) => ({
    event_type: stringValue(entry.event_type),
    timestamp: stringValue(entry.timestamp),
    summary: stringValue(entry.summary),
    artifact_ref: optionalString(entry.artifact_ref),
  }));
}

function runtimeSignatureProvenance(view: RuntimeReplayView): SignatureProvenanceEntry[] {
  return objectArray(view.signer_chain).map((entry) => {
    const metadata = isRecord(entry.signer_metadata) ? entry.signer_metadata : {};
    return {
      artifact_type: stringValue(entry.artifact_type),
      signer_type: stringValue(entry.signer_type ?? metadata.signer_type),
      signer_id: stringValue(entry.signer_id ?? metadata.signer_id),
      key_ref: optionalString(entry.key_ref ?? metadata.key_ref) ?? "hidden",
      attestation_level: stringValue(entry.attestation_level ?? metadata.attestation_level),
    };
  });
}

function runtimeTelemetryRefs(view: RuntimeReplayView): string[] {
  const evidenceBundle = isRecord(view.evidence_bundle) ? view.evidence_bundle : {};
  return objectArray(evidenceBundle.telemetry_refs).map((entry) => {
    if (typeof entry.kind === "string") {
      return entry.kind;
    }
    if (typeof entry.uri === "string") {
      return entry.uri;
    }
    return JSON.stringify(entry);
  });
}

function deriveRuntimeReport(view: RuntimeReplayView, summary: TransferTrustSummary): TransferVerificationReport {
  const auditRecord = isRecord(view.audit_record) ? view.audit_record : {};
  const policyDecision = isRecord(auditRecord.policy_decision) ? auditRecord.policy_decision : {};
  const authzGraph = isRecord(view.authz_graph) ? view.authz_graph : {};
  const policyReceipt = isRecord(view.policy_receipt) ? view.policy_receipt : {};
  const evidenceBundle = isRecord(view.evidence_bundle) ? view.evidence_bundle : {};
  const approvalContext = isRecord(
    (((auditRecord.action_intent as Record<string, unknown> | undefined)?.action as Record<string, unknown> | undefined)
      ?.parameters as Record<string, unknown> | undefined)?.approval_context,
  )
    ? (((((auditRecord.action_intent as Record<string, unknown>).action as Record<string, unknown>).parameters as Record<string, unknown>).approval_context) as Record<string, unknown>)
    : {};

  const requiredApprovals = arrayOfStrings(policyDecision.required_approvals);
  const approvedBy = arrayOfStrings(approvalContext.approved_by);
  const missingPrerequisites =
    approvedBy.length >= requiredApprovals.length ? [] : requiredApprovals;
  const assetRef =
    optionalString(policyReceipt.asset_ref) ??
    optionalString((auditRecord.action_intent as Record<string, unknown> | undefined)?.resource && ((auditRecord.action_intent as Record<string, unknown>).resource as Record<string, unknown>).asset_id) ??
    optionalString(view.subject_id) ??
    "asset:unknown";
  const intentRef = optionalString(auditRecord.intent_id) ?? optionalString(view.intent_id) ?? "intent:unknown";
  const policySnapshotRef =
    optionalString(auditRecord.policy_snapshot) ?? optionalString(policyReceipt.policy_version) ?? "snapshot:runtime";
  const tokenId = optionalString(evidenceBundle.execution_token_id) ?? optionalString(auditRecord.token_id);
  const mintedArtifacts = objectArray(authzGraph.minted_artifacts).map((entry) => {
    const kind = optionalString(entry.kind);
    const ref = optionalString(entry.ref);
    if (kind && ref) {
      return `${kind}:${ref}`;
    }
    return ref ?? kind ?? JSON.stringify(entry);
  });

  return {
    verified: summary.verified,
    checks: summary.checks,
    error_code: summary.verification_error_code,
    actual_policy_evaluation: {
      disposition: summary.disposition,
      explanation: {
        trust_gaps: runtimeTrustGapCodes(view),
        missing_prerequisites: missingPrerequisites,
        matched_policy_refs: arrayOfStrings(policyReceipt.evaluated_rules),
        authority_path_summary: arrayOfStrings(authzGraph.authority_path_summary),
        minted_artifacts: mintedArtifacts,
        obligations: objectArray(authzGraph.obligations),
      },
      governed_decision_artifact: {
        decision_id:
          optionalString(policyReceipt.policy_decision_id) ??
          optionalString((policyDecision.governed_receipt as Record<string, unknown> | undefined)?.decision_hash) ??
          `decision:${intentRef}`,
        action_intent_ref: intentRef,
        policy_snapshot_ref: policySnapshotRef,
        disposition: summary.disposition,
        asset_ref: assetRef,
      },
      policy_receipt_payload: {
        policy_receipt_id: optionalString(policyReceipt.policy_receipt_id) ?? `policy:${intentRef}`,
        policy_snapshot_ref: policySnapshotRef,
        action_intent_ref: intentRef,
        disposition: summary.disposition,
      },
      execution_token_spec:
        summary.disposition === "allow"
          ? {
              intent_ref: intentRef,
              asset_ref: assetRef,
              policy_snapshot_ref: policySnapshotRef,
            }
          : null,
    },
    actual_execution_token: tokenId
      ? {
          token_id: tokenId,
          intent_id: intentRef,
          issued_at: optionalString(auditRecord.recorded_at) ?? "runtime",
          valid_until: optionalString(auditRecord.recorded_at) ?? "runtime",
          contract_version: policySnapshotRef,
        }
      : null,
  };
}

function buildRuntimeSummary(view: RuntimeReplayView): TransferTrustSummary {
  const auditRecord = isRecord(view.audit_record) ? view.audit_record : {};
  const policyDecision = isRecord(auditRecord.policy_decision) ? auditRecord.policy_decision : {};
  const verificationStatus = isRecord(view.verification_status) ? view.verification_status : {};
  const disposition = stringValue(policyDecision.disposition, "deny") as Disposition;
  const verified = verificationStatus.verified === true;
  const executionTokenPresent =
    Boolean(optionalString((view.evidence_bundle as Record<string, unknown> | undefined)?.execution_token_id)) ||
    Boolean(optionalString(auditRecord.token_id));
  return {
    verified,
    business_state: mapBusinessState(verified, disposition),
    disposition,
    approval_status: deriveRuntimeApprovalStatus(view),
    execution_token_expected: disposition === "allow",
    execution_token_present: executionTokenPresent,
    verification_error_code:
      verified || !Array.isArray(verificationStatus.issues) || verificationStatus.issues.length === 0
        ? null
        : stringValue(verificationStatus.issues[0]),
    checks: extractRuntimeChecks(view),
  };
}

export function buildRuntimeScenarioFromReplay(view: RuntimeReplayView, query: TransferSourceQuery): TransferScenario {
  const auditRecord = isRecord(view.audit_record) ? view.audit_record : {};
  const policyDecision = isRecord(auditRecord.policy_decision) ? auditRecord.policy_decision : {};
  const authzGraph = isRecord(view.authz_graph) ? view.authz_graph : {};
  const governedReceipt = isRecord(view.governed_receipt) ? view.governed_receipt : {};
  const policyReceipt = isRecord(view.policy_receipt) ? view.policy_receipt : {};
  const evidenceBundle = isRecord(view.evidence_bundle) ? view.evidence_bundle : {};
  const approvalContext = isRecord(
    (((auditRecord.action_intent as Record<string, unknown> | undefined)?.action as Record<string, unknown> | undefined)
      ?.parameters as Record<string, unknown> | undefined)?.approval_context,
  )
    ? (((((auditRecord.action_intent as Record<string, unknown>).action as Record<string, unknown>).parameters as Record<string, unknown>).approval_context) as Record<string, unknown>)
    : {};
  const resource = isRecord((auditRecord.action_intent as Record<string, unknown> | undefined)?.resource)
    ? ((auditRecord.action_intent as Record<string, unknown>).resource as Record<string, unknown>)
    : {};
  const categoryEnvelope = isRecord(resource.category_envelope) ? (resource.category_envelope as Record<string, unknown>) : {};
  const transferContext = isRecord(categoryEnvelope.transfer_context) ? (categoryEnvelope.transfer_context as Record<string, unknown>) : {};
  const assetCustodyState = isRecord(view.asset_custody_state) ? view.asset_custody_state : {};
  const approvalEnvelopeId =
    optionalString(governedReceipt.approval_envelope_id) ??
    optionalString(authzGraph.approval_envelope_id) ??
    optionalString(approvalContext.approval_envelope_id) ??
    null;
  const approvalEnvelopeVersion =
    optionalNumber(governedReceipt.approval_envelope_version) ??
    optionalNumber(authzGraph.approval_envelope_version) ??
    optionalNumber(approvalContext.approval_envelope_version ?? approvalContext.observed_version) ??
    null;
  const approvalBindingHash =
    optionalString(governedReceipt.approval_binding_hash) ??
    optionalString(authzGraph.approval_binding_hash) ??
    optionalString(approvalContext.approval_binding_hash) ??
    null;
  const transitionReceiptIds = (() => {
    const fromEvidence = arrayOfStrings(evidenceBundle.transition_receipt_ids);
    if (fromEvidence.length > 0) {
      return fromEvidence;
    }
    return objectArray(view.transition_receipts)
      .map((entry) => optionalString(entry.transition_receipt_id))
      .filter((entry): entry is string => Boolean(entry));
  })();
  const summary = buildRuntimeSummary(view);
  const report = deriveRuntimeReport(view, summary);
  const transferLookup = deriveRuntimeTransferLookup(view, query);
  const forensicLookup = deriveRuntimeForensicLookup(view, query);
  const links = buildStatusLinks(transferLookup);
  const forensicLinks = buildForensicLinks(transferLookup);
  const publicTrustUrl = extractPublicTrustUrl(view);
  const verifyUrl = optionalString(view.verification_ref);
  const replayArtifacts = replayArtifactsUrl(forensicLookup);

  const status = toTransferStatusView(report, summary, {
    approval_envelope_id: approvalEnvelopeId,
    approval_envelope_version: approvalEnvelopeVersion,
    approval_binding_hash: approvalBindingHash,
    policy_receipt_id:
      optionalString(policyReceipt.policy_receipt_id) ?? optionalString(evidenceBundle.policy_receipt_id) ?? null,
    transition_receipt_ids: transitionReceiptIds,
    pending_roles:
      summary.approval_status === "APPROVED" ? [] : arrayOfStrings(policyDecision.required_approvals),
    timeline: runtimeTimeline(view),
    current_step: optionalString(authzGraph.workflow_status),
    principal_identity: {
      requesting_principal_ref:
        optionalString((policyDecision.governed_receipt as Record<string, unknown> | undefined)?.principal_ref) ??
        optionalString(auditRecord.actor_agent_id) ??
        "unknown",
      approving_principal_refs: arrayOfStrings(approvalContext.approved_by),
      next_custodian_ref: optionalString(transferContext.next_custodian) ?? null,
    },
    custody_transition: {
      from_zone:
        optionalString(transferContext.from_zone) ??
        optionalString((view.transition_receipts?.[0] as Record<string, unknown> | undefined)?.from_zone) ??
        "unknown",
      to_zone:
        optionalString(transferContext.to_zone) ??
        optionalString((view.transition_receipts?.[0] as Record<string, unknown> | undefined)?.to_zone) ??
        "unknown",
      facility_ref: optionalString(transferContext.facility_ref) ?? "unknown",
      custody_point_ref:
        optionalString(transferContext.custody_point_ref) ??
        optionalString(assetCustodyState.custody_point_ref) ??
        "unknown",
      expected_current_custodian:
        optionalString(transferContext.expected_current_custodian) ??
        optionalString(assetCustodyState.current_custodian_ref) ??
        "unknown",
      next_custodian: optionalString(transferContext.next_custodian) ?? "unknown",
    },
    telemetry_refs: runtimeTelemetryRefs(view),
    signature_provenance: runtimeSignatureProvenance(view),
    asset_custody_state: {
      current_custodian_ref: optionalString(assetCustodyState.current_custodian_ref) ?? null,
      current_zone_ref: optionalString(assetCustodyState.current_zone_ref ?? assetCustodyState.current_zone) ?? null,
      custody_point_ref: optionalString(assetCustodyState.custody_point_ref) ?? null,
      authority_source: optionalString(assetCustodyState.authority_source) ?? null,
    },
    replay_artifacts_url: replayArtifacts,
    public_trust_url: publicTrustUrl,
    verify_url: verifyUrl,
  });

  const assetForensics = toAssetForensicView(report, summary, {
    approval_envelope_id: approvalEnvelopeId,
    approval_envelope_version: approvalEnvelopeVersion,
    approval_binding_hash: approvalBindingHash,
    policy_receipt_id:
      optionalString(policyReceipt.policy_receipt_id) ?? optionalString(evidenceBundle.policy_receipt_id) ?? null,
    transition_receipt_ids: transitionReceiptIds,
    timeline: runtimeTimeline(view),
    principal_identity: {
      requesting_principal_ref:
        optionalString((policyDecision.governed_receipt as Record<string, unknown> | undefined)?.principal_ref) ??
        optionalString(auditRecord.actor_agent_id) ??
        "unknown",
      approving_principal_refs: arrayOfStrings(approvalContext.approved_by),
      next_custodian_ref: optionalString(transferContext.next_custodian) ?? null,
    },
    custody_transition: {
      from_zone:
        optionalString(transferContext.from_zone) ??
        optionalString((view.transition_receipts?.[0] as Record<string, unknown> | undefined)?.from_zone) ??
        "unknown",
      to_zone:
        optionalString(transferContext.to_zone) ??
        optionalString((view.transition_receipts?.[0] as Record<string, unknown> | undefined)?.to_zone) ??
        "unknown",
      facility_ref: optionalString(transferContext.facility_ref) ?? "unknown",
      custody_point_ref:
        optionalString(transferContext.custody_point_ref) ??
        optionalString(assetCustodyState.custody_point_ref) ??
        "unknown",
      expected_current_custodian:
        optionalString(transferContext.expected_current_custodian) ??
        optionalString(assetCustodyState.current_custodian_ref) ??
        "unknown",
      next_custodian: optionalString(transferContext.next_custodian) ?? "unknown",
    },
    telemetry_refs: runtimeTelemetryRefs(view),
    signature_provenance: runtimeSignatureProvenance(view),
    asset_custody_state: {
      current_custodian_ref: optionalString(assetCustodyState.current_custodian_ref) ?? null,
      current_zone_ref: optionalString(assetCustodyState.current_zone_ref ?? assetCustodyState.current_zone) ?? null,
      custody_point_ref: optionalString(assetCustodyState.custody_point_ref) ?? null,
      authority_source: optionalString(assetCustodyState.authority_source) ?? null,
    },
    replay_artifacts_url: replayArtifacts,
    public_trust_url: publicTrustUrl,
    verify_url: verifyUrl,
  });

  status.links = { ...status.links, ...links };
  assetForensics.links = { ...assetForensics.links, ...forensicLinks };

  return {
    summary,
    transfer_proof: toTransferProofView(report, summary, {
      approval_envelope_id: approvalEnvelopeId,
      approval_envelope_version: approvalEnvelopeVersion,
      approval_binding_hash: approvalBindingHash,
      policy_receipt_id:
        optionalString(policyReceipt.policy_receipt_id) ?? optionalString(evidenceBundle.policy_receipt_id) ?? null,
      transition_receipt_ids: transitionReceiptIds,
    }),
    asset_proof: toAssetProofView(report, summary),
    status,
    asset_forensics: assetForensics,
  };
}

async function fetchRuntimeReplayView(
  query: TransferSourceQuery,
  allowedLookupKeys: RuntimeLookupKey[],
): Promise<RuntimeReplayView> {
  const [key, value] = assertSingleLookup(query, allowedLookupKeys);
  const params = new URLSearchParams();
  params.set(key, value);
  if (key === "subject_id") {
    params.set("subject_type", "asset");
  }
  params.set("projection", "internal");
  const payload = await fetchRuntimeJson(`/replay?${params.toString()}`);
  if (!isRecord(payload) || !isRecord(payload.view)) {
    throw new Error("invalid_runtime_replay_payload");
  }
  return payload.view as RuntimeReplayView;
}

async function fetchRuntimeReplayViewForAsset(query: TransferSourceQuery): Promise<RuntimeReplayView> {
  return fetchRuntimeReplayView(query, FORENSIC_RUNTIME_LOOKUP_KEYS);
}

export async function buildTransferScenario(query: TransferSourceQuery): Promise<TransferScenario> {
  if (query.source === "fixture") {
    return buildFixtureScenario(query);
  }

  const view = await fetchRuntimeReplayView(query, TRANSFER_RUNTIME_LOOKUP_KEYS);
  return buildRuntimeScenarioFromReplay(view, query);
}

export async function buildAssetScenario(query: TransferSourceQuery): Promise<TransferScenario> {
  if (query.source === "fixture") {
    return buildFixtureScenario(query);
  }

  const view = await fetchRuntimeReplayViewForAsset(query);
  return buildRuntimeScenarioFromReplay(view, query);
}

export async function listTransferCatalog(query: TransferSourceQuery): Promise<TransferCatalogItem[]> {
  if (query.source === "runtime") {
    const scenario = await buildTransferScenario(query);
    return [
      {
        id: query.audit_id ?? query.intent_id ?? "runtime-transfer",
        source: "runtime",
        query: buildQueryString(query),
        summary: scenario.summary,
        status_preview: {
          transfer_readiness: scenario.status.transfer_readiness,
          current_step: scenario.status.current_step,
          top_blocker: scenario.status.blocker_codes[0] ?? null,
        },
        links: {
          status: `/api/v1/transfers/status?${buildQueryString(query)}`,
          review: `/api/v1/transfers/review?${buildQueryString(query)}`,
          asset_forensics: `/api/v1/assets/forensics?${buildQueryString(query)}`,
        },
      },
    ];
  }

  const root = resolveTransferRoot(query.root);
  if (!existsSync(root)) {
    return [];
  }

  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort()
    .map((id) => {
      const dir = path.join(root, id);
      const scenario = buildFixtureScenario({ source: "fixture", dir });
      return {
        id,
        dir,
        source: "fixture" as const,
        query: buildQueryString({ source: "fixture", dir }),
        summary: scenario.summary,
        status_preview: {
          transfer_readiness: scenario.status.transfer_readiness,
          current_step: scenario.status.current_step,
          top_blocker: scenario.status.blocker_codes[0] ?? null,
        },
        links: {
          status: `/api/v1/transfers/status?${buildQueryString({ source: "fixture", dir })}`,
          review: `/api/v1/transfers/review?${buildQueryString({ source: "fixture", dir })}`,
          asset_forensics: `/api/v1/assets/forensics?${buildQueryString({ source: "fixture", dir })}`,
        },
      };
    });
}

export function resolveSourceMode(rawSource: string | null): TransferSourceMode {
  return rawSource === "runtime" ? "runtime" : "fixture";
}

export function parseTransferQuery(url: URL): TransferSourceQuery {
  return {
    source: resolveSourceMode(url.searchParams.get("source")),
    dir: url.searchParams.get("dir") ?? undefined,
    root: url.searchParams.get("root") ?? undefined,
    audit_id: url.searchParams.get("audit_id") ?? undefined,
    intent_id: url.searchParams.get("intent_id") ?? undefined,
    subject_id: url.searchParams.get("subject_id") ?? undefined,
  };
}

export function summarizeScenarioState(summary: TransferTrustSummary): {
  business_state: BusinessState;
  disposition: Disposition;
} {
  return {
    business_state: summary.business_state,
    disposition: summary.disposition,
  };
}
