import http from "node:http";
import process from "node:process";

import {
  page,
  type HotPathBanner,
  type OperatorShellOptions,
  renderCatalogPage,
  renderForensicsPage,
  renderQueuePage,
  renderReplayPage,
  renderRunbooksPage,
  renderTransferPage,
} from "./ui.js";

const apiBase = process.env.SEEDCORE_VERIFICATION_API_BASE ?? "http://127.0.0.1:7071";
const runtimeBase = process.env.SEEDCORE_RUNTIME_API_BASE ?? "http://127.0.0.1:8002/api/v1";
const DEFAULT_LIST_QS = "source=fixture&root=rust/fixtures/transfers";

async function fetchJson(apiPath: string): Promise<any> {
  const response = await fetch(`${apiBase}${apiPath}`);
  if (!response.ok) {
    throw new Error(`${response.status}:${response.statusText}`);
  }
  return response.json();
}

async function fetchHotPathBanner(): Promise<HotPathBanner | null> {
  if (process.env.SEEDCORE_OPERATOR_SKIP_HOT_PATH_BANNER === "1") {
    return null;
  }
  try {
    const controller = new AbortController();
    const kill = setTimeout(() => controller.abort(), 1500);
    const response = await fetch(`${runtimeBase}/pdp/hot-path/status`, { signal: controller.signal });
    clearTimeout(kill);
    if (!response.ok) {
      return null;
    }
    const body = await response.json();
    const obs = body.observability ?? {};
    return {
      resolved_mode: String(body.resolved_mode ?? body.mode ?? "unknown"),
      graph_freshness_ok: Boolean(body.graph_freshness_ok),
      alert_level: String(obs.alert_level ?? "unknown"),
    };
  } catch {
    return null;
  }
}

function operatorShell(
  nav: OperatorShellOptions["nav"],
  listQuery: string,
  hotPath: HotPathBanner | null,
): OperatorShellOptions {
  return { nav, listQuery, hotPath };
}

function queryString(url: URL, mode: "catalog" | "single" | "replay"): string {
  const params = new URLSearchParams(url.search);
  if (!params.has("source")) {
    params.set("source", "fixture");
  }
  if ((mode === "catalog" || mode === "replay") && !params.has("root") && !params.has("dir")) {
    params.set("root", "rust/fixtures/transfers");
  }
  if (
    mode === "single"
    && params.get("source") === "fixture"
    && !params.has("dir")
    && !params.has("root")
    && !params.has("workflow_id")
  ) {
    params.set("dir", "rust/fixtures/transfers/allow_case");
  }
  return params.toString();
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
    if (url.pathname === "/search") {
      const q = url.searchParams.get("q")?.trim() ?? "";
      if (!q) {
        res.writeHead(302, { Location: `/queue?${DEFAULT_LIST_QS}` });
        res.end();
        return;
      }
      const qLower = q.toLowerCase();
      if (qLower.startsWith("envelope:") || qLower.startsWith("approval:")) {
        const raw = q.replace(/^[^:]+:/, "").trim();
        if (raw) {
          const p = new URLSearchParams(DEFAULT_LIST_QS);
          p.set("approval_envelope_id", raw);
          res.writeHead(302, { Location: `/queue?${p.toString()}` });
          res.end();
          return;
        }
      }
      if (qLower.startsWith("request:")) {
        const raw = q.slice("request:".length).trim();
        if (raw) {
          const p = new URLSearchParams(DEFAULT_LIST_QS);
          p.set("request_id", raw);
          res.writeHead(302, { Location: `/queue?${p.toString()}` });
          res.end();
          return;
        }
      }
      if (q.startsWith("asset:")) {
        res.writeHead(302, {
          Location: `/forensics?source=runtime&subject_id=${encodeURIComponent(q)}`,
        });
        res.end();
        return;
      }
      const uuidRe =
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      if (uuidRe.test(q)) {
        res.writeHead(302, {
          Location: `/transfer?source=runtime&audit_id=${encodeURIComponent(q)}`,
        });
        res.end();
        return;
      }
      res.writeHead(302, {
        Location: `/replay?workflow_id=${encodeURIComponent(q)}&${DEFAULT_LIST_QS}`,
      });
      res.end();
      return;
    }

    if (url.pathname === "/") {
      const qs = queryString(url, "catalog");
      const catalog = await fetchJson(`/api/v1/verification/transfers/catalog?${qs}`);
      const hotPath = await fetchHotPathBanner();
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderCatalogPage(catalog, qs, operatorShell("transfers", qs, hotPath)));
      return;
    }

    if (url.pathname === "/queue") {
      const qs = queryString(url, "catalog");
      const queue = await fetchJson(`/api/v1/verification/transfers/queue?${qs}`);
      const hotPath = await fetchHotPathBanner();
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderQueuePage(queue, qs, operatorShell("verification", qs, hotPath)));
      return;
    }

    if (url.pathname === "/runbooks") {
      const idx = await fetchJson("/api/v1/verification/runbook");
      const hotPath = await fetchHotPathBanner();
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderRunbooksPage(idx, operatorShell("runbooks", DEFAULT_LIST_QS, hotPath), apiBase, DEFAULT_LIST_QS));
      return;
    }

    if (url.pathname === "/replay") {
      const wf = url.searchParams.get("workflow_id")?.trim();
      if (!wf) {
        res.writeHead(400, { "content-type": "text/html; charset=utf-8" });
        res.end(page("Replay view", "<h1>Replay / verification</h1><p>Missing <code>workflow_id</code> query parameter.</p>"));
        return;
      }
      const qs = queryString(url, "replay");
      const detail = await fetchJson(
        `/api/v1/verification/workflows/${encodeURIComponent(wf)}/verification-detail?${qs}`,
      );
      const hotPath = await fetchHotPathBanner();
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderReplayPage(detail, qs, wf, operatorShell("verification", qs, hotPath)));
      return;
    }

    if (url.pathname === "/transfer") {
      const qs = queryString(url, "single");
      const review = await fetchJson(`/api/v1/verification/transfers/review?${qs}`);
      const hotPath = await fetchHotPathBanner();
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderTransferPage(review, qs, operatorShell("verification", qs, hotPath)));
      return;
    }

    if (url.pathname === "/forensics") {
      const qs = queryString(url, "single");
      const forensics = await fetchJson(`/api/v1/verification/assets/forensics?${qs}`);
      const hotPath = await fetchHotPathBanner();
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderForensicsPage(forensics, qs, operatorShell("verification", qs, hotPath)));
      return;
    }

    res.writeHead(404).end("not_found");
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown_error";
    res.writeHead(500, { "content-type": "text/html; charset=utf-8" });
    res.end(page("Operator Console Error", `<h1>Operator Console Error</h1><p>${detail}</p>`));
  }
});

const port = Number.parseInt(process.env.PORT ?? "7073", 10);
server.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`operator-console listening on http://127.0.0.1:${port}`);
});
