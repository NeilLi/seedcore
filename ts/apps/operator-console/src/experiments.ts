import { createHash, randomUUID } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import process from "node:process";

import { createClient, type FlagsClient } from "@vercel/flags-core";

export type OperatorShellVariant = "control" | "treatment";

type OperatorShellSource =
  | "env_override"
  | "query_override"
  | "cookie_override"
  | "vercel_flags"
  | "local_hash_fallback";

export type OperatorShellExperiment = {
  key: string;
  variant: OperatorShellVariant;
  source: OperatorShellSource;
};

type VercelEntities = {
  user: {
    id: string;
  };
};

const SESSION_COOKIE = "seedcore_operator_session";
const OVERRIDE_COOKIE = "seedcore_exp_operator_shell";
const OVERRIDE_QUERY = "exp_operator_shell";
const FLAG_KEY = process.env.SEEDCORE_OPERATOR_SHELL_FLAG_KEY ?? "seedcore-operator-console-treatment";

const flagsConnection = process.env.FLAGS?.trim();
const flagsClient: FlagsClient<VercelEntities> | null = flagsConnection
  ? createClient<VercelEntities>(flagsConnection, { stream: false, polling: false })
  : null;
let flagsInitPromise: Promise<void> | null = null;
let flagsUnavailable = false;

function parseCookies(cookieHeader: string | undefined): Map<string, string> {
  const out = new Map<string, string>();
  if (!cookieHeader) {
    return out;
  }
  for (const token of cookieHeader.split(";")) {
    const idx = token.indexOf("=");
    if (idx < 1) {
      continue;
    }
    const key = token.slice(0, idx).trim();
    const valueRaw = token.slice(idx + 1).trim();
    if (!key) {
      continue;
    }
    try {
      out.set(key, decodeURIComponent(valueRaw));
    } catch {
      out.set(key, valueRaw);
    }
  }
  return out;
}

function appendSetCookie(res: ServerResponse, cookieValue: string): void {
  const prev = res.getHeader("set-cookie");
  if (prev === undefined) {
    res.setHeader("set-cookie", cookieValue);
    return;
  }
  if (Array.isArray(prev)) {
    res.setHeader("set-cookie", [...prev, cookieValue]);
    return;
  }
  res.setHeader("set-cookie", [String(prev), cookieValue]);
}

function cookieAttrs(req: IncomingMessage): string {
  const forwardedProto = req.headers["x-forwarded-proto"];
  const isSecure =
    typeof forwardedProto === "string"
      ? forwardedProto.split(",").some((entry) => entry.trim().toLowerCase() === "https")
      : false;
  return isSecure ? "; Path=/; HttpOnly; SameSite=Lax; Secure" : "; Path=/; HttpOnly; SameSite=Lax";
}

function setCookie(
  req: IncomingMessage,
  res: ServerResponse,
  key: string,
  value: string,
  maxAgeSeconds: number,
): void {
  const payload =
    `${key}=${encodeURIComponent(value)}; Max-Age=${maxAgeSeconds}${cookieAttrs(req)}`;
  appendSetCookie(res, payload);
}

function parseVariant(raw: string | null | undefined): OperatorShellVariant | null {
  if (!raw) {
    return null;
  }
  const normalized = raw.trim().toLowerCase();
  if (normalized === "control" || normalized === "a" || normalized === "0" || normalized === "off") {
    return "control";
  }
  if (
    normalized === "treatment"
    || normalized === "b"
    || normalized === "1"
    || normalized === "on"
  ) {
    return "treatment";
  }
  return null;
}

function getOrSetSessionId(req: IncomingMessage, res: ServerResponse, cookies: Map<string, string>): string {
  const existing = cookies.get(SESSION_COOKIE);
  if (existing && existing.length >= 16) {
    return existing;
  }
  const generated = randomUUID();
  setCookie(req, res, SESSION_COOKIE, generated, 60 * 60 * 24 * 365);
  return generated;
}

function localDeterministicVariant(sessionId: string): OperatorShellVariant {
  const digest = createHash("sha256").update(`${FLAG_KEY}:${sessionId}`).digest("hex");
  const firstByte = Number.parseInt(digest.slice(0, 2), 16);
  return firstByte % 2 === 0 ? "control" : "treatment";
}

async function ensureFlagsClientInitialized(): Promise<boolean> {
  if (!flagsClient || flagsUnavailable) {
    return false;
  }
  if (!flagsInitPromise) {
    flagsInitPromise = Promise.resolve(flagsClient.initialize()).catch(() => {
      flagsUnavailable = true;
      throw new Error("flags_init_failed");
    });
  }
  try {
    await flagsInitPromise;
    return true;
  } catch {
    return false;
  }
}

export async function resolveOperatorShellExperiment(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<OperatorShellExperiment> {
  const envOverride = parseVariant(process.env.SEEDCORE_OPERATOR_SHELL_FORCE);
  if (envOverride) {
    return { key: FLAG_KEY, variant: envOverride, source: "env_override" };
  }

  const cookies = parseCookies(req.headers.cookie);
  const queryOverride = parseVariant(url.searchParams.get(OVERRIDE_QUERY));
  if (queryOverride) {
    setCookie(req, res, OVERRIDE_COOKIE, queryOverride, 60 * 60 * 24 * 30);
    return { key: FLAG_KEY, variant: queryOverride, source: "query_override" };
  }

  const cookieOverride = parseVariant(cookies.get(OVERRIDE_COOKIE));
  if (cookieOverride) {
    return { key: FLAG_KEY, variant: cookieOverride, source: "cookie_override" };
  }

  const sessionId = getOrSetSessionId(req, res, cookies);
  const ready = await ensureFlagsClientInitialized();
  if (ready && flagsClient) {
    try {
      const result = await flagsClient.evaluate<boolean>(FLAG_KEY, false, {
        user: { id: sessionId },
      });
      if (result.reason !== "error") {
        return {
          key: FLAG_KEY,
          variant: result.value ? "treatment" : "control",
          source: "vercel_flags",
        };
      }
    } catch {
      flagsUnavailable = true;
    }
  }

  return {
    key: FLAG_KEY,
    variant: localDeterministicVariant(sessionId),
    source: "local_hash_fallback",
  };
}
