import http from "node:http";
import process from "node:process";

const DEFAULT_TRANSFER_DIR = "rust/fixtures/transfers/allow_case";
const apiBase = process.env.SEEDCORE_VERIFICATION_API_BASE ?? "http://127.0.0.1:7071";

function htmlPage(title: string, content: string): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --accent: #22d3ee;
      --ok: #34d399;
      --warn: #f59e0b;
      --bad: #f87171;
      --border: #1f2937;
    }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: radial-gradient(circle at 20% 0%, #0b1228 0%, var(--bg) 45%);
      color: var(--text);
    }
    main { max-width: 920px; margin: 40px auto; padding: 0 16px; }
    h1, h2 { margin: 0 0 16px; }
    .card {
      background: linear-gradient(180deg, rgba(17, 24, 39, 0.95), rgba(17, 24, 39, 0.88));
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
      margin-bottom: 18px;
    }
    .muted { color: var(--muted); }
    code { color: var(--accent); }
    a { color: var(--accent); text-decoration: none; }
    .pill {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid var(--border);
      margin-right: 8px;
      font-size: 13px;
    }
    .ok { color: var(--ok); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    ul { margin: 8px 0 0; padding-left: 18px; }
  </style>
</head>
<body>
  <main>${content}</main>
</body>
</html>`;
}

function stateClass(state: string): "ok" | "warn" | "bad" {
  if (state === "verified") {
    return "ok";
  }
  if (state === "quarantined" || state === "review_required") {
    return "warn";
  }
  return "bad";
}

function buildApiQuery(url: URL): string {
  const params = new URLSearchParams(url.search);
  if (!params.has("source")) {
    params.set("source", "fixture");
  }
  if (params.get("source") === "fixture" && !params.has("dir")) {
    params.set("dir", DEFAULT_TRANSFER_DIR);
  }
  return params.toString();
}

async function fetchJson(path: string, query: string): Promise<any> {
  const url = `${apiBase}${path}?${query}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status}:${response.statusText}`);
  }
  return response.json();
}

const server = http.createServer(async (req, res) => {
  if (!req.url) {
    res.writeHead(400).end("missing_url");
    return;
  }
  const url = new URL(req.url, "http://127.0.0.1");
  const query = buildApiQuery(url);
  const fixtureDir = url.searchParams.get("dir") ?? DEFAULT_TRANSFER_DIR;
  const source = url.searchParams.get("source") ?? "fixture";
  const publicTrustUrl = url.searchParams.get("public_trust");

  if (url.pathname === "/health") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: true, app: "proof-surface" }));
    return;
  }

  try {
    if (url.pathname === "/") {
      const content = `
        <h1>SeedCore Proof Surface</h1>
        <div class="card">
          <p class="muted">Narrow trust surface for Restricted Custody Transfer.</p>
          <p><a href="/transfer?${query}">Open transfer proof page</a></p>
          <p><a href="/asset?${query}">Open asset proof page</a></p>
          <p class="muted">Fixture dir: <code>${fixtureDir}</code></p>
        </div>
      `;
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(htmlPage("SeedCore Proof Surface", content));
      return;
    }

    if (url.pathname === "/transfer") {
      const proof = await fetchJson("/api/v1/transfers/proof", query);
      let resolvedPublicTrustUrl = publicTrustUrl;
      if (!resolvedPublicTrustUrl && source === "runtime") {
        try {
          const review = await fetchJson("/api/v1/transfers/review", query);
          resolvedPublicTrustUrl = review?.status?.links?.public_trust ?? review?.asset_forensics?.links?.public_trust;
        } catch {
          resolvedPublicTrustUrl = null;
        }
      }
      const cls = stateClass(proof.business_state);
      const checks = Array.isArray(proof.checks) ? proof.checks : [];
      const content = `
        <h1>Transfer Proof Page</h1>
        <div class="card">
          <span class="pill ${cls}">${proof.business_state}</span>
          <span class="pill">${proof.disposition}</span>
          <span class="pill">${proof.approval_status ?? "N/A"}</span>
          <h2>Identity</h2>
          <p>Asset: <code>${proof.asset_ref}</code></p>
          <p>Intent: <code>${proof.intent_ref}</code></p>
          <p>Decision: <code>${proof.decision_id}</code></p>
          <p>Approval Envelope: <code>${proof.approval_envelope_id ?? "none"}</code></p>
          <p>Approval Version: <code>${proof.approval_envelope_version ?? "none"}</code></p>
          <p>Approval Binding: <code>${proof.approval_binding_hash ?? "none"}</code></p>
          <p>Policy Receipt: <code>${proof.policy_receipt_id}</code></p>
          <p>Transition Receipts: <code>${Array.isArray(proof.transition_receipt_ids) && proof.transition_receipt_ids.length > 0 ? proof.transition_receipt_ids.join(", ") : "none"}</code></p>
          <p>Execution Token: <code>${proof.execution_token_id ?? "none"}</code></p>
          <h2>Verification</h2>
          <p>Verified: <code>${String(proof.verified)}</code></p>
          <p>Error: <code>${proof.verification_error_code ?? "none"}</code></p>
          ${resolvedPublicTrustUrl ? `<p>Public trust: <a href="${resolvedPublicTrustUrl}">Open trust page</a></p>` : ""}
          <h2>Checks</h2>
          <ul>${checks.map((check: string) => `<li><code>${check}</code></li>`).join("")}</ul>
          <p style="margin-top:16px;"><a href="/asset?${query}">Open related asset proof</a></p>
        </div>
      `;
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(htmlPage("Transfer Proof", content));
      return;
    }

    if (url.pathname === "/asset") {
      const proof = await fetchJson("/api/v1/assets/proof", query);
      let resolvedPublicTrustUrl = publicTrustUrl;
      if (!resolvedPublicTrustUrl && source === "runtime") {
        try {
          const forensics = await fetchJson("/api/v1/assets/forensics", query);
          resolvedPublicTrustUrl = forensics?.links?.public_trust;
        } catch {
          resolvedPublicTrustUrl = null;
        }
      }
      const cls = stateClass(proof.business_state);
      const missing = Array.isArray(proof.missing_prerequisites) ? proof.missing_prerequisites : [];
      const gaps = Array.isArray(proof.trust_gaps) ? proof.trust_gaps : [];
      const content = `
        <h1>Asset Proof Page</h1>
        <div class="card">
          <span class="pill ${cls}">${proof.business_state}</span>
          <span class="pill">${proof.disposition}</span>
          <h2>Asset Evidence</h2>
          <p>Asset: <code>${proof.asset_ref}</code></p>
          <p>Snapshot: <code>${proof.policy_snapshot_ref}</code></p>
          <p>Decision: <code>${proof.decision_id}</code></p>
          <h2>Trust Gaps</h2>
          <ul>${gaps.length > 0 ? gaps.map((gap: string) => `<li><code>${gap}</code></li>`).join("") : "<li>none</li>"}</ul>
          <h2>Missing Prerequisites</h2>
          <ul>${missing.length > 0 ? missing.map((item: string) => `<li><code>${item}</code></li>`).join("") : "<li>none</li>"}</ul>
          ${resolvedPublicTrustUrl ? `<p>Public trust: <a href="${resolvedPublicTrustUrl}">Open trust page</a></p>` : ""}
          <p style="margin-top:16px;"><a href="/transfer?${query}">Open related transfer proof</a></p>
        </div>
      `;
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(htmlPage("Asset Proof", content));
      return;
    }

    res.writeHead(404).end("not_found");
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown_error";
    res.writeHead(500, { "content-type": "text/html; charset=utf-8" });
    res.end(
      htmlPage(
        "Proof Surface Error",
        `<h1>Proof Surface Error</h1><div class="card"><p class="bad">${detail}</p></div>`,
      ),
    );
  }
});

const port = Number.parseInt(process.env.PORT ?? "7072", 10);
server.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`proof-surface listening on http://127.0.0.1:${port}`);
});
