import {
  AssetForensicProjection,
  type OperatorCopilotBriefV1,
  SignatureProvenanceEntry,
  TransferAuditTrail,
  TransferTimelineEntry,
  type CaseVerdictHeader,
  type ReplayVerdict,
  buildDeterministicCopilotBrief,
  buildDeterministicCopilotBriefFromForensics,
  buildDeterministicCopilotBriefFromProjectionOnly,
  deriveCaseVerdictFromForensicsOnly,
  deriveCaseVerdictFromProjectionOnly,
  deriveCaseVerdictHeader,
  deriveReplayCorrelationFlags,
  deriveReplayVerdict,
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export type OperatorNavKey = "transfers" | "verification" | "runbooks";

export type HotPathBanner = {
  resolved_mode: string;
  graph_freshness_ok: boolean;
  alert_level: string;
};

export type OperatorShellOptions = {
  nav: OperatorNavKey;
  listQuery: string;
  hotPath: HotPathBanner | null;
};

function renderOperatorShell(nav: OperatorNavKey, listQuery: string, hotPath: HotPathBanner | null): string {
  const q = escapeHtml(listQuery);
  const item = (key: OperatorNavKey, label: string, href: string) =>
    `<a class="topnav-link${nav === key ? " topnav-active" : ""}" href="${href}">${escapeHtml(label)}</a>`;
  const parts: string[] = [];
  if (hotPath) {
    const modeCls = hotPath.alert_level === "critical" ? "bad" : hotPath.alert_level === "warning" ? "warn" : "ok";
    parts.push(
      `<span class="status ${modeCls}">Hot path · ${escapeHtml(hotPath.resolved_mode)}</span>`,
      `<span class="status ${hotPath.graph_freshness_ok ? "ok" : "bad"}">Graph fresh · ${String(hotPath.graph_freshness_ok)}</span>`,
      `<span class="status">Observability · ${escapeHtml(hotPath.alert_level)}</span>`,
    );
  }
  return `
    <nav class="topnav" aria-label="Primary">
      ${item("transfers", "Transfers", `/?${q}`)}
      ${item("verification", "Verification", `/queue?${q}`)}
      ${item("runbooks", "Runbooks", `/runbooks`)}
      <form class="topnav-search" method="get" action="/search">
        <input name="q" placeholder="audit UUID · workflow · asset:… · envelope:… · request:…" size="36" aria-label="Search" />
        <button type="submit">Search</button>
      </form>
    </nav>
    ${parts.length ? `<div class="env-banner" role="status">${parts.join(" ")}</div>` : ""}`;
}

export function page(title: string, body: string, shell?: OperatorShellOptions): string {
  const shellBlock = shell ? renderOperatorShell(shell.nav, shell.listQuery, shell.hotPath) : "";
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
    .topnav {
      display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
      padding: 12px 16px; margin: 0 0 0; border-bottom: 1px solid var(--edge);
      background: rgba(255, 253, 249, 0.92);
    }
    .topnav-link { font-weight: 600; font-size: 14px; border-bottom: none; }
    .topnav-active { color: var(--ink); border-bottom: 2px solid var(--accent); padding-bottom: 2px; }
    .env-banner {
      padding: 8px 16px; font-size: 13px; border-bottom: 1px solid var(--edge);
      background: rgba(255, 253, 249, 0.75);
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
    .topnav-search {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      margin-left: 18px;
    }
    .crumbs { margin: 0 0 14px; line-height: 1.5; }
    .crumbs a { margin-right: 2px; }
    .filter-form {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: flex-end;
      margin: 8px 0 0;
    }
    .filter-form label {
      font-size: 12px;
      color: var(--muted);
      font-weight: 600;
    }
    .filter-form input {
      margin-top: 4px;
      padding: 6px 8px;
      border: 1px solid var(--edge);
      border-radius: 8px;
      font-size: 13px;
      min-width: 8rem;
    }
    .filter-form button {
      padding: 7px 14px;
      border-radius: 8px;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fff;
      font-weight: 600;
      cursor: pointer;
    }
    .data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    .data-table th,
    .data-table td {
      padding: 8px 10px 8px 0;
      border-bottom: 1px solid var(--edge);
      vertical-align: top;
    }
    .data-table th {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      font-weight: 700;
    }
    .table-scroll { overflow-x: auto; }
    .card > h2 { font-size: 1.05rem; font-weight: 700; color: var(--ink); }
    .card > h3 { font-size: 0.95rem; font-weight: 700; margin-top: 12px; color: var(--ink); }
    .verdict-strip { border-left: 4px solid var(--accent); }
    .verdict-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      margin-top: 8px;
    }
    .vlab {
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      font-weight: 700;
    }
    .vval { margin-top: 4px; font-size: 14px; font-weight: 600; line-height: 1.35; }
    .replay-verdict-card { border-left: 4px solid var(--edge); }
    .copilot-panel {
      border-left: 4px dashed var(--muted);
      background: rgba(15, 118, 110, 0.05);
    }
    .delta-panel { border-left: 4px solid #6c757d; }
    .flag-warn code { color: var(--warn); font-weight: 700; }
  </style>
</head>
<body>
  ${shellBlock}
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

function withQueryParam(listQuery: string, key: string, value: string | null | undefined): string {
  const p = new URLSearchParams(listQuery);
  if (value === null || value === undefined || value === "") {
    p.delete(key);
  } else {
    p.set(key, value);
  }
  return p.toString();
}

function inputValueFromQuery(listQuery: string, key: string): string {
  const v = new URLSearchParams(listQuery).get(key);
  return v ? escapeHtml(v) : "";
}

/** Shared in-page links between RCT surfaces (labels match product spec). */
function renderSurfaceCrumbs(
  listQuery: string,
  replayHref?: string,
  opts?: { transferForensicsQuery?: string },
): string {
  const qe = escapeHtml(listQuery);
  const tf = escapeHtml(opts?.transferForensicsQuery ?? listQuery);
  const replay =
    replayHref != null && replayHref.length > 0
      ? `<a href="${escapeHtml(replayHref)}">Replay / verification</a>`
      : `<a href="/replay?${qe}">Replay / verification</a>`;
  return `<nav class="crumbs" aria-label="RCT surfaces">${[
    `<a href="/?${qe}">Scenario cards</a>`,
    `<a href="/queue?${qe}">Transfer queue</a>`,
    `<a href="/transfer?${tf}">Transfer detail</a>`,
    `<a href="/forensics?${tf}">Forensics</a>`,
    replay,
  ].join(" · ")}</nav>`;
}

function renderCaseVerdictStrip(header: CaseVerdictHeader): string {
  return `<section class="card verdict-strip" aria-label="Case verdict">
    <h2>Case verdict</h2>
    <p class="sub">Legibility layer on top of frozen contracts — same sources of truth as the cards below.</p>
    <div class="verdict-grid">
      <div><span class="vlab">Decision</span><div class="vval">${escapeHtml(header.decision)}</div></div>
      <div><span class="vlab">Risk</span><div class="vval">${escapeHtml(header.risk)}</div></div>
      <div><span class="vlab">Confidence</span><div class="vval">${escapeHtml(header.confidence)}</div></div>
      <div><span class="vlab">Next action</span><div class="vval">${escapeHtml(header.next_action)}</div></div>
    </div>
  </section>`;
}

function renderReplayVerdictCard(verdict: ReplayVerdict, correlationFlags: string[]): string {
  const cls = verdict === "consistent" ? "ok" : verdict === "inconsistent" ? "bad" : "warn";
  const flagBlock =
    correlationFlags.length > 0
      ? `<p class="sub">Cross-surface checks (deterministic)</p><ul>${correlationFlags
          .map((f) => `<li><code>${escapeHtml(f)}</code></li>`)
          .join("")}</ul>`
      : `<p class="sub">No deterministic cross-check flags on this payload.</p>`;
  return `<section class="card replay-verdict-card" aria-label="Replay verdict">
    <h2>Replay verdict <span class="status ${cls}">${escapeHtml(verdict)}</span></h2>
    <p class="sub">Derived from receipt chain steps, replay readiness, verification traces, and failure panel — not a model.</p>
    ${flagBlock}
  </section>`;
}

function renderCopilotReadOnlyPanel(brief: OperatorCopilotBriefV1): string {
  const bullets = brief.operator_brief_bullets
    .slice(0, 6)
    .map((b) => `<li>${escapeHtml(b)}</li>`)
    .join("");
  const mode = brief.generation_mode === "llm" ? "llm" : "deterministic";
  const modeCls = mode === "llm" ? "warn" : "ok";
  const unc = (brief.uncertainty_notes ?? [])
    .map((u) => `<li>${escapeHtml(u)}</li>`)
    .join("");
  return `<section class="card copilot-panel" aria-label="Operator copilot read-only">
    <h2>Copilot (read-only, MVP) <span class="status ${modeCls}">${escapeHtml(mode)}</span></h2>
    <p class="sub">Does not mutate state. LLM path (when enabled on verification API) must include citations and uncertainty; this panel mirrors the same contract.</p>
    <p class="row"><strong>Confidence</strong> — ${escapeHtml(brief.confidence)}</p>
    <h3>Uncertainty</h3>
    <ul>${unc || "<li class=\"empty\">none</li>"}</ul>
    <p><strong>One-line summary</strong> — ${escapeHtml(brief.one_line_summary)}</p>
    <h3>Operator brief (≤5 bullets)</h3>
    <ul>${bullets}</ul>
    <h3>Deep drill-down</h3>
    <p class="row"><strong>Facts</strong> (from projections)</p>
    <ul>${brief.facts.map((f) => `<li><code>${escapeHtml(f)}</code></li>`).join("")}</ul>
    <p class="row"><strong>Inferences</strong> (heuristic / non-authoritative)</p>
    <ul>${brief.inferences.map((f) => `<li>${escapeHtml(f)}</li>`).join("")}</ul>
    <p class="row"><strong>Citations</strong></p>
    <ul>${brief.citations.map((c) => `<li><code>${escapeHtml(c.path)}</code> → <code>${escapeHtml(c.value)}</code></li>`).join("")}</ul>
    <p class="sub"><code>${escapeHtml(brief.contract_version)}</code> · ${escapeHtml(brief.audit_note)}</p>
  </section>`;
}

function renderChangeSinceLastLoad(viewKey: string, snapshot: Record<string, unknown>): string {
  const json = JSON.stringify(snapshot).replaceAll("<", "\\u003c");
  const vk = escapeHtml(viewKey);
  return `<section class="card delta-panel" id="seedcore-op-delta-mount">
    <h2>What changed since last load</h2>
    <div id="seedcore-op-delta" class="sub">Comparing…</div>
    <script type="application/json" id="seedcore-op-snapshot" data-view="${vk}">${json}</script>
    <script>
(() => {
  var el = document.getElementById("seedcore-op-snapshot");
  var out = document.getElementById("seedcore-op-delta");
  if (!el || !out || !el.dataset.view) return;
  var key = "seedcore.op.snapshot." + el.dataset.view;
  var cur = {};
  try { cur = JSON.parse(el.textContent || "{}"); } catch (e1) { out.textContent = "Unable to parse snapshot."; return; }
  var prevRaw = sessionStorage.getItem(key);
  sessionStorage.setItem(key, el.textContent || "{}");
  if (!prevRaw) { out.innerHTML = '<p class="sub">No prior snapshot in this browser tab session.</p>'; return; }
  var prev = {};
  try { prev = JSON.parse(prevRaw); } catch (e2) {}
  var keys = Object.keys(cur).concat(Object.keys(prev)).filter(function (k, i, a) { return a.indexOf(k) === i; }).sort();
  var changes = [];
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    var a = JSON.stringify(cur[k]);
    var b = JSON.stringify(prev[k]);
    if (a !== b) changes.push("<li><code>" + k.replace(/</g, "&lt;") + "</code></li>");
  }
  out.innerHTML = changes.length ? "<ul>" + changes.join("") + "</ul>" : '<p class="sub">No field changes detected vs last load.</p>';
})();
    </script>
  </section>`;
}

function renderQueueBusinessStateStrip(items: any[], listQuery: string): string {
  const counts: Record<string, number> = {
    verified: 0,
    quarantined: 0,
    rejected: 0,
    review_required: 0,
    pending_approval: 0,
  };
  for (const row of items) {
    const bs = String(row.trust_summary?.business_state ?? "");
    if (bs in counts) {
      counts[bs] += 1;
    }
  }
  const chip = (label: string, state: string) => {
    const qs = escapeHtml(withQueryParam(listQuery, "status", state));
    const cls = statusClass(state);
    return `<a class="status ${cls}" href="/queue?${qs}">${escapeHtml(label)} (${counts[state]})</a>`;
  };
  const clearQs = escapeHtml(withQueryParam(listQuery, "status", null));
  return `
      <section class="card">
        <h2>Business-readable status</h2>
        <p class="sub">Counts reflect the current filter result set. Click a chip to filter the table.</p>
        <div class="row">
          ${chip("Verified", "verified")}
          ${chip("Quarantined", "quarantined")}
          ${chip("Rejected", "rejected")}
          ${chip("Review required", "review_required")}
          ${chip("Pending approval", "pending_approval")}
          <a class="status" href="/queue?${clearQs}">Clear status filter</a>
        </div>
      </section>`;
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
    <div class="row"><a href="/transfer?${query}">Transfer detail</a></div>
    <div class="row"><a href="/forensics?${query}">Forensics</a></div>
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

export function renderCatalogPage(catalog: any, listQuery: string, shell?: OperatorShellOptions): string {
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
          <div class="row"><a href="${escapeHtml(`/replay?workflow_id=${encodeURIComponent(workflowId)}&${listQuery}`)}">Replay / verification</a></div>
        </article>
      `;
    })
    .join("");

  return page(
    "Scenario cards — Operator console",
    `
      <h1>Scenario cards</h1>
      <p class="sub">Restricted Custody Transfer — operator status, readiness, and forensic entry points for each fixture scenario.</p>
      ${renderSurfaceCrumbs(listQuery)}
      <section class="grid">
        ${cards || `<article class="card"><p class="empty">No transfer scenarios found.</p></article>`}
      </section>
    `,
    shell,
  );
}

export function renderQueuePage(queuePayload: any, listQuery: string, shell?: OperatorShellOptions): string {
  const items = Array.isArray(queuePayload?.items) ? queuePayload.items : [];
  const alertCounts = new Map<string, number>();
  for (const row of items) {
    for (const a of Array.isArray(row.trust_alerts) ? row.trust_alerts : []) {
      if (typeof a === "string") {
        alertCounts.set(a, (alertCounts.get(a) ?? 0) + 1);
      }
    }
  }
  const strip =
    alertCounts.size > 0
      ? `<section class="card"><h2>Trust alerts</h2><p class="sub">Aggregated codes for this result set (replay readiness, trust gaps, scope verification, prerequisites, verification errors).</p><div class="row">${[...alertCounts.entries()]
          .map(([k, v]) => `<span class="status warn">${escapeHtml(k)} (${v})</span>`)
          .join(" ")}</div></section>`
      : "";
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
      const sig = row.operator_signals ?? { priority_score: 0, correlation_flags: [] };
      const flags = Array.isArray(sig.correlation_flags) ? sig.correlation_flags : [];
      const flagTxt = flags.length > 0 ? flags.join(", ") : "—";
      const flagCell =
        flags.length > 0
          ? `<span class="flag-warn"><code>${escapeHtml(flagTxt)}</code></span>`
          : `<code>${escapeHtml(flagTxt)}</code>`;
      return `
        <tr>
          <td><code>${escapeHtml(String(sig.priority_score ?? 0))}</code></td>
          <td>${flagCell}</td>
          <td><code>${escapeHtml(row.queue_key ?? "")}</code></td>
          <td><code>${escapeHtml(row.workflow_id ?? "")}</code></td>
          <td><code>${escapeHtml(row.asset_ref ?? "")}</code></td>
          <td><code>${escapeHtml(row.product_ref != null ? String(row.product_ref) : "—")}</code></td>
          <td><code>${escapeHtml(row.updated_at != null ? String(row.updated_at) : "—")}</code></td>
          <td><code>${escapeHtml(Array.isArray(row.trust_alerts) ? row.trust_alerts.join(", ") || "—" : "—")}</code></td>
          <td><span class="status ${bucketCls}">${escapeHtml(trust.trust_bucket ?? "")}</span></td>
          <td><span class="status ${cls}">${escapeHtml(trust.business_state ?? "")}</span></td>
          <td><code>${escapeHtml(String(row.approval_state ?? ""))}</code></td>
          <td><code>${escapeHtml(pre.transfer_readiness ?? "")}</code></td>
          <td><code>${escapeHtml(row.replay_readiness ?? "")}</code></td>
          <td><code>${escapeHtml(pre.top_blocker ?? "none")}</code></td>
          <td>
            <a href="/transfer?${escapeHtml(scenarioQs)}">Transfer detail</a>
            · <a href="/forensics?${escapeHtml(scenarioQs)}">Forensics</a>
            · <a href="${escapeHtml(`/replay?workflow_id=${wf}&${listQuery}`)}">Replay / verification</a>
          </td>
        </tr>`;
    })
    .join("");

  const filterBase = escapeHtml(listQuery);
  const listParams = new URLSearchParams(listQuery);
  const rootVal = escapeHtml(listParams.get("root") ?? "rust/fixtures/transfers");
  const sourceVal = escapeHtml(listParams.get("source") ?? "fixture");
  const sortChron = listParams.get("queue_sort") === "chron";
  const sortLabel = sortChron ? "Updated · newest first" : "Needs attention first (default)";
  const statusStrip = items.length > 0 ? renderQueueBusinessStateStrip(items, listQuery) : "";
  const queueChangeSnap: Record<string, unknown> = {
    sort: sortChron ? "chron" : "anomaly",
    row_count: items.length,
    workflow_fingerprint: items
      .map((r: { workflow_id?: string }) => String(r.workflow_id ?? ""))
      .sort()
      .join("|"),
  };
  return page(
    "Screen 1 — Transfer queue",
    `
      <h1>Screen 1 — Transfer queue</h1>
      <p class="sub">Prerequisite blockers, approval posture, trust bucket, and replay readiness. <strong>Sort:</strong> ${escapeHtml(
        sortLabel,
      )}. Higher <strong>Priority</strong> scores surface cases that need action sooner; <strong>Correlation flags</strong> highlight internal inconsistencies on the row payload.</p>
      ${renderSurfaceCrumbs(listQuery)}
      <p class="row"><a href="/queue?${filterBase}">Refresh this view</a></p>
      ${statusStrip}
      <section class="card">
        <h2>Filters</h2>
        <form method="get" action="/queue" class="filter-form">
          <input type="hidden" name="source" value="${sourceVal}" />
          <input type="hidden" name="root" value="${rootVal}" />
          <label>status / bucket<br /><input name="status" placeholder="verified, quarantined, …" value="${inputValueFromQuery(listQuery, "status")}" /></label>
          <label>disposition<br /><input name="disposition" placeholder="allow, deny, …" value="${inputValueFromQuery(listQuery, "disposition")}" /></label>
          <label>facility<br /><input name="facility" value="${inputValueFromQuery(listQuery, "facility")}" /></label>
          <label>zone<br /><input name="zone" value="${inputValueFromQuery(listQuery, "zone")}" /></label>
          <label>approval<br /><input name="approval_state" placeholder="APPROVED, PENDING, …" value="${inputValueFromQuery(listQuery, "approval_state")}" /></label>
          <label>replay<br /><input name="replay_readiness" placeholder="ready, pending" value="${inputValueFromQuery(listQuery, "replay_readiness")}" /></label>
          <label>trust alert<br /><input name="trust_alert" placeholder="replay_not_ready, …" value="${inputValueFromQuery(listQuery, "trust_alert")}" /></label>
          <label>envelope id<br /><input name="approval_envelope_id" placeholder="substring" value="${inputValueFromQuery(listQuery, "approval_envelope_id")}" /></label>
          <label>request id<br /><input name="request_id" placeholder="substring" value="${inputValueFromQuery(listQuery, "request_id")}" /></label>
          <label>sort order<br /><select name="queue_sort">
            <option value="anomaly" ${sortChron ? "" : "selected"}>Needs attention first</option>
            <option value="chron" ${sortChron ? "selected" : ""}>Updated · newest first</option>
          </select></label>
          <button type="submit">Apply</button>
        </form>
      </section>
      ${strip}
      ${renderChangeSinceLastLoad(`queue:${listParams.get("root") ?? "default"}`, queueChangeSnap)}
      <section class="card table-scroll">
        <h2>Open transfers</h2>
        <table class="data-table">
          <thead>
            <tr>
              <th align="left">Priority</th>
              <th align="left">Flags</th>
              <th align="left">Case</th>
              <th align="left">Workflow</th>
              <th align="left">Asset</th>
              <th align="left">Product</th>
              <th align="left">Updated</th>
              <th align="left">Trust alerts</th>
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
            ${rows || `<tr><td colspan="15"><p class="empty">No rows match the current filters.</p></td></tr>`}
          </tbody>
        </table>
      </section>
    `,
    shell,
  );
}

export function renderRunbooksPage(
  indexPayload: any,
  shell?: OperatorShellOptions,
  verificationApiBase?: string,
  listQuery?: string,
): string {
  const navQs = escapeHtml(listQuery ?? "");
  const books = Array.isArray(indexPayload?.runbooks) ? indexPayload.runbooks : [];
  const base = (verificationApiBase ?? "").replace(/\/+$/, "");
  const presetLookup = (label: string, reason: string) =>
    base
      ? `<li><a href="${escapeHtml(`${base}/api/v1/verification/runbook/lookup?reason_code=${encodeURIComponent(reason)}`)}">${escapeHtml(label)}</a></li>`
      : "";
  const cards = books
    .map(
      (b: { slug?: string; title?: string }) => `
      <article class="card">
        <h3>${escapeHtml(b.title ?? b.slug ?? "runbook")}</h3>
        <p class="row"><a href="/api/v1/verification/runbook/${encodeURIComponent(b.slug ?? "")}">JSON entry</a> (verification API)</p>
      </article>`,
    )
    .join("");
  const quick =
    base &&
    `<section class="card">
        <h2>Preset runbook lookups</h2>
        <p class="sub">Resolved against <code>seedcore.verification_runbook_lookup.v1</code> on the verification service.</p>
        <ul>
          ${presetLookup("Stale telemetry", "stale_telemetry")}
          ${presetLookup("Trust gap / quarantine", "trust_gap_quarantine")}
          ${presetLookup("Policy denied", "policy_denied")}
          ${presetLookup("Snapshot not ready", "snapshot_not_ready")}
          ${presetLookup("Scope / asset mismatch", "asset_custody_mismatch")}
        </ul>
      </section>`;
  return page(
    "Runbooks — Operator console",
    `
      <h1>Runbooks</h1>
      <p class="sub">Investigation guides for failure panels and operator drills (read-only JSON on the verification API).</p>
      <nav class="crumbs" aria-label="RCT surfaces">
        <a href="/?${navQs}">Scenario cards</a>
        · <a href="/queue?${navQs}">Transfer queue</a>
        · <a href="/transfer?${navQs}">Transfer detail</a>
        · <a href="/forensics?${navQs}">Forensics</a>
      </nav>
      ${quick || `<p class="sub">Set <code>SEEDCORE_VERIFICATION_API_BASE</code> on the operator console to enable preset lookup links.</p>`}
      <section class="grid">${cards || `<article class="card"><p class="empty">No runbooks.</p></article>`}</section>
    `,
    shell,
  );
}

export function renderReplayPage(
  detail: any,
  query: string,
  workflowId: string,
  shell?: OperatorShellOptions,
): string {
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
  const replaySelfRaw = `/replay?workflow_id=${encodeURIComponent(workflowId)}&${detailQuery}`;
  let auditTrailReplay: TransferAuditTrail | null = null;
  let forensicsReplay: AssetForensicProjection | null = null;
  try {
    auditTrailReplay = parseTransferAuditTrail(detail?.transfer_audit_trail ?? {});
  } catch {
    auditTrailReplay = null;
  }
  try {
    forensicsReplay = parseAssetForensicProjection(detail?.asset_forensic_projection ?? {});
  } catch {
    forensicsReplay = null;
  }
  const stepsOk = steps.length > 0 && steps.every((s: { ok?: boolean }) => Boolean(s.ok));
  const replayVerdict = deriveReplayVerdict({
    projection_status: projection.status,
    signature_valid: projection.verification.signature_valid,
    tamper_status: projection.verification.tamper_status,
    policy_trace_available: projection.verification.policy_trace_available,
    evidence_trace_available: projection.verification.evidence_trace_available,
    receipt_steps_ok: stepsOk,
    replay_verifiable: Boolean(chain.replay_verifiable),
    terminal_disposition: String(chain.terminal_disposition ?? ""),
    failure_active: failActive,
  });
  const replayCorr = deriveReplayCorrelationFlags({
    projection_status: projection.status,
    terminal_disposition: String(chain.terminal_disposition ?? ""),
    failure_active: failActive,
    failure_path: String(failure.path ?? ""),
  });
  const replayCaseVerdict =
    auditTrailReplay && forensicsReplay
      ? deriveCaseVerdictHeader(projection, auditTrailReplay, forensicsReplay)
      : deriveCaseVerdictFromProjectionOnly(projection);
  const replayCopilot =
    auditTrailReplay && forensicsReplay
      ? buildDeterministicCopilotBrief({
          workflow_id: workflowId,
          projection,
          audit: auditTrailReplay,
          forensics: forensicsReplay,
          correlation_flags: replayCorr,
          replay_verdict: replayVerdict,
        })
      : buildDeterministicCopilotBriefFromProjectionOnly(workflowId, projection, replayVerdict, replayCorr);
  const replayChangeSnap: Record<string, unknown> = {
    workflow_id: workflowId,
    replay_verdict: replayVerdict,
    projection_status: projection.status,
    terminal_disposition: String(chain.terminal_disposition ?? ""),
    failure_active: failActive,
    steps_ok: stepsOk,
  };
  return page(
    "Screen 4 — Replay / verification",
    `
      <h1>Screen 4 — Replay / verification</h1>
      <p class="sub">Receipt-chain checkpoints and explicit failure context for deny or quarantine paths.</p>
      ${renderSurfaceCrumbs(query, replaySelfRaw, { transferForensicsQuery: detailQuery })}
      ${renderReplayVerdictCard(replayVerdict, replayCorr)}
      ${renderCaseVerdictStrip(replayCaseVerdict)}
      ${renderCopilotReadOnlyPanel(replayCopilot)}
      ${renderChangeSinceLastLoad(`replay:${workflowId}`, replayChangeSnap)}

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
        <h2>Verification summary</h2>
        <div class="row">signature valid: <code>${String(projection.verification.signature_valid)}</code></div>
        <div class="row">policy trace available: <code>${String(projection.verification.policy_trace_available)}</code></div>
        <div class="row">evidence trace available: <code>${String(projection.verification.evidence_trace_available)}</code></div>
        <div class="row">tamper status: <code>${escapeHtml(projection.verification.tamper_status)}</code></div>
      </section>

      <section class="card">
        <h2>Verification actions</h2>
        <p class="sub">Open JSON contracts on the verification service (same host/port as API base in deployments).</p>
        <ul>
          <li>
            <a href="/api/v1/verification/workflows/${encodeURIComponent(workflowId)}/replay?${query}"><code>GET …/replay</code></a>
            — dedicated replay bundle (<code>seedcore.verification_replay.v1</code>)
          </li>
          <li>
            <a href="/api/v1/verification/workflows/${encodeURIComponent(workflowId)}/projection?${query}"><code>GET …/projection</code></a>
            — <code>VerificationSurfaceProjection</code>
          </li>
          <li>${projection.links.replay_ref ? `<a href="${escapeHtml(projection.links.replay_ref)}">Replay ref (from projection)</a>` : `<span class="empty">no replay ref on projection</span>`}</li>
          <li>${projection.links.trust_ref ? `<a href="${escapeHtml(projection.links.trust_ref)}">Trust ref</a>` : `<span class="empty">no trust ref</span>`}</li>
          <li>
            <a href="/api/v1/verification/runbook/lookup?reason_code=${encodeURIComponent(String(failure.reason_code ?? ""))}"><code>Runbook lookup</code></a>
            for current reason code
          </li>
        </ul>
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

      <section class="card table-scroll">
        <h2>Receipt chain</h2>
        <table class="data-table">
          <thead>
            <tr><th align="left">ID</th><th align="left">Step</th><th align="left">Ref</th><th align="left">Status</th><th align="left">Detail</th></tr>
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
    shell,
  );
}

export function renderTransferPage(reviewPayload: any, query: string, shell?: OperatorShellOptions): string {
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
  const replayHrefRaw = `/replay?${replayList.toString()}`;
  const caseVerdict = deriveCaseVerdictHeader(projection, auditTrail, forensics);
  const copilotBrief = buildDeterministicCopilotBrief({
    workflow_id: projection.workflow_id,
    projection,
    audit: auditTrail,
    forensics,
  });
  const transferChangeSnap: Record<string, unknown> = {
    workflow_id: projection.workflow_id,
    status: projection.status,
    disposition: auditTrail.decision.disposition,
    trust_gap_count: forensics.trust_gaps.length,
    replay_status: auditTrail.physical_evidence.replay_status,
    approval_state: projection.summary.approval_state,
  };
  return page(
    "Screen 2 — Transfer detail / audit trail",
    `
      <h1>Screen 2 — Transfer detail / audit trail</h1>
      <p class="sub">Side-by-side audit trail: request and authority, decision and artifacts, physical evidence and closure.</p>
      ${renderSurfaceCrumbs(query, replayHrefRaw)}
      ${renderCaseVerdictStrip(caseVerdict)}
      ${renderCopilotReadOnlyPanel(copilotBrief)}
      ${renderChangeSinceLastLoad(`transfer:${projection.workflow_id}`, transferChangeSnap)}

      <section class="card">
        <h2>Workflow projection</h2>
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
          <h2>Request and authority</h2>
          <div class="row">request id: <code>${escapeHtml(auditTrail.request.request_id)}</code></div>
          <div class="row">requested at: <code>${escapeHtml(auditTrail.request.requested_at)}</code></div>
          <div class="row">workflow type: <code>${escapeHtml(auditTrail.request.workflow_type)}</code></div>
          <div class="row">valid until: <code>${escapeHtml(auditTrail.request.valid_until ?? "none")}</code></div>
          <div class="row">idempotency key: <code>${escapeHtml(auditTrail.request.idempotency_key ?? "none")}</code></div>
          <div class="row">request summary: ${escapeHtml(auditTrail.request.request_summary)}</div>
          <div class="row">action type: <code>${escapeHtml(auditTrail.request.action_type)}</code></div>
          <h3>Principal and authority</h3>
          <div class="row">agent id: <code>${escapeHtml(auditTrail.principal.agent_id)}</code></div>
          <div class="row">role profile: <code>${escapeHtml(auditTrail.principal.role_profile)}</code></div>
          <div class="row">owner id: <code>${escapeHtml(auditTrail.principal.owner_id ?? "none")}</code></div>
          <div class="row">delegation ref: <code>${escapeHtml(auditTrail.principal.delegation_ref ?? "none")}</code></div>
          <div class="row">organization ref: <code>${escapeHtml(auditTrail.principal.organization_ref ?? "none")}</code></div>
          <div class="row">hardware fingerprint id: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.fingerprint_id ?? "none")}</code></div>
          <div class="row">node id: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.node_id ?? "none")}</code></div>
          <div class="row">public key fingerprint: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.public_key_fingerprint ?? "none")}</code></div>
          <div class="row">attestation type: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.attestation_type ?? "none")}</code></div>
          <div class="row">key ref: <code>${escapeHtml(auditTrail.principal.hardware_fingerprint.key_ref ?? "none")}</code></div>
          <h3>Scope</h3>
          <div class="row">scope id: <code>${escapeHtml(auditTrail.authority_scope.scope_id ?? "none")}</code></div>
          <div class="row">asset ref: <code>${escapeHtml(auditTrail.authority_scope.asset_ref)}</code></div>
          <div class="row">product ref: <code>${escapeHtml(auditTrail.authority_scope.product_ref ?? "none")}</code></div>
          <div class="row">facility ref: <code>${escapeHtml(auditTrail.authority_scope.facility_ref ?? "none")}</code></div>
          <div class="row">expected from zone: <code>${escapeHtml(auditTrail.authority_scope.expected_from_zone ?? "none")}</code></div>
          <div class="row">expected to zone: <code>${escapeHtml(auditTrail.authority_scope.expected_to_zone ?? "none")}</code></div>
          <div class="row">expected coordinate ref: <code>${escapeHtml(auditTrail.authority_scope.expected_coordinate_ref ?? "none")}</code></div>
          <div class="row">authority scope verdict: <code>${escapeHtml(auditTrail.authority_scope.authority_scope_verdict)}</code></div>
          <h3>Scope mismatch keys</h3>
          ${renderList(auditTrail.authority_scope.mismatch_keys)}
        </article>

        <article class="card">
          <h2>Decision and artifacts</h2>
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
          <h3>Minted artifacts</h3>
          ${renderList(auditTrail.artifacts.minted_artifacts)}
          <h3>Obligations</h3>
          ${renderList(auditTrail.artifacts.obligations.map((value: unknown) => JSON.stringify(value)))}
          <h3>Approvals</h3>
          <div class="row">approval status: <code>${escapeHtml(auditTrail.approvals.approval_status ?? "none")}</code></div>
          <div class="row">required approvers: <code>${escapeHtml(auditTrail.approvals.required.join(", ") || "none")}</code></div>
          <div class="row">completed by: <code>${escapeHtml(auditTrail.approvals.completed_by.join(", ") || "none")}</code></div>
          <div class="row">approval envelope id: <code>${escapeHtml(auditTrail.approvals.approval_envelope_id ?? "none")}</code></div>
          <div class="row">expected envelope version: <code>${escapeHtml(String(auditTrail.approvals.approval_envelope_version ?? "none"))}</code></div>
          <div class="row">approval binding hash: <code>${escapeHtml(auditTrail.approvals.approval_binding_hash ?? "none")}</code></div>
          <div class="row">co-signed (required satisfied): <code>${escapeHtml(
            String(
              auditTrail.approvals.required.length > 0
                && auditTrail.approvals.completed_by.length >= auditTrail.approvals.required.length,
            ),
          )}</code></div>
        </article>

        <article class="card">
          <h2>Physical evidence and closure</h2>
          <div class="row">current zone: <code>${escapeHtml(auditTrail.physical_evidence.current_zone ?? "none")}</code></div>
          <div class="row">current coordinate: <code>${escapeHtml(auditTrail.physical_evidence.current_coordinate_ref ?? "none")}</code></div>
          <div class="row">economic hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.economic_hash ?? "none")}</code></div>
          <div class="row">physical presence hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.physical_presence_hash ?? "none")}</code></div>
          <div class="row">reasoning hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.reasoning_hash ?? "none")}</code></div>
          <div class="row">actuator hash: <code>${escapeHtml(auditTrail.physical_evidence.fingerprint_components.actuator_hash ?? "none")}</code></div>
          <div class="row">replay status: <code>${escapeHtml(auditTrail.physical_evidence.replay_status)}</code></div>
          <div class="row">settlement status: <code>${escapeHtml(auditTrail.physical_evidence.settlement_status)}</code></div>
          <h3>Telemetry references</h3>
          ${renderList(auditTrail.physical_evidence.telemetry_refs)}
          <h3>Trust gaps</h3>
          ${renderList(forensics.trust_gaps)}
          <h3>Missing prerequisites</h3>
          ${renderList(forensics.missing_prerequisites)}
          <h3>Transfer links</h3>
          ${renderApiLinks([
            ["Workflow Projection API", projection.links.audit_trail_ref],
            ["Asset Forensics API", projection.links.forensics_ref],
            ["Replay Artifacts", auditTrail.links.replay_artifacts_ref ?? undefined],
            ["Public Trust", projection.links.trust_ref ?? undefined],
          ])}
        </article>
      </section>

      <section class="card">
        <h2>Governed timeline</h2>
        ${renderTimeline(forensics.timeline)}
      </section>
    `,
    shell,
  );
}

export function renderForensicsPage(forensicsPayload: any, query: string, shell?: OperatorShellOptions): string {
  const forensics = parseAssetForensicProjection(forensicsPayload);
  const cls = statusClass(forensics.business_state);
  const settlement = isRecord(forensicsPayload?.settlement) ? (forensicsPayload.settlement as Record<string, unknown>) : null;
  const qp = new URLSearchParams(query);
  const wf = qp.get("workflow_id") ?? "";
  const replayRaw = wf.length > 0 ? `/replay?workflow_id=${encodeURIComponent(wf)}&${query}` : undefined;
  const fv = deriveCaseVerdictFromForensicsOnly(forensics);
  const forensicCopilot = buildDeterministicCopilotBriefFromForensics(forensics);
  const forensicChangeSnap: Record<string, unknown> = {
    workflow_id: forensics.workflow_id,
    business_state: forensics.business_state,
    disposition: forensics.disposition,
    trust_gap_count: forensics.trust_gaps.length,
    decision_id: forensics.decision_id,
  };
  return page(
    "Screen 3 — Asset forensics",
    `
      <h1>Screen 3 — Asset forensics</h1>
      <p class="sub">Operator-facing forensic context for the Restricted Custody Transfer wedge.</p>
      ${renderSurfaceCrumbs(query, replayRaw)}
      ${renderCaseVerdictStrip(fv)}
      ${renderCopilotReadOnlyPanel(forensicCopilot)}
      ${renderChangeSinceLastLoad(`forensics:${forensics.workflow_id}`, forensicChangeSnap)}

      <section class="card">
        <h2>Forensic state</h2>
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
          <h2>Identity and custody</h2>
          <div class="row">requesting principal: <code>${escapeHtml(forensics.principal_identity.requesting_principal_ref)}</code></div>
          <div class="row">approving principals: <code>${escapeHtml(forensics.principal_identity.approving_principal_refs.join(", ") || "none")}</code></div>
          <div class="row">next custodian: <code>${escapeHtml(forensics.principal_identity.next_custodian_ref ?? "none")}</code></div>
          <h3>Custody transition</h3>
          <div class="row">from zone: <code>${escapeHtml(forensics.custody_transition.from_zone)}</code></div>
          <div class="row">to zone: <code>${escapeHtml(forensics.custody_transition.to_zone)}</code></div>
          <div class="row">facility: <code>${escapeHtml(forensics.custody_transition.facility_ref)}</code></div>
          <div class="row">custody point: <code>${escapeHtml(forensics.custody_transition.custody_point_ref)}</code></div>
          <div class="row">expected custodian: <code>${escapeHtml(forensics.custody_transition.expected_current_custodian)}</code></div>
          <div class="row">next custodian: <code>${escapeHtml(forensics.custody_transition.next_custodian)}</code></div>
          <h3>Runtime custody state</h3>
          <div class="row">current custodian: <code>${escapeHtml(forensics.asset_custody_state.current_custodian_ref ?? "none")}</code></div>
          <div class="row">current zone: <code>${escapeHtml(forensics.asset_custody_state.current_zone_ref ?? "none")}</code></div>
          <div class="row">custody point: <code>${escapeHtml(forensics.asset_custody_state.custody_point_ref ?? "none")}</code></div>
          <div class="row">authority source: <code>${escapeHtml(forensics.asset_custody_state.authority_source ?? "none")}</code></div>
        </article>

        <article class="card">
          <h2>Telemetry and signatures</h2>
          <h3>Telemetry references</h3>
          ${renderList(forensics.telemetry_refs)}
          <h3>Forensic fingerprint</h3>
          <div class="row">economic hash: <code>${escapeHtml(forensics.forensic_fingerprint.economic_hash ?? "none")}</code></div>
          <div class="row">physical presence hash: <code>${escapeHtml(forensics.forensic_fingerprint.physical_presence_hash ?? "none")}</code></div>
          <div class="row">reasoning hash: <code>${escapeHtml(forensics.forensic_fingerprint.reasoning_hash ?? "none")}</code></div>
          <div class="row">actuator hash: <code>${escapeHtml(forensics.forensic_fingerprint.actuator_hash ?? "none")}</code></div>
          <h3>Signature provenance</h3>
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
          <h2>Trust review</h2>
          <h3>Trust gaps</h3>
          ${renderList(forensics.trust_gaps)}
          <h3>Missing prerequisites</h3>
          ${renderList(forensics.missing_prerequisites)}
          <h3>Minted artifacts</h3>
          ${renderList(forensics.minted_artifacts)}
        </article>

        <article class="card">
          <h2>Obligations and timeline</h2>
          <h3>Obligations</h3>
          ${renderList(forensics.obligations.map((value: unknown) => JSON.stringify(value)))}
          <h3>Forensic links</h3>
          ${renderApiLinks([
            ["Workflow Projection API", forensics.links.workflow_projection_ref],
            ["Transfer Audit Trail API", forensics.links.transfer_audit_trail_ref],
            ["Public Trust", forensics.links.trust_ref ?? undefined],
            ["Replay Artifacts", forensics.links.replay_artifacts_ref ?? undefined],
          ])}
          <h3>Governed timeline</h3>
          ${renderTimeline(forensics.timeline)}
        </article>
      </section>

      <section class="card">
        <h2>Settlement and twin (Workstream 3)</h2>
        ${
          settlement
            ? `<div class="row">status: <code>${escapeHtml(String(settlement.status ?? "unknown"))}</code></div>
          <div class="row">twin mutation ref: <code>${escapeHtml(String(settlement.twin_mutation_ref ?? "none"))}</code></div>
          <div class="row">physical location: <code>${escapeHtml(String(settlement.physical_location_ref ?? "none"))}</code></div>`
            : `<p class="sub">Extended settlement and digital-twin linkage will populate this card when the forensic projection carries a <code>settlement</code> object. Closure fields remain on the audit trail today.</p>`
        }
      </section>
    `,
    shell,
  );
}
