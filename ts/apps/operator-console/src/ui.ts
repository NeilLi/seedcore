import {
  AssetForensicView,
  SignatureProvenanceEntry,
  TransferTimelineEntry,
  parseAssetForensicView,
  parseTransferStatusView,
} from "@seedcore/contracts";

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function page(title: string, body: string): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      --paper: #f3efe5;
      --ink: #1d2a31;
      --muted: #506069;
      --panel: #fffdf9;
      --edge: #d8ccbb;
      --accent: #0f766e;
      --ok: #198754;
      --warn: #b45f06;
      --bad: #a61b1b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Avenir Next", "Trebuchet MS", sans-serif;
      background:
        radial-gradient(circle at 85% 10%, #d6efe5 0, transparent 38%),
        radial-gradient(circle at 10% 80%, #f7d7be 0, transparent 45%),
        var(--paper);
    }
    main { max-width: 1120px; margin: 28px auto; padding: 0 16px 48px; }
    h1, h2, h3 { margin: 0 0 10px; line-height: 1.2; }
    h1 { font-size: 34px; letter-spacing: -0.02em; }
    .sub { color: var(--muted); margin-bottom: 16px; }
    .grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }
    .split {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    }
    .card {
      border: 1px solid var(--edge);
      background: var(--panel);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 4px 14px rgba(25, 28, 31, 0.06);
    }
    .status {
      display: inline-block;
      border: 1px solid var(--edge);
      border-radius: 999px;
      padding: 3px 9px;
      margin-right: 6px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .ok { color: var(--ok); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    .row { margin: 6px 0; }
    code {
      font-family: "Iosevka", "Menlo", monospace;
      color: #264653;
      font-size: 13px;
      word-break: break-all;
    }
    a {
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px dotted currentColor;
    }
    ul { margin: 8px 0 0; padding-left: 18px; }
    .empty { color: var(--muted); font-style: italic; }
    .timeline li { margin-bottom: 8px; }
  </style>
</head>
<body>
  <main>${body}</main>
</body>
</html>`;
}

export function statusClass(state: string): "ok" | "warn" | "bad" {
  if (state === "verified") {
    return "ok";
  }
  if (state === "quarantined" || state === "review_required") {
    return "warn";
  }
  return "bad";
}

function renderList(values: string[]): string {
  if (!Array.isArray(values) || values.length === 0) {
    return `<p class="empty">none</p>`;
  }
  return `<ul>${values.map((value) => `<li><code>${escapeHtml(value)}</code></li>`).join("")}</ul>`;
}

function renderTimeline(values: TransferTimelineEntry[]): string {
  if (!Array.isArray(values) || values.length === 0) {
    return `<p class="empty">no timeline events</p>`;
  }
  return `<ul class="timeline">${values
    .map(
      (value) => `<li><strong>${escapeHtml(value.event_type)}</strong> <code>${escapeHtml(value.timestamp)}</code><br />${escapeHtml(value.summary)}${
        value.artifact_ref ? ` <br /><code>${escapeHtml(value.artifact_ref)}</code>` : ""
      }</li>`,
    )
    .join("")}</ul>`;
}

function renderActionLinks(query: string): string {
  return `
    <div class="row"><a href="/transfer?${query}">Open workflow review</a></div>
    <div class="row"><a href="/forensics?${query}">Open asset forensic view</a></div>
  `;
}

function renderApiLinks(entries: Array<[string, string | undefined]>): string {
  const items = entries
    .filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0)
    .map(([label, href]) => `<li>${escapeHtml(label)}: <a href="${escapeHtml(href)}"><code>${escapeHtml(href)}</code></a></li>`);
  if (items.length === 0) {
    return `<p class="empty">none</p>`;
  }
  return `<ul>${items.join("")}</ul>`;
}

export function renderCatalogPage(catalog: any): string {
  const items = Array.isArray(catalog?.items) ? catalog.items : [];
  const cards = items
    .map((item: any) => {
      const summary = item.summary ?? {};
      const preview = item.status_preview ?? {};
      const cls = statusClass(summary.business_state ?? "verification_failed");
      const query = typeof item.query === "string" && item.query.length > 0
        ? item.query
        : new URLSearchParams({
            source: "fixture",
            dir: item.dir ?? "",
          }).toString();
      return `
        <article class="card">
          <h3>${escapeHtml(item.id ?? "unknown")}</h3>
          <div class="row">
            <span class="status ${cls}">${escapeHtml(summary.business_state ?? "unknown")}</span>
            <span class="status">${escapeHtml(summary.disposition ?? "unknown")}</span>
            <span class="status">${escapeHtml(summary.approval_status ?? "unknown")}</span>
          </div>
          <div class="row">readiness: <code>${escapeHtml(preview.transfer_readiness ?? "unknown")}</code></div>
          <div class="row">step: <code>${escapeHtml(preview.current_step ?? "unknown")}</code></div>
          <div class="row">top blocker: <code>${escapeHtml(preview.top_blocker ?? "none")}</code></div>
          <div class="row">verified: <code>${String(summary.verified)}</code></div>
          <div class="row">token expected/present: <code>${String(summary.execution_token_expected)} / ${String(summary.execution_token_present)}</code></div>
          ${renderActionLinks(query)}
        </article>
      `;
    })
    .join("");

  return page(
    "SeedCore Operator Console",
    `
      <h1>Restricted Custody Transfer Operator Console</h1>
      <p class="sub">Operator-first status, readiness, and asset forensic workflow for the canonical transfer chain.</p>
      <section class="grid">
        ${cards || `<article class="card"><p class="empty">No transfer scenarios found.</p></article>`}
      </section>
    `,
  );
}

export function renderTransferPage(reviewPayload: any, query: string): string {
  const status = parseTransferStatusView(reviewPayload?.status ?? {});
  const forensics = parseAssetForensicView(reviewPayload?.asset_forensics ?? {});
  const transfer = reviewPayload?.transfer_proof ?? {};
  const cls = statusClass(status.business_state);
  return page(
    "Transfer Workflow Review",
    `
      <h1>Transfer Workflow Review</h1>
      <p class="sub">Operator status, readiness, and verifier state for Restricted Custody Transfer.</p>
      <p class="row"><a href="/?${query}">Back to scenario list</a></p>
      <p class="row"><a href="/forensics?${query}">Open asset forensic view</a></p>

      <section class="card">
        <h2>Current State</h2>
        <div class="row">
          <span class="status ${cls}">${escapeHtml(status.business_state)}</span>
          <span class="status">${escapeHtml(status.disposition)}</span>
          <span class="status">${escapeHtml(status.approval_status)}</span>
          <span class="status">${escapeHtml(status.transfer_readiness)}</span>
        </div>
        <div class="row">current step: <code>${escapeHtml(status.current_step)}</code></div>
        <div class="row">verified: <code>${String(status.verified)}</code></div>
        <div class="row">verification error: <code>${escapeHtml(status.verification_error_code ?? "none")}</code></div>
        <div class="row">execution token: <code>${escapeHtml(transfer.execution_token_id ?? "none")}</code></div>
      </section>

      <section class="split">
        <article class="card">
          <h2>Workflow Identity</h2>
        <div class="row">asset: <code>${escapeHtml(transfer.asset_ref ?? "unknown")}</code></div>
        <div class="row">intent: <code>${escapeHtml(transfer.intent_ref ?? "unknown")}</code></div>
        <div class="row">decision: <code>${escapeHtml(transfer.decision_id ?? "unknown")}</code></div>
        <div class="row">approval envelope: <code>${escapeHtml(transfer.approval_envelope_id ?? "none")}</code></div>
        <div class="row">approval version: <code>${escapeHtml(String(transfer.approval_envelope_version ?? "none"))}</code></div>
        <div class="row">approval binding: <code>${escapeHtml(transfer.approval_binding_hash ?? "none")}</code></div>
        <div class="row">policy receipt: <code>${escapeHtml(transfer.policy_receipt_id ?? "unknown")}</code></div>
        <div class="row">transition receipts: <code>${escapeHtml((transfer.transition_receipt_ids ?? []).join(", ") || "none")}</code></div>
        <h3>Pending Roles</h3>
        ${renderList(status.pending_roles)}
          <h3>Blockers</h3>
          ${renderList(status.blocker_codes)}
        </article>

        <article class="card">
          <h2>Review Signals</h2>
          <h3>Verifier Checks</h3>
          ${renderList(status.checks)}
          <h3>Missing Prerequisites</h3>
          ${renderList(forensics.missing_prerequisites)}
          <h3>Trust Gaps</h3>
          ${renderList(forensics.trust_gaps)}
          <h3>Transfer Links</h3>
          ${renderApiLinks([
            ["Review API", status.links.review],
            ["Asset Forensics API", status.links.asset_forensics],
            ["Public Trust", status.links.public_trust],
            ["Verify", status.links.verify],
          ])}
        </article>
      </section>

      <section class="card">
        <h2>Governed Timeline</h2>
        ${renderTimeline(status.timeline)}
      </section>
    `,
  );
}

export function renderForensicsPage(forensicsPayload: any, query: string): string {
  const forensics = parseAssetForensicView(forensicsPayload);
  const cls = statusClass(forensics.business_state);
  return page(
    "Asset Forensic View",
    `
      <h1>Asset Forensic View</h1>
      <p class="sub">Canonical operator-facing forensic context for the Restricted Custody Transfer wedge.</p>
      <p class="row"><a href="/transfer?${query}">Back to workflow review</a></p>

      <section class="card">
        <h2>Forensic State</h2>
        <div class="row">
          <span class="status ${cls}">${escapeHtml(forensics.business_state)}</span>
          <span class="status">${escapeHtml(forensics.disposition)}</span>
        </div>
        <div class="row">asset: <code>${escapeHtml(forensics.asset_ref)}</code></div>
        <div class="row">decision: <code>${escapeHtml(forensics.decision_id)}</code></div>
        <div class="row">policy snapshot: <code>${escapeHtml(forensics.policy_snapshot_ref)}</code></div>
        <div class="row">approval envelope: <code>${escapeHtml(forensics.approval_envelope_id ?? "none")}</code></div>
        <div class="row">approval version: <code>${escapeHtml(String(forensics.approval_envelope_version ?? "none"))}</code></div>
        <div class="row">approval binding: <code>${escapeHtml(forensics.approval_binding_hash ?? "none")}</code></div>
        <div class="row">policy receipt: <code>${escapeHtml(forensics.policy_receipt_id)}</code></div>
        <div class="row">transition receipts: <code>${escapeHtml(forensics.transition_receipt_ids.join(", ") || "none")}</code></div>
      </section>

      <section class="split">
        <article class="card">
          <h2>Identity + Custody</h2>
          <div class="row">requesting principal: <code>${escapeHtml(forensics.principal_identity.requesting_principal_ref)}</code></div>
          <div class="row">approving principals: <code>${escapeHtml(forensics.principal_identity.approving_principal_refs.join(", ") || "none")}</code></div>
          <div class="row">next custodian: <code>${escapeHtml(forensics.principal_identity.next_custodian_ref ?? "none")}</code></div>
          <h3>Custody Transition</h3>
          <div class="row">from zone: <code>${escapeHtml(forensics.custody_transition.from_zone)}</code></div>
          <div class="row">to zone: <code>${escapeHtml(forensics.custody_transition.to_zone)}</code></div>
          <div class="row">facility: <code>${escapeHtml(forensics.custody_transition.facility_ref)}</code></div>
          <div class="row">custody point: <code>${escapeHtml(forensics.custody_transition.custody_point_ref)}</code></div>
          <div class="row">expected custodian: <code>${escapeHtml(forensics.custody_transition.expected_current_custodian)}</code></div>
          <div class="row">next custodian: <code>${escapeHtml(forensics.custody_transition.next_custodian)}</code></div>
          <h3>Runtime Custody State</h3>
          <div class="row">current custodian: <code>${escapeHtml(forensics.asset_custody_state.current_custodian_ref ?? "none")}</code></div>
          <div class="row">current zone: <code>${escapeHtml(forensics.asset_custody_state.current_zone_ref ?? "none")}</code></div>
          <div class="row">custody point: <code>${escapeHtml(forensics.asset_custody_state.custody_point_ref ?? "none")}</code></div>
          <div class="row">authority source: <code>${escapeHtml(forensics.asset_custody_state.authority_source ?? "none")}</code></div>
        </article>

        <article class="card">
          <h2>Telemetry + Signatures</h2>
          <h3>Telemetry References</h3>
          ${renderList(forensics.telemetry_refs)}
          <h3>Signature Provenance</h3>
          <ul>${forensics.signature_provenance
            .map(
              (entry: SignatureProvenanceEntry) =>
                `<li><code>${escapeHtml(entry.artifact_type)}</code> signed by <code>${escapeHtml(entry.signer_id)}</code> (${escapeHtml(entry.attestation_level)})</li>`,
            )
            .join("") || "<li>none</li>"}</ul>
        </article>
      </section>

      <section class="split">
        <article class="card">
          <h2>Trust Review</h2>
          <h3>Trust Gaps</h3>
          ${renderList(forensics.trust_gaps)}
          <h3>Missing Prerequisites</h3>
          ${renderList(forensics.missing_prerequisites)}
          <h3>Minted Artifacts</h3>
          ${renderList(forensics.minted_artifacts)}
        </article>

        <article class="card">
          <h2>Obligations + Timeline</h2>
          <h3>Obligations</h3>
          ${renderList(forensics.obligations.map((value: unknown) => JSON.stringify(value)))}
          <h3>Forensic Links</h3>
          ${renderApiLinks([
            ["Transfer Review API", forensics.links.transfer_review],
            ["Public Trust", forensics.links.public_trust],
            ["Replay Artifacts", forensics.links.replay_artifacts],
          ])}
          <h3>Governed Timeline</h3>
          ${renderTimeline(forensics.timeline)}
        </article>
      </section>
    `,
  );
}
