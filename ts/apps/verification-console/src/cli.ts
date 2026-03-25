import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { parseTransferTrustSummary } from "@seedcore/contracts";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, "../../../..");
const COMMAND_CWD = process.env.INIT_CWD ?? process.cwd();

function parseRequiredArg(flag: string): string {
  const index = process.argv.indexOf(flag);
  const value = index >= 0 ? process.argv[index + 1] : undefined;
  if (!value || value.startsWith("--")) {
    throw new Error(`missing_flag:${flag}`);
  }
  return value;
}

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

function resolveFixtureDir(rawPath: string): string {
  if (path.isAbsolute(rawPath)) {
    return rawPath;
  }

  const candidates = [
    path.resolve(COMMAND_CWD, rawPath),
    path.resolve(REPO_ROOT, rawPath),
  ];

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return path.resolve(COMMAND_CWD, rawPath);
}

function main(): void {
  const fixtureDir = resolveFixtureDir(parseRequiredArg("--dir"));
  const verifyBin = resolveVerifyBinary();

  const raw = execFileSync(
    verifyBin,
    ["summarize-transfer", "--dir", fixtureDir],
    {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const summary = parseTransferTrustSummary(JSON.parse(raw));

  console.log("SeedCore Transfer Trust Summary");
  console.log(`- business_state: ${summary.business_state}`);
  console.log(`- disposition: ${summary.disposition}`);
  console.log(`- approval_status: ${summary.approval_status}`);
  console.log(`- verified: ${summary.verified}`);
  console.log(`- execution_token_expected: ${summary.execution_token_expected}`);
  console.log(`- execution_token_present: ${summary.execution_token_present}`);
  console.log(
    `- verification_error_code: ${summary.verification_error_code ?? "none"}`,
  );
}

main();
