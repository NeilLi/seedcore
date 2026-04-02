/**
 * Operator runbooks for verification / replay failure panels (JSON contract, not markdown).
 */

export interface RunbookRef {
  slug: string;
  title: string;
  /** Path-only href under verification API (caller prefixes base URL). */
  href_path: string;
}

export interface RunbookEntry {
  slug: string;
  title: string;
  summary: string;
  steps: string[];
  related_reason_codes: string[];
}

const RUNBOOKS: Record<string, RunbookEntry> = {
  operator_transfer_overview: {
    slug: "operator_transfer_overview",
    title: "Restricted custody transfer — operator overview",
    summary: "How queue, audit trail, forensics, and replay views relate for Screen 1–4.",
    steps: [
      "Open the transfer queue to see trust bucket, approval state, and blockers.",
      "Drill into transfer review (Screen 2) for request + decision + physical evidence.",
      "Use asset forensics for four-class fingerprint hashes and custody context.",
      "Use verification replay for receipt-chain checkpoints and failure panels.",
    ],
    related_reason_codes: [],
  },
  policy_denied: {
    slug: "policy_denied",
    title: "Policy denied terminal path",
    summary: "Disposition deny: verify scope, approvals, and policy snapshot before retry.",
    steps: [
      "Confirm authority_scope verdict and mismatch_keys on the audit trail.",
      "Verify approval envelope status matches required roles.",
      "Compare policy_snapshot_ref to the active compiled graph in runtime.",
    ],
    related_reason_codes: ["policy_denied", "restricted_custody_transfer_denied"],
  },
  trust_gap_quarantine: {
    slug: "trust_gap_quarantine",
    title: "Trust gap / quarantine",
    summary: "Quarantine indicates missing prerequisites, stale telemetry, or graph readiness gaps.",
    steps: [
      "Review trust_gaps and missing_prerequisites on the forensic projection.",
      "Check hot-path status for graph_freshness_ok and authz_graph_ready.",
      "If telemetry-driven, confirm edge sensor freshness and signing chain.",
    ],
    related_reason_codes: ["trust_gap_quarantine", "hot_path_dependency_unavailable", "compiled_authz_graph_stale"],
  },
  missing_prerequisites: {
    slug: "missing_prerequisites",
    title: "Missing prerequisites / blocked readiness",
    summary: "Transfer readiness blocked until dual approval or other gates clear.",
    steps: [
      "Inspect blocker_codes on the status view.",
      "Complete pending approvals or escalate per governance policy.",
      "Re-run verification after coordinator records updated approval envelope.",
    ],
    related_reason_codes: ["missing_dual_approval", "missing_prerequisite"],
  },
  hot_path_rollback: {
    slug: "hot_path_rollback",
    title: "Hot-path rollback or promotion gate",
    summary: "Runtime observability flagged false-positive allow, SLO breach, or dependency drift.",
    steps: [
      "GET /api/v1/pdp/hot-path/status and read observability.alert_level and rollback_reasons.",
      "Do not promote to enforce while rollback_triggered is true.",
      "Investigate recent_mismatch_count and parity JSONL artifacts.",
    ],
    related_reason_codes: [],
  },
  stale_telemetry: {
    slug: "stale_telemetry",
    title: "Stale telemetry or freshness violation",
    summary: "Telemetry age exceeded policy; quarantine is the governed outcome until fresh evidence lands.",
    steps: [
      "Compare telemetry_context freshness_seconds to max_allowed_age_seconds on the audit trail request card.",
      "Validate edge clock skew and ingestion lag; capture a new signed telemetry envelope.",
      "Re-run hot-path evaluation after freshness is within SLO; confirm trust_alerts clear on the queue row.",
    ],
    related_reason_codes: ["stale_telemetry", "telemetry_freshness", "freshness"],
  },
  authority_scope_mismatch: {
    slug: "authority_scope_mismatch",
    title: "Authority / coordinate / asset scope mismatch",
    summary: "Intent asset, zones, or coordinates do not match the scoped authority graph (deny path).",
    steps: [
      "Read authority_scope.mismatch_keys and authority_scope_verdict on Screen 2.",
      "Verify asset_ref and product_ref align across action_intent, asset_context, and custody transition.",
      "If coordinates are in scope, confirm expected_coordinate_ref matches physical evidence refs.",
    ],
    related_reason_codes: [
      "asset_custody_mismatch",
      "authority_scope_mismatch",
      "coordinate_scope_mismatch",
      "asset_product_scope_mismatch",
    ],
  },
  snapshot_not_ready: {
    slug: "snapshot_not_ready",
    title: "Policy snapshot skew / graph not ready",
    summary: "Request snapshot_ref does not match the active compiled authorization graph.",
    steps: [
      "Compare decision.policy_snapshot_ref to GET /api/v1/pkg/status active_version.",
      "Activate the expected rules snapshot or resubmit the transfer with the active snapshot ref.",
      "Confirm authz graph compiled_at and graph_freshness_ok before retrying evaluation.",
    ],
    related_reason_codes: ["snapshot_not_ready", "snapshot_skew", "hot_path_dependency_unavailable"],
  },
};

export function listRunbookSummaries(): Array<{ slug: string; title: string }> {
  return Object.values(RUNBOOKS).map((r) => ({ slug: r.slug, title: r.title }));
}

export function getRunbook(slug: string): RunbookEntry | null {
  const key = slug.trim();
  return RUNBOOKS[key] ?? null;
}

function refFor(slug: string): RunbookRef | null {
  const entry = RUNBOOKS[slug];
  if (!entry) {
    return null;
  }
  return { slug: entry.slug, title: entry.title, href_path: `/api/v1/verification/runbook/${encodeURIComponent(entry.slug)}` };
}

/** Lookup runbooks by exception fields (Q2 spec: runbooks by status/reason). */
export function lookupRunbooksForQuery(args: {
  reason_code?: string;
  disposition?: string;
  business_state?: string;
  blockers?: string[];
}): RunbookRef[] {
  const rc = (args.reason_code ?? "").toLowerCase();
  let disposition = args.disposition ?? "allow";
  let business_state = args.business_state ?? "verified";
  if (!args.disposition) {
    if (rc.includes("quarantine") || rc.includes("trust_gap") || rc.includes("stale")) {
      disposition = "quarantine";
      business_state = args.business_state ?? "quarantined";
    } else if (rc.includes("deny") || rc.includes("policy_denied") || rc.includes("missing")) {
      disposition = "deny";
      business_state = args.business_state ?? "rejected";
    }
  }
  return resolveRunbookLinks({
    reason_code: args.reason_code ?? "",
    disposition,
    business_state,
    blockers: args.blockers ?? [],
  });
}

export function resolveRunbookLinks(args: {
  reason_code: string;
  disposition: string;
  business_state: string;
  blockers: string[];
}): RunbookRef[] {
  const out: RunbookRef[] = [];
  const seen = new Set<string>();
  const push = (slug: string) => {
    const r = refFor(slug);
    if (r && !seen.has(r.slug)) {
      seen.add(r.slug);
      out.push(r);
    }
  };

  push("operator_transfer_overview");

  const rc = args.reason_code.toLowerCase();
  const disp = args.disposition.toLowerCase();
  const bs = args.business_state.toLowerCase();

  if (disp === "deny" || bs === "rejected") {
    push("policy_denied");
  }
  if (disp === "quarantine" || bs === "quarantined") {
    push("trust_gap_quarantine");
  }
  if (args.blockers.length > 0 || bs === "pending_approval") {
    push("missing_prerequisites");
  }

  for (const book of Object.values(RUNBOOKS)) {
    for (const code of book.related_reason_codes) {
      if (rc.includes(code.toLowerCase())) {
        push(book.slug);
      }
    }
  }

  return out;
}
