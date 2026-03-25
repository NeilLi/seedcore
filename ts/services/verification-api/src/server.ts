import { execFileSync } from "node:child_process";
import http from "node:http";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import {
  parseTransferTrustSummary,
  parseTransferVerificationReport,
  toAssetProofView,
  toTransferProofView,
} from "@seedcore/contracts";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, "../../../..");
const COMMAND_CWD = process.env.INIT_CWD ?? process.cwd();
const DEFAULT_TRANSFER_DIR = "rust/fixtures/transfers/allow_case";

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

function resolveFixtureDir(rawPath?: string | null): string {
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

function runVerifier(command: "summarize-transfer" | "verify-transfer", dir: string): unknown {
  const verifyBin = resolveVerifyBinary();
  const output = execFileSync(verifyBin, [command, "--dir", dir], {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return JSON.parse(output);
}

function jsonResponse(
  res: http.ServerResponse,
  statusCode: number,
  payload: unknown,
): void {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (!req.url) {
    jsonResponse(res, 400, { error: "missing_url" });
    return;
  }
  const url = new URL(req.url, "http://127.0.0.1");

  try {
    if (url.pathname === "/health") {
      jsonResponse(res, 200, { ok: true, service: "verification-api" });
      return;
    }

    if (req.method !== "GET") {
      jsonResponse(res, 405, { error: "method_not_allowed" });
      return;
    }

    const dir = resolveFixtureDir(url.searchParams.get("dir"));
    if (url.pathname === "/api/v1/transfers/summary") {
      const summary = parseTransferTrustSummary(runVerifier("summarize-transfer", dir));
      jsonResponse(res, 200, summary);
      return;
    }

    if (url.pathname === "/api/v1/transfers/proof") {
      const summary = parseTransferTrustSummary(runVerifier("summarize-transfer", dir));
      const report = parseTransferVerificationReport(runVerifier("verify-transfer", dir));
      jsonResponse(res, 200, toTransferProofView(report, summary));
      return;
    }

    if (url.pathname === "/api/v1/assets/proof") {
      const summary = parseTransferTrustSummary(runVerifier("summarize-transfer", dir));
      const report = parseTransferVerificationReport(runVerifier("verify-transfer", dir));
      jsonResponse(res, 200, toAssetProofView(report, summary));
      return;
    }

    jsonResponse(res, 404, { error: "not_found" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown_error";
    jsonResponse(res, 500, { error: "verification_failed", detail: message });
  }
});

const port = Number.parseInt(process.env.PORT ?? "7071", 10);
server.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`verification-api listening on http://127.0.0.1:${port}`);
});

