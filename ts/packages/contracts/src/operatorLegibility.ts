/**
 * Deterministic operator-legibility helpers (facts from projections; no LLM).
 * Used by verification queue rows and the operator console HTML surface.
 */

import type { AssetForensicProjection, TransferAuditTrail, VerificationSurfaceProjection } from "./verificationSurfaceContracts.js";

export type ReplayVerdict = "consistent" | "inconsistent" | "incomplete";

export interface CaseVerdictHeader {
  decision: string;
  risk: string;
  confidence: string;
  next_action: string;
}

export interface OperatorQueueSignals {
  priority_score: number;
  correlation_flags: string[];
}

/** Stable read-only copilot-shaped payload (deterministic stub and optional LLM). */
export interface OperatorCopilotBriefV1 {
  contract_version: "seedcore.operator_copilot_brief.v0";
  case_id: string;
  decision: string;
  current_status: string;
  why: string;
  evidence_completeness: "complete" | "partial" | "gaps";
  verification_status: string;
  anomalies: string[];
  recommended_action: string;
  audit_note: string;
  /** Calibrated language (e.g. low | medium | high); always set for LLM output. */
  confidence: string;
  /** Non-empty for LLM: explicit unknowns, limits of evidence, or model limits. */
  uncertainty_notes: string[];
  one_line_summary: string;
  operator_brief_bullets: string[];
  /** Grounded in source fields — show as “fact” in UI */
  facts: string[];
  /** Derived heuristics — show as “inference” in UI */
  inferences: string[];
  /** Every claim should be traceable; LLM responses must include ≥1 citation with non-empty path and value. */
  citations: Array<{ path: string; value: string }>;
  generation_mode: "deterministic" | "llm";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Validate parsed JSON for LLM path: citations + uncertainty + confidence required. */
export function validateOperatorCopilotBriefForLlm(
  value: unknown,
): { ok: true; brief: OperatorCopilotBriefV1 } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  if (!isRecord(value)) {
    return { ok: false, errors: ["root must be object"] };
  }
  if (value.contract_version !== "seedcore.operator_copilot_brief.v0") {
    errors.push("contract_version must be seedcore.operator_copilot_brief.v0");
  }
  if (value.generation_mode !== "llm") {
    errors.push("generation_mode must be \"llm\"");
  }
  const str = (k: string) => (typeof value[k] === "string" ? (value[k] as string) : "");
  const strArr = (k: string) => (Array.isArray(value[k]) ? (value[k] as unknown[]).filter((x): x is string => typeof x === "string") : []);
  if (!str("case_id").trim()) {
    errors.push("case_id required");
  }
  if (!str("confidence").trim()) {
    errors.push("confidence required (non-empty string; express calibration explicitly)");
  }
  if (!str("one_line_summary").trim()) {
    errors.push("one_line_summary required");
  }
  const unc = strArr("uncertainty_notes").filter((s) => s.trim().length > 0);
  if (unc.length < 1) {
    errors.push(
      "uncertainty_notes required: at least one non-empty string (known unknowns, evidence gaps, or model limits)",
    );
  }
  const citationsRaw = Array.isArray(value.citations) ? value.citations : [];
  const citations: Array<{ path: string; value: string }> = [];
  for (const c of citationsRaw) {
    if (!isRecord(c)) {
      continue;
    }
    const p = typeof c.path === "string" ? c.path.trim() : "";
    const v = typeof c.value === "string" ? c.value.trim() : "";
    if (p && v) {
      citations.push({ path: p, value: v });
    }
  }
  if (citations.length < 1) {
    errors.push("citations required: at least one { path, value } with non-empty strings");
  }
  const evidence = str("evidence_completeness");
  if (evidence !== "complete" && evidence !== "partial" && evidence !== "gaps") {
    errors.push("evidence_completeness must be complete | partial | gaps");
  }
  const bullets = strArr("operator_brief_bullets").filter((s) => s.trim().length > 0);
  if (bullets.length < 1) {
    errors.push("operator_brief_bullets required: at least one non-empty string");
  }
  const facts = strArr("facts").filter((s) => s.trim().length > 0);
  if (facts.length < 1) {
    errors.push("facts required: at least one grounded string tied to CONTEXT_JSON fields");
  }
  const inferences = strArr("inferences").filter((s) => s.trim().length > 0);
  if (inferences.length < 1) {
    errors.push("inferences required: at least one explicitly labeled non-authoritative inference");
  }
  if (errors.length > 0) {
    return { ok: false, errors };
  }
  const brief: OperatorCopilotBriefV1 = {
    contract_version: "seedcore.operator_copilot_brief.v0",
    case_id: str("case_id").trim(),
    decision: str("decision"),
    current_status: str("current_status"),
    why: str("why"),
    evidence_completeness: evidence as "complete" | "partial" | "gaps",
    verification_status: str("verification_status"),
    anomalies: strArr("anomalies"),
    recommended_action: str("recommended_action"),
    audit_note: str("audit_note"),
    confidence: str("confidence").trim(),
    uncertainty_notes: unc,
    one_line_summary: str("one_line_summary").trim(),
    operator_brief_bullets: bullets.slice(0, 8),
    facts,
    inferences,
    citations,
    generation_mode: "llm",
  };
  return { ok: true, brief };
}

export function computeQueueCorrelationFlags(input: {
  business_state: string;
  disposition: string;
  trust_bucket: string;
  replay_readiness: string;
  trust_alerts: string[];
}): string[] {
  const flags: string[] = [];
  if (input.business_state === "verified" && input.disposition !== "allow") {
    flags.push("verified_business_state_vs_non_allow_disposition");
  }
  if (input.trust_bucket === "verified" && (input.business_state === "quarantined" || input.business_state === "rejected")) {
    flags.push("trust_bucket_green_vs_negative_business_state");
  }
  if (input.business_state === "verified" && input.replay_readiness === "pending") {
    flags.push("verified_but_replay_not_ready");
  }
  if (input.trust_alerts.includes("replay_not_ready") && input.business_state === "verified") {
    flags.push("trust_alert_replay_not_ready_under_verified");
  }
  return flags;
}

export function computeQueuePriorityScore(input: {
  business_state: string;
  transfer_readiness: string;
  trust_alerts: string[];
  correlation_flags: string[];
  top_blocker: string | null;
}): number {
  let score = 0;
  const bs = input.business_state;
  if (bs === "review_required") {
    score += 100;
  }
  if (bs === "quarantined") {
    score += 95;
  }
  if (bs === "rejected") {
    score += 90;
  }
  if (bs === "pending_approval") {
    score += 55;
  }
  if (bs === "verified") {
    score += 5;
  }
  if (input.transfer_readiness === "blocked") {
    score += 45;
  }
  score += Math.min(40, input.trust_alerts.length * 12);
  score += Math.min(30, input.correlation_flags.length * 15);
  if (input.top_blocker) {
    score += 20;
  }
  return score;
}

export function deriveReplayVerdict(input: {
  projection_status: string;
  signature_valid: boolean;
  tamper_status: string;
  policy_trace_available: boolean;
  evidence_trace_available: boolean;
  receipt_steps_ok: boolean;
  replay_verifiable: boolean;
  terminal_disposition: string;
  failure_active: boolean;
}): ReplayVerdict {
  if (!input.receipt_steps_ok || !input.replay_verifiable) {
    return "incomplete";
  }
  if (input.projection_status === "pending_approval") {
    return "incomplete";
  }
  if (!input.signature_valid && input.projection_status === "verified") {
    return "inconsistent";
  }
  if (input.tamper_status !== "clear" && input.projection_status === "verified") {
    return "inconsistent";
  }
  if (input.projection_status === "verified" && (input.terminal_disposition === "deny" || input.terminal_disposition === "quarantine")) {
    return "inconsistent";
  }
  if (input.failure_active && input.terminal_disposition === "allow" && input.projection_status === "verified") {
    return "inconsistent";
  }
  if (!input.policy_trace_available || !input.evidence_trace_available) {
    return "incomplete";
  }
  return "consistent";
}

export function deriveCaseVerdictHeader(
  projection: VerificationSurfaceProjection,
  audit: TransferAuditTrail,
  forensics: AssetForensicProjection,
): CaseVerdictHeader {
  const disposition = audit.decision.disposition;
  const allowed = audit.decision.allowed;
  const decision = `${disposition}${allowed ? " (allowed)" : " (not allowed)"}`;
  const bs = projection.status;
  let risk = "medium";
  if (bs === "quarantined" || bs === "rejected" || forensics.trust_gaps.length > 0) {
    risk = "high";
  } else if (bs === "verified" && forensics.trust_gaps.length === 0) {
    risk = "low";
  } else if (bs === "pending_approval" || bs === "review_required") {
    risk = "medium";
  }
  const traces =
    projection.verification.policy_trace_available && projection.verification.evidence_trace_available;
  const sig = projection.verification.signature_valid && projection.verification.tamper_status === "clear";
  let confidence = "medium";
  if (traces && sig) {
    confidence = "high";
  }
  if (!projection.verification.signature_valid || projection.verification.tamper_status !== "clear") {
    confidence = "low";
  }
  let next_action = "Review governed timeline and linked JSON contracts.";
  if (bs === "review_required") {
    next_action = "Escalate per runbook; capture human decision and prerequisites.";
  } else if (bs === "quarantined") {
    next_action = "Hold movement; inspect trust gaps and forensic fingerprint.";
  } else if (bs === "rejected") {
    next_action = "Confirm denial reason with policy snapshot and scope verdict.";
  } else if (bs === "pending_approval") {
    next_action = "Complete approval envelope; monitor replay readiness.";
  } else if (bs === "verified") {
    next_action = "Optional deep verification: open replay bundle and receipt chain.";
  }
  return { decision, risk, confidence, next_action };
}

/** When verification-detail omits nested audit/forensics (partial test payloads). */
export function deriveCaseVerdictFromProjectionOnly(projection: VerificationSurfaceProjection): CaseVerdictHeader {
  const decision = `${projection.authorization.disposition} (projection-only)`;
  let risk = "medium";
  if (projection.status === "quarantined" || projection.status === "rejected") {
    risk = "high";
  } else if (projection.status === "verified") {
    risk = "low";
  }
  const confidence = projection.verification.signature_valid && projection.verification.tamper_status === "clear"
    ? "medium"
    : "low";
  return {
    decision,
    risk,
    confidence,
    next_action: "Fetch full verification-detail with transfer_audit_trail and asset_forensic_projection for authoritative verdict.",
  };
}

export function buildDeterministicCopilotBriefFromProjectionOnly(
  workflowId: string,
  projection: VerificationSurfaceProjection,
  replayVerdict?: ReplayVerdict,
  correlationFlags?: string[],
): OperatorCopilotBriefV1 {
  const header = deriveCaseVerdictFromProjectionOnly(projection);
  return {
    contract_version: "seedcore.operator_copilot_brief.v0",
    case_id: workflowId,
    decision: header.decision,
    current_status: projection.status,
    why: "Partial payload: copilot grounded on verification_projection only.",
    evidence_completeness: projection.verification.policy_trace_available ? "partial" : "gaps",
    verification_status: `${projection.verification.tamper_status}; signature ${projection.verification.signature_valid}`,
    anomalies: [...(correlationFlags ?? [])],
    recommended_action: header.next_action,
    audit_note: "Incomplete detail body: expand audit trail + forensics for full copilot citations.",
    confidence: header.confidence,
    one_line_summary: `${projection.status.toUpperCase()} · ${projection.authorization.disposition} · ${projection.asset_ref}`,
    operator_brief_bullets: [
      `Workflow ${workflowId} — projection status ${projection.status}.`,
      `Disposition ${projection.authorization.disposition} on projection surface.`,
      replayVerdict ? `Replay verdict (deterministic): ${replayVerdict}.` : "Open replay for receipt-chain verdict.",
      `Signature valid: ${String(projection.verification.signature_valid)}.`,
      "Load JSON verification-detail for audit trail and forensic binds.",
    ],
    facts: [
      `verification_projection.status=${projection.status}`,
      `verification.authorization.disposition=${projection.authorization.disposition}`,
    ],
    inferences: ["Risk band from projection-only view (heuristic)."],
    citations: [
      { path: "verification_projection.status", value: projection.status },
      { path: "verification_projection.asset_ref", value: projection.asset_ref },
    ],
    generation_mode: "deterministic",
    uncertainty_notes: [
      "No LLM: parser-derived from verification_projection only; load full audit trail and forensics for authoritative review.",
    ],
  };
}

export function deriveCaseVerdictFromForensicsOnly(forensics: AssetForensicProjection): CaseVerdictHeader {
  const decision = `${forensics.disposition} · ${forensics.decision_id}`;
  let risk = "medium";
  if (forensics.trust_gaps.length > 0 || forensics.business_state === "quarantined" || forensics.business_state === "rejected") {
    risk = "high";
  } else if (forensics.business_state === "verified" && forensics.disposition === "allow") {
    risk = "low";
  }
  const confidence = forensics.signer_provenance.length > 0 ? "medium" : "low";
  let next_action = "Cross-check transfer audit trail and workflow projection via links below.";
  if (forensics.trust_gaps.length > 0) {
    next_action = "Resolve trust gaps before clearing custody movement.";
  } else if (forensics.missing_prerequisites.length > 0) {
    next_action = "Satisfy missing prerequisites; re-run verification.";
  }
  return { decision, risk, confidence, next_action };
}

export function deriveReplayCorrelationFlags(input: {
  projection_status: string;
  terminal_disposition: string;
  failure_active: boolean;
  failure_path: string;
}): string[] {
  const flags: string[] = [];
  if (
    input.projection_status === "verified"
    && (input.terminal_disposition === "deny" || input.terminal_disposition === "quarantine")
  ) {
    flags.push("projection_verified_vs_terminal_negative_disposition");
  }
  if (input.failure_active && input.failure_path === "allow") {
    flags.push("failure_panel_active_on_allow_path");
  }
  return flags;
}

export function buildDeterministicCopilotBrief(input: {
  workflow_id: string;
  projection: VerificationSurfaceProjection;
  audit: TransferAuditTrail;
  forensics: AssetForensicProjection;
  correlation_flags?: string[];
  replay_verdict?: ReplayVerdict;
}): OperatorCopilotBriefV1 {
  const { projection: p, audit: a, forensics: f } = input;
  const header = deriveCaseVerdictHeader(p, a, f);
  const anomalies = [...(input.correlation_flags ?? []), ...f.trust_gaps.slice(0, 5)];
  const evidence_complete =
    p.verification.policy_trace_available && p.verification.evidence_trace_available && p.verification.signature_valid
      ? "complete"
      : p.verification.policy_trace_available || p.verification.evidence_trace_available
        ? "partial"
        : "gaps";
  const why = `Status ${p.status} with disposition ${a.decision.disposition}; approval ${p.summary.approval_state}.`;
  const bullets = [
    `Workflow ${input.workflow_id} — asset ${p.asset_ref}.`,
    `Governed decision: ${a.decision.reason_code} (${a.decision.disposition}).`,
    `Signatures: ${p.verification.signature_valid ? "valid" : "invalid"}; tamper: ${p.verification.tamper_status}.`,
    `Traces — policy: ${p.verification.policy_trace_available}, evidence: ${p.verification.evidence_trace_available}.`,
    input.replay_verdict ? `Replay verdict (deterministic): ${input.replay_verdict}.` : "Open replay view for receipt-chain verdict.",
  ];
  const facts = [
    `verification_projection.status=${p.status}`,
    `transfer_audit_trail.decision.disposition=${a.decision.disposition}`,
    `verification.signature_valid=${String(p.verification.signature_valid)}`,
    `verification.tamper_status=${p.verification.tamper_status}`,
  ];
  const inferences = [
    header.risk === "high"
      ? "Elevated risk inferred from status and/or trust gaps (heuristic)."
      : "Risk band from business state + trust gap presence (heuristic).",
    input.replay_verdict === "inconsistent"
      ? "Replay chain contradicts optimistic read (heuristic)."
      : "Replay alignment not flagged as inconsistent by deterministic check.",
  ];
  const citations = [
    { path: "verification_projection.status", value: p.status },
    { path: "transfer_audit_trail.decision.reason_code", value: a.decision.reason_code },
    { path: "asset_forensic_projection.trust_gaps.length", value: String(f.trust_gaps.length) },
  ];
  return {
    contract_version: "seedcore.operator_copilot_brief.v0",
    case_id: input.workflow_id,
    decision: header.decision,
    current_status: p.status,
    why,
    evidence_completeness: evidence_complete,
    verification_status: `${p.verification.tamper_status}; traces policy/evidence as reported`,
    anomalies,
    recommended_action: header.next_action,
    audit_note:
      "MVP stub: deterministic only; no model. Replace with cited LLM output in later phase; never mutate state from this channel.",
    confidence: header.confidence,
    uncertainty_notes: [
      "No LLM: heuristic risk band and replay alignment flags; operator must confirm against raw JSON contracts.",
    ],
    one_line_summary: `${p.status.toUpperCase()} · ${a.decision.disposition} · ${p.asset_ref}`,
    operator_brief_bullets: bullets,
    facts,
    inferences,
    citations,
    generation_mode: "deterministic",
  };
}

/** Forensics-only surface: partial copilot stub until transfer projection is loaded. */
export function buildDeterministicCopilotBriefFromForensics(forensics: AssetForensicProjection): OperatorCopilotBriefV1 {
  const header = deriveCaseVerdictFromForensicsOnly(forensics);
  const bullets = [
    `Workflow ${forensics.workflow_id} — asset ${forensics.asset_ref}.`,
    `Forensic disposition: ${forensics.disposition}; business state: ${forensics.business_state}.`,
    `Trust gaps: ${forensics.trust_gaps.length}; missing prerequisites: ${forensics.missing_prerequisites.length}.`,
    `Policy snapshot: ${forensics.policy_snapshot_ref}.`,
    "Open transfer detail for full verification projection + audit trail copilot.",
  ];
  return {
    contract_version: "seedcore.operator_copilot_brief.v0",
    case_id: forensics.workflow_id,
    decision: header.decision,
    current_status: forensics.business_state,
    why: `Forensics projection only; disposition ${forensics.disposition}.`,
    evidence_completeness: forensics.forensic_fingerprint.economic_hash ? "partial" : "gaps",
    verification_status: `Signer entries: ${forensics.signer_provenance.length}`,
    anomalies: [...forensics.trust_gaps],
    recommended_action: header.next_action,
    audit_note:
      "Partial view: deterministic stub from asset_forensic_projection only; expand via transfer/replay surfaces.",
    confidence: header.confidence,
    uncertainty_notes: [
      "No LLM: forensic projection slice only; workflow projection and audit trail may add contradicting context.",
    ],
    one_line_summary: `${forensics.business_state.toUpperCase()} · ${forensics.disposition} · ${forensics.asset_ref}`,
    operator_brief_bullets: bullets,
    facts: [
      `asset_forensic_projection.business_state=${forensics.business_state}`,
      `asset_forensic_projection.disposition=${forensics.disposition}`,
      `asset_forensic_projection.trust_gaps.length=${String(forensics.trust_gaps.length)}`,
    ],
    inferences: [
      header.risk === "high" ? "High risk band from forensic trust gaps or negative state (heuristic)." : "Medium/low risk from forensic summary (heuristic).",
    ],
    citations: [
      { path: "asset_forensic_projection.workflow_id", value: forensics.workflow_id },
      { path: "asset_forensic_projection.decision_id", value: forensics.decision_id },
    ],
    generation_mode: "deterministic",
  };
}
