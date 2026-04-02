import http from "node:http";
import process from "node:process";

import { page, renderCatalogPage, renderForensicsPage, renderTransferPage } from "./ui.js";

const apiBase = process.env.SEEDCORE_VERIFICATION_API_BASE ?? "http://127.0.0.1:7071";

async function fetchJson(apiPath: string): Promise<any> {
  const response = await fetch(`${apiBase}${apiPath}`);
  if (!response.ok) {
    throw new Error(`${response.status}:${response.statusText}`);
  }
  return response.json();
}

function queryString(url: URL): string {
  const params = new URLSearchParams(url.search);
  if (!params.has("source")) {
    params.set("source", "fixture");
  }
  if (params.get("source") === "fixture" && !params.has("dir")) {
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
    const qs = queryString(url);
    if (url.pathname === "/") {
      const catalog = await fetchJson(`/api/v1/verification/transfers/catalog?${qs}`);
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderCatalogPage(catalog));
      return;
    }

    if (url.pathname === "/transfer") {
      const review = await fetchJson(`/api/v1/verification/transfers/review?${qs}`);
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderTransferPage(review, qs));
      return;
    }

    if (url.pathname === "/forensics") {
      const forensics = await fetchJson(`/api/v1/verification/assets/forensics?${qs}`);
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(renderForensicsPage(forensics, qs));
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
