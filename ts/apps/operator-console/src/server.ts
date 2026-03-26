import http from "node:http";
import process from "node:process";

const apiBase = process.env.SEEDCORE_VERIFICATION_API_BASE ?? "http://127.0.0.1:7071";

function page(title: string, body: string): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
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
    main { max-width: 1040px; margin: 28px auto; padding: 0 16px 48px; }
    h1, h2, h3 { margin: 0 0 10px; line-height: 1.2; }
    h1 { font-size: 34px; letter-spacing: -0.02em; }
    .sub { color: var(--muted); margin-bottom: 16px; }
    .grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
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
    .split {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
    }
  </style>
</head>
<body>
  <main>${body}</main>
</body>
</html>`;
}

function statusClass(state: string): "ok" | "warn" | "bad" {
  if (state === "verified") {
    return "ok";
  }
  if (state === "quarantined" || state === "review_required") {
    return "warn";
  }
  return "bad";
}

async function fetchJson(apiPath: string): Promise<any> {
  const response = await fetch(`${apiBase}${apiPath}`);
  if (!response.ok) {
    throw new Error(`${response.status}:${response.statusText}`);
  }
  return response.json();
}

function renderListPage(catalog: any): string {
  const items = Array.isArray(catalog?.items) ? catalog.items : [];
  const cards = items
    .map((item: any) => {
      const summary = item.summary ?? {};
      const cls = statusClass(summary.business_state ?? "verification_failed");
      return `
        <article class="card">
          <h3>${item.id}</h3>
          <div class="row">
            <span class="status ${cls}">${summary.business_state ?? "unknown"}</span>
            <span class="status">${summary.disposition ?? "unknown"}</span>
            <span class="status">${summary.approval_status ?? "unknown"}</span>
          </div>
          <div class="row">verified: <code>${String(summary.verified)}</code></div>
          <div class="row">token expected/present: <code>${String(summary.execution_token_expected)} / ${String(summary.execution_token_present)}</code></div>
          <div class="row"><a href="/transfer?dir=${encodeURIComponent(item.dir)}">Open workflow review</a></div>
        </article>
      `;
    })
    .join("");

  return page(
    "SeedCore Operator Console",
    `
      <h1>Restricted Custody Transfer Operator Console</h1>
      <p class="sub">Narrow operator surface for intake triage, quarantine/review routing, and approval-state visibility.</p>
      <section class="grid">
        ${cards || `<article class="card"><p class="empty">No transfer fixture scenarios found.</p></article>`}
      </section>
    `,
  );
}

function renderList(values: string[]): string {
  if (!Array.isArray(values) || values.length === 0) {
    return `<p class="empty">none</p>`;
  }
  return `<ul>${values.map((value) => `<li><code>${value}</code></li>`).join("")}</ul>`;
}

function renderTransferPage(review: any, dir: string): string {
  const summary = review.summary ?? {};
  const transfer = review.transfer_proof ?? {};
  const asset = review.asset_proof ?? {};
  const cls = statusClass(transfer.business_state ?? "verification_failed");

  return page(
    "Transfer Workflow Review",
    `
      <h1>Transfer Workflow Review</h1>
      <p class="sub">Operator view for approval state, decision disposition, and replay verification status.</p>
      <p class="row">Scenario directory: <code>${dir}</code></p>
      <p class="row"><a href="/">Back to scenario list</a></p>

      <section class="card">
        <h2>Current State</h2>
        <div class="row">
          <span class="status ${cls}">${transfer.business_state ?? "unknown"}</span>
          <span class="status">${transfer.disposition ?? "unknown"}</span>
          <span class="status">${transfer.approval_status ?? "unknown"}</span>
        </div>
        <div class="row">verified: <code>${String(transfer.verified)}</code></div>
        <div class="row">verification error: <code>${transfer.verification_error_code ?? "none"}</code></div>
        <div class="row">execution token: <code>${transfer.execution_token_id ?? "none"}</code></div>
      </section>

      <section class="split">
        <article class="card">
          <h2>Approval + Workflow Identity</h2>
          <div class="row">asset: <code>${transfer.asset_ref ?? "unknown"}</code></div>
          <div class="row">intent: <code>${transfer.intent_ref ?? "unknown"}</code></div>
          <div class="row">decision: <code>${transfer.decision_id ?? "unknown"}</code></div>
          <div class="row">policy receipt: <code>${transfer.policy_receipt_id ?? "unknown"}</code></div>
          <h3>Verifier Checks</h3>
          ${renderList(Array.isArray(summary.checks) ? summary.checks : [])}
        </article>

        <article class="card">
          <h2>Review + Quarantine Signals</h2>
          <h3>Missing Prerequisites</h3>
          ${renderList(Array.isArray(asset.missing_prerequisites) ? asset.missing_prerequisites : [])}
          <h3>Trust Gaps</h3>
          ${renderList(Array.isArray(asset.trust_gaps) ? asset.trust_gaps : [])}
          <div class="row">policy snapshot: <code>${asset.policy_snapshot_ref ?? "unknown"}</code></div>
        </article>
      </section>
    `,
  );
}

const server = http.createServer(async (req, res) => {
  if (!req.url) {
    res.writeHead(400).end("missing_url");
    return;
  }
  const url = new URL(req.url, "http://127.0.0.1");

  if (url.pathname === "/health") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: true, app: "operator-console" }));
    return;
  }

  try {
    if (url.pathname === "/") {
      const catalog = await fetchJson("/api/v1/transfers/catalog");
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderListPage(catalog));
      return;
    }

    if (url.pathname === "/transfer") {
      const dir = url.searchParams.get("dir") ?? "rust/fixtures/transfers/allow_case";
      const review = await fetchJson(`/api/v1/transfers/review?dir=${encodeURIComponent(dir)}`);
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderTransferPage(review, dir));
      return;
    }

    res.writeHead(404).end("not_found");
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown_error";
    res.writeHead(500, { "content-type": "text/html; charset=utf-8" });
    res.end(page("Operator Console Error", `<h1>Operator Console Error</h1><p class="bad">${detail}</p>`));
  }
});

const port = Number.parseInt(process.env.PORT ?? "7073", 10);
server.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`operator-console listening on http://127.0.0.1:${port}`);
});
