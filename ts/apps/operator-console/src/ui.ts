import {
  AssetForensicProjection,
  SignatureProvenanceEntry,
  TransferAuditTrail,
  TransferTimelineEntry,
  parseAssetForensicProjection,
  parseTransferAuditTrail,
  parseVerificationSurfaceProjection,
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
  if (state === "quarantined" || state === "review_required" || state === "pending_approval") {
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

export function renderCatalogPage(catalog: any, listQuery: string): string {
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
      const workflowId = String(item.workflow_id ?? item.id ?? "unknown");
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
          <div class="row"><a href="${escapeHtml(`/replay?workflow_id=${encodeURIComponent(workflowId)}&${listQuery}`)}">Screen 4 — Replay / verification</a></div>
        </article>
      `;
    })
    .join("");

  return page(
    "SeedCore Operator Console",
    `
      <h1>Restricted Custody Transfer Operator Console</h1>
      <p class="sub">Operator-first status, readiness, and asset forensic workflow for the canonical transfer chain.</p>
      <p class="row">
        <a href="/queue?${escapeHtml(listQuery)}">Screen 1 — Transfer queue</a>
        · <a href="/?${escapeHtml(listQuery)}">Scenario cards</a>
      </p>
      <section class="grid">
        ${cards || `<article class="card"><p class="empty">No transfer scenarios found.</p></article>`}
      </section>
    `,
  );
}

export function renderQueuePage(queuePayload: any, listQuery: string): string {
  const items = Array.isArray(queuePayload?.items) ? queuePayload.items : [];
  const rows = items
    .map((row: any) => {
      const trust = row.trust_summary ?? {};
      const pre = row.prerequisites ?? {};
      const cls = statusClass(trust.business_state ?? "verification_failed");
      const bucketCls =
        trust.trust_bucket === "verified"
          ? "ok"
          : trust.trust_bucket === "quarantined" || trust.trust_bucket === "pending"
            ? "warn"
            : "bad";
      const scenarioQs =
        typeof row.links?.review === "string" && row.links.review.includes("?")
          ? row.links.review.split("?")[1] ?? listQuery
          : listQuery;
      const wf = encodeURIComponent(row.workflow_id ?? row.queue_key ?? "");
      return `
        <tr>
          <td><code>${escapeHtml(row.queue_key ?? "")}</code></td>
          <td><code>${escapeHtml(row.workflow_id ?? "")}</code></td>
          <td><code>${escapeHtml(row.asset_ref ?? "")}</code></td>
          <td><span class="status ${bucketCls}">${escapeHtml(trust.trust_bucket ?? "")}</span></td>
          <td><span class="status ${cls}">${escapeHtml(trust.business_state ?? "")}</span></td>
          <td><code>${escapeHtml(String(row.approval_state ?? ""))}</code></td>
          <td><code>${escapeHtml(pre.transfer_readiness ?? "")}</code></td>
          <td><code>${escapeHtml(row.replay_readiness ?? "")}</code></td>
          <td><code>${escapeHtml(pre.top_blocker ?? "none")}</code></td>
          <td>
            <a href="/transfer?${escapeHtml(scenarioQs)}">Review</a>
            · <a href="/forensics?${escapeHtml(scenarioQs)}">Forensics</a>
            · <a href="${escapeHtml(`/replay?workflow_id=${wf}&${listQuery}`)}">Replay</a>
          </td>
        </tr>`;
    })
    .join("");

  const filterBase = escapeHtml(listQuery);
  const listParams = new URLSearchParams(listQuery);
  const rootVal = escapeHtml(listParams.get("root") ?? "rust/fixtures/transfers");
  const sourceVal = escapeHtml(listParams.get("source") ?? "fixture");
  return page(
    "Transfer queue",
    `
      <h1>Screen 1 — Transfer queue</h1>
      <p class="sub">Prerequisite blockers, approval posture, trust bucket, and replay readiness across all scenarios under the selected root.</p>
      <p class="row">
        <a href="/?${filterBase}">Scenario cards</a>
        · <a href="/queue?${filterBase}">Refresh queue</a>
      </p>
      <section class="card">
        <h2>Filters</h2>
        <form method="get" action="/queue" class="row">
          <input type="hidden" name="source" value="${sourceVal}" />
          <input type="hidden" name="root" value="${rootVal}" />
          <label>status / bucket <input name="status" placeholder="verified, quarantined, …" /></label>
          <label>disposition <input name="disposition" placeholder="allow, deny, …" /></label>
          <label>facility <input name="facility" /></label>
          <label>zone <input name="zone" /></label>
          <label>approval <input name="approval_state" placeholder="APPROVED, PENDING, …" /></label>
          <label>replay <input name="replay_readiness" placeholder="ready, pending" /></label>
          <button type="submit">Apply</button>
        </form>
      </section>
      <section class="card" style="overflow-x:auto">
        <h2>Open transfers</h2>
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <thead>
            <tr>
              <th align="left">Case</th>
              <th align="left">Workflow</th>
              <th align="left">Asset</th>
              <th align="left">Trust bucket</th>
              <th align="left">Business state</th>
              <th align="left">Approval</th>
              <th align="left">Readiness</th>
              <th align="left">Replay</th>
              <th align="left">Top blocker</th>
              <th align="left">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${rows || `<tr><td colspan="10"><p class="empty">No rows match the current filters.</p></td></tr>`}
          </tbody>
        </table>
      </section>
    `,
  );
}

export function renderReplayPage(detail: any, query: string, workflowId: string): string {
  const scenarioQs = new URLSearchParams(query);
  scenarioQs.delete("workflow_id");
  const source = scenarioQs.get("source") ?? "fixture";
  if (source === "runtime") {
    scenarioQs.set("source", "runtime");
    if (!scenarioQs.has("audit_id") && !scenarioQs.has("intent_id") && !scenarioQs.has("subject_id")) {
      scenarioQs.set("audit_id", workflowId);
    }
    scenarioQs.delete("dir");
    scenarioQs.delete("root");
  } else {
    scenarioQs.set("source", "fixture");
    if (!scenarioQs.has("dir")) {
      const root = scenarioQs.get("root") ?? "rust/fixtures/transfers";
      scenarioQs.set("dir", `${root.replace(/\/+$/, "")}/${workflowId}`);
    }
  }
  const detailQuery = scenarioQs.toString();

  const projection = parseVerificationSurfaceProjection(detail?.verification_projection ?? {});
  const failure = detail?.failure_panel ?? {};
  const chain = detail?.receipt_chain ?? { steps: [], terminal_disposition: "", replay_verifiable: false };
  const steps = Array.isArray(chain.steps) ? chain.steps : [];
  const cls = statusClass(projection.status);
  const failActive = Boolean(failure.active);
  const failCls = failActive ? "bad" : "ok";
  const stepRows = steps
    .map(
      (s: any) => `
        <tr>
          <td><code>${escapeHtml(s.id ?? "")}</code></td>
          <td>${escapeHtml(s.label ?? "")}</td>
          <td><code>${escapeHtml(s.ref != null ? String(s.ref) : "none")}</code></td>
          <td><span class="status ${s.ok ? "ok" : "bad"}">${s.ok ? "ok" : "gap"}</span></td>
          <td>${escapeHtml(s.detail ?? "")}</td>
        </tr>`,
    )
    .join("");
  return page(
    "Replay / verification",
    `
      <h1>Screen 4 — Replay / verification</h1>
      <p class="sub">Receipt-chain checkpoints and explicit failure context for deny or quarantine paths.</p>
      <p class="row">
        <a href="/?${query}">Scenarios</a>
        · <a href="/queue?${query}">Queue</a>
        · <a href="/transfer?${detailQuery}">Transfer detail</a>
        · <a href="/forensics?${detailQuery}">Forensics</a>
      </p>

      <section class="card">
        <h2>Workflow summary</h2>
        <div class="row">
          <span class="status ${cls}">${escapeHtml(projection.status)}</span>
          <span class="status">${escapeHtml(projection.authorization.disposition)}</span>
        </div>
        <div class="row">workflow id: <code>${escapeHtml(workflowId)}</code></div>
        <div class="row">asset: <code>${escapeHtml(projection.asset_ref)}</code></div>
        <div class="row">replay verifiable (chain): <code>${String(chain.replay_verifiable)}</code></div>
        <div class="row">terminal disposition: <code>${escapeHtml(String(chain.terminal_disposition ?? ""))}</code></div>
      </section>

      <section class="card">
        <h2>Failure panel</h2>
        <div class="row"><span class="status ${failCls}">${failActive ? "active" : "clear"}</span> ${escapeHtml(failure.headline ?? "")}</div>
        <div class="row">path: <code>${escapeHtml(String(failure.path ?? ""))}</code> · business state: <code>${escapeHtml(String(failure.business_state ?? ""))}</code></div>
        <div class="row">reason code: <code>${escapeHtml(String(failure.reason_code ?? ""))}</code></div>
        <div class="row">reason: ${escapeHtml(String(failure.reason ?? ""))}</div>
        <h3>Blockers</h3>
        ${renderList(Array.isArray(failure.blockers) ? failure.blockers : [])}
        <h3>Trust gaps</h3>
        ${renderList(Array.isArray(failure.trust_gaps) ? failure.trust_gaps : [])}
        <h3>Missing prerequisites</h3>
        ${renderList(Array.isArray(failure.missing_prerequisites) ? failure.missing_prerequisites : [])}
        <h3>Runbooks</h3>
        ${renderApiLinks(
          (Array.isArray(failure.runbook_links) ? failure.runbook_links : []).map((r: { title?: string; href_path?: string }) => [
            r.title ?? "runbook",
            typeof r.href_path === "string" ? r.href_path : undefined,
          ]),
        )}
      </section>

      <section class="card" style="overflow-x:auto">
        <h2>Receipt chain</h2>
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <thead>
            <tr><th align="left">Id</th><th align="left">Step</th><th align="left">Ref</th><th align="left">Status</th><th align="left">Detail</th></tr>
          </thead>
          <tbody>${stepRows || `<tr><td colspan="5"><p class="empty">No steps</p></td></tr>`}</tbody>
        </table>
      </section>

      <section class="card">
        <h2>API</h2>
        ${renderApiLinks([
          ["Verification detail (JSON)", `/api/v1/verification/workflows/${encodeURIComponent(workflowId)}/verification-detail?${query}`],
          ["Workflow projection", `/api/v1/verification/workflows/${encodeURIComponent(workflowId)}/projection?${query}`],
        ])}
      </section>
    `,
  );
}

export function renderTransferPage(reviewPayload: any, query: string): string {
  const projection = parseVerificationSurfaceProjection(reviewPayload?.verification_projection ?? {});
  const auditTrail = parseTransferAuditTrail(reviewPayload?.transfer_audit_trail ?? {});
  const forensics = parseAssetForensicProjection(reviewPayload?.asset_forensic_projection ?? {});
  const cls = statusClass(projection.status);
  const qp = new URLSearchParams(query);
  const replayList = new URLSearchParams({
    workflow_id: projection.workflow_id,
    source: qp.get("source") ?? "fixture",
    root: qp.get("root") ?? "rust/fixtures/transfers",
  });
  const replayHref = escapeHtml(`/replay?${replayList.toString()}`);
  return page(
    "Transfer Workflow Review",
    `
      <h1>Transfer Workflow Review</h1>
      <p class="sub">Side-by-side audit trail: request + authority, decision + artifacts, and physical evidence + closure.</p>
      <p class="row"><a href="/?${query}">Back to scenario list</a> · <a href="/queue?${query}">Transfer queue</a> · <a href="${replayHref}">Screen 4 — Replay / verification</a></p>
      <p class="row"><a href="/forensics?${query}">Open asset forensic view</a></p>

      <section class="card">
        <h2>Workflow Projection</h2>
        <div class="row">
          <span class="status ${cls}">${escapeHtml(projection.status)}</span>
          <span class="status">${escapeHtml(projection.authorization.disposition)}</span>
          <span class="status">${escapeHtml(projection.summary.approval_state)}</span>
        </div>
        <div class="row">workflow id: <code>${escapeHtml(projection.workflow_id)}</code></div>
        <div class="row">asset: <code>${escapeHtml(projection.asset_ref)}</code></div>
        <div class="row">from zone: <code>${escapeHtml(projection.summary.from_zone)}</code></div>
        <div class="row">to zone: <code>${escapeHtml(projection.summary.to_zone)}</code></div>
      </section>

      <section class="split">
        <article class="card">
          <h2>Request + Authority</h2>
          <div class="row">request id: <code>${escapeHtml(auditTrail.request.request_id)}</code></div>
          <div class="row">requested at: <code>${escapeHtml(auditTrail.request.requested_at)}</code></div>
          <div class="row">request summary: ${escapeHtml(auditTrail.request.request_summary)}</div>
          <div class="row">action type: <code>${escapeHtml(auditTrail.request.action_type)}</code></div>
          <div class="row">agent id: <code>${escapeHtml(auditTrail.principal.agent_id)}</code></div>
          <div class="row">role profile: <code>${escapeHtml(auditTrail.principal.role_profile)}</code></div>
          <div class="row">owner id: <code>${escapeHtml(auditTrail.principal.owner_id ?? "none")}</code></div>
          <div class="row">delegation ref: <code>${escapeHtml(auditTrail.principal.delegation_ref ?? "none")}</code></div>
          <div class="row">organization ref: <code>${escapeHtml(auditTrail.principal.organization_ref ?? "none")}</code></div>
          <div class="row">fingerprint id: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.fingerprint_id ?? "none")}</code></div>
          <div class="row">fingerprint pubkey: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.public_key_fingerprint ?? "none")}</code></div>
          <div class="row">scope id: <code>${escapeHtml(auditTrail.authority_scope.scope_id ?? "none")}</code></div>
          <div class="row">scope verdict: <code>${escapeHtml(auditTrail.authority_scope.authority_scope_verdict)}</code></div>
          <h3>Scope Mismatch Keys</h3>
          ${renderList(auditTrail.authority_scope.mismatch_keys)}
        </article>

        <article class="card">
          <h2>Decision + Artifacts</h2>
          <div class="row">allowed: <code>${String(auditTrail.decision.allowed)}</code></div>
          <div class="row">disposition: <code>${escapeHtml(auditTrail.decision.disposition)}</code></div>
          <div class="row">reason code: <code>${escapeHtml(auditTrail.decision.reason_code)}</code></div>
          <div class="row">reason: ${escapeHtml(auditTrail.decision.reason)}</div>
          <div class="row">policy snapshot: <code>${escapeHtml(auditTrail.decision.policy_snapshot_ref)}</code></div>
          <div class="row">latency ms: <code>${escapeHtml(String(auditTrail.decision.latency_ms ?? "none"))}</code></div>
          <div class="row">decision id: <code>${escapeHtml(auditTrail.artifacts.decision_id)}</code></div>
          <div class="row">policy receipt id: <code>${escapeHtml(auditTrail.artifacts.policy_receipt_id)}</code></div>
          <div class="row">transition receipt ids: <code>${escapeHtml(auditTrail.artifacts.transition_receipt_ids.join(", ") || "none")}</code></div>
          <div class="row">execution token id: <code>${escapeHtml(auditTrail.artifacts.execution_token_id ?? "none")}</code></div>
          <div class="row">audit id: <code>${escapeHtml(auditTrail.artifacts.audit_id)}</code></div>
          <div class="row">forensic block id: <code>${escapeHtml(auditTrail.artifacts.forensic_block_id ?? "none")}</code></div>
          <h3>Minted Artifacts</h3>
          ${renderList(auditTrail.artifacts.minted_artifacts)}
          <h3>Obligations</h3>
          ${renderList(auditTrail.artifacts.obligations.map((value: unknown) => JSON.stringify(value)))}
        </article>

        <article class="card">
          <h2>Physical Evidence + Closure</h2>
          <div class="row">current zone: <code>${escapeHtml(auditTrail.physical_evidence.current_zone ?? "none")}</code></div>
          <div class="row">current coordinate: <code>${escapeHtml(auditTrail.physical_evidence.current_coordinate_ref ?? "none")}</code></div>
          <div class="row">economic hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.economic_hash ?? "none")}</code></div>
          <div class="row">physical presence hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.physical_presence_hash ?? "none")}</code></div>
          <div class="row">reasoning hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.reasoning_hash ?? "none")}</code></div>
          <div class="row">actuator hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.actuator_hash ?? "none")}</code></div>
          <div class="row">replay status: <code>${escapeHtml(auditTrail.physical_evidence.replay_status)}</code></div>
          <div class="row">settlement status: <code>${escapeHtml(auditTrail.physical_evidence.settlement_status)}</code></div>
          <h3>Telemetry References</h3>
          ${renderList(auditTrail.physical_evidence.telemetry_refs)}
          <h3>Trust Gaps</h3>
          ${renderList(forensics.trust_gaps)}
          <h3>Missing Prerequisites</h3>
          ${renderList(forensics.missing_prerequisites)}
          <h3>Transfer Links</h3>
          ${renderApiLinks([
            ["Workflow Projection API", projection.links.audit_trail_ref],
            ["Asset Forensics API", projection.links.forensics_ref],
            ["Replay Artifacts", auditTrail.links.replay_artifacts_ref ?? undefined],
            ["Public Trust", projection.links.trust_ref ?? undefined],
          ])}
        </article>
      </section>

      <section class="card">
        <h2>Governed Timeline</h2>
        ${renderTimeline(forensics.timeline)}
      </section>
    `,
  );
}

export function renderForensicsPage(forensicsPayload: any, query: string): string {
  const forensics = parseAssetForensicProjection(forensicsPayload);
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
          <h3>Forensic Fingerprint</h3>
          <div class="row">economic hash: <code>${escapeHtml(forensics.forensic_fingerprint.economic_hash ?? "none")}</code></div>
          <div class="row">physical presence hash: <code>${escapeHtml(forensics.forensic_fingerprint.physical_presence_hash ?? "none")}</code></div>
          <div class="row">reasoning hash: <code>${escapeHtml(forensics.forensic_fingerprint.reasoning_hash ?? "none")}</code></div>
          <div class="row">actuator hash: <code>${escapeHtml(forensics.forensic_fingerprint.actuator_hash ?? "none")}</code></div>
          <h3>Signature Provenance</h3>
          <ul>${forensics.signer_provenance
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
            ["Workflow Projection API", forensics.links.workflow_projection_ref],
            ["Transfer Audit Trail API", forensics.links.transfer_audit_trail_ref],
            ["Public Trust", forensics.links.trust_ref ?? undefined],
            ["Replay Artifacts", forensics.links.replay_artifacts_ref ?? undefined],
          ])}
          <h3>Governed Timeline</h3>
          ${renderTimeline(forensics.timeline)}
        </article>
      </section>
    `,
  );
}
