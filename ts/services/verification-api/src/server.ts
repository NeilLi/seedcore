import http from "node:http";
import process from "node:process";

import {
  buildAssetScenario,
  buildTransferScenario,
  buildTransferScenarioByWorkflowId,
  buildVerificationDetailForWorkflow,
  buildVerificationReplayForWorkflow,
  listTransferCatalog,
  listTransferQueue,
  parseTransferQuery,
  resolveScenarioByAssetRef,
} from "./transferSources.js";
import { buildScenarioForOperatorCopilot, resolveOperatorCopilotBrief } from "./operatorCopilot.js";
import { getRunbook, listRunbookSummaries, lookupRunbooksForQuery } from "./runbooks.js";

function jsonResponse(
  res: http.ServerResponse,
  statusCode: number,
  payload: unknown,
): void {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  res.end(body);
}

function errorStatus(message: string): number {
  if (
    message.startsWith("invalid_runtime_lookup")
    || message.startsWith("invalid_fixture_lookup")
    || message.startsWith("fixture_not_found")
    || message.startsWith("invalid_runtime_replay_payload")
    || message.startsWith("invalid_runtime_verify_payload")
    || message.startsWith("invalid_workflow_id")
    || message.startsWith("invalid_asset_ref")
  ) {
    return 422;
  }
  if (message.startsWith("invalid_runbook_slug")) {
    return 404;
  }
  if (message.startsWith("runtime_fetch_failed:")) {
    const parts = message.split(":");
    const code = Number.parseInt(parts[1] ?? "", 10);
    return Number.isNaN(code) ? 502 : code;
  }
  return 500;
}

export const server = http.createServer(async (req, res) => {
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

    const query = parseTransferQuery(url);
    if (url.pathname === "/api/v1/verification/transfers/summary") {
      const scenario = await buildTransferScenario(query);
      jsonResponse(res, 200, scenario.summary);
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers/proof") {
      const scenario = await buildTransferScenario(query);
      jsonResponse(res, 200, scenario.transfer_proof);
      return;
    }

    if (url.pathname === "/api/v1/verification/assets/proof") {
      const scenario = await buildAssetScenario(query);
      jsonResponse(res, 200, scenario.asset_proof);
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers/status") {
      const scenario = await buildTransferScenario(query);
      jsonResponse(res, 200, scenario.status);
      return;
    }

    if (url.pathname === "/api/v1/verification/assets/forensics") {
      const scenario = await buildAssetScenario(query);
      jsonResponse(res, 200, scenario.asset_forensic_projection);
      return;
    }

    const assetsPrefix = "/api/v1/verification/assets/";
    const forensicsSuffix = "/forensics";
    if (url.pathname.startsWith(assetsPrefix) && url.pathname.endsWith(forensicsSuffix)) {
      const middle = url.pathname.slice(assetsPrefix.length, url.pathname.length - forensicsSuffix.length);
      if (middle.length > 0 && middle !== "forensics" && !middle.includes("/")) {
        const assetRef = decodeURIComponent(middle);
        const scenario = await resolveScenarioByAssetRef(assetRef, query);
        jsonResponse(res, 200, scenario.asset_forensic_projection);
        return;
      }
    }

    if (url.pathname === "/api/v1/verification/operator/copilot-brief") {
      const scenario = await buildScenarioForOperatorCopilot(query);
      const { brief, meta } = await resolveOperatorCopilotBrief(scenario);
      jsonResponse(res, 200, {
        contract_version: "seedcore.verification_operator_copilot_response.v0",
        brief,
        meta,
      });
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers/review") {
      const scenario = await buildTransferScenario(query);
      jsonResponse(res, 200, scenario);
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers/catalog") {
      const items = await listTransferCatalog(query);
      jsonResponse(res, 200, { root: query.root ?? null, source: query.source, items });
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers/queue") {
      const rows = await listTransferQueue(query);
      jsonResponse(res, 200, { root: query.root ?? null, source: query.source, items: rows });
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers") {
      const items = await listTransferCatalog(query);
      jsonResponse(res, 200, { root: query.root ?? null, source: query.source, items });
      return;
    }

    if (url.pathname === "/api/v1/verification/transfers/audit-trail") {
      const scenario = await buildTransferScenario(query);
      jsonResponse(res, 200, scenario.transfer_audit_trail);
      return;
    }

    if (url.pathname === "/api/v1/verification/runbook" || url.pathname === "/api/v1/verification/runbook/") {
      jsonResponse(res, 200, { contract_version: "seedcore.verification_runbook_index.v1", runbooks: listRunbookSummaries() });
      return;
    }

    if (url.pathname === "/api/v1/verification/runbook/lookup") {
      const blockersRaw = url.searchParams.get("blockers");
      jsonResponse(res, 200, {
        contract_version: "seedcore.verification_runbook_lookup.v1",
        runbook_links: lookupRunbooksForQuery({
          reason_code: url.searchParams.get("reason_code") ?? undefined,
          disposition: url.searchParams.get("disposition") ?? undefined,
          business_state: url.searchParams.get("business_state") ?? undefined,
          blockers: blockersRaw
            ? blockersRaw
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            : undefined,
        }),
      });
      return;
    }

    if (url.pathname.startsWith("/api/v1/verification/runbook/")) {
      const slug = decodeURIComponent(
        url.pathname.replace("/api/v1/verification/runbook/", "").replace(/\/+$/, ""),
      );
      if (!slug) {
        jsonResponse(res, 404, { error: "not_found" });
        return;
      }
      const entry = getRunbook(slug);
      if (!entry) {
        jsonResponse(res, 404, { error: "invalid_runbook_slug", detail: slug });
        return;
      }
      jsonResponse(res, 200, { contract_version: "seedcore.verification_runbook_entry.v1", ...entry });
      return;
    }

    if (url.pathname.startsWith("/api/v1/verification/workflows/") && url.pathname.endsWith("/replay")) {
      const workflowId = decodeURIComponent(
        url.pathname
          .replace("/api/v1/verification/workflows/", "")
          .replace("/replay", "")
          .replace(/\/+$/, ""),
      );
      const replay = await buildVerificationReplayForWorkflow(workflowId, query);
      jsonResponse(res, 200, replay);
      return;
    }

    if (url.pathname.startsWith("/api/v1/verification/workflows/") && url.pathname.endsWith("/verification-detail")) {
      const workflowId = decodeURIComponent(
        url.pathname
          .replace("/api/v1/verification/workflows/", "")
          .replace("/verification-detail", "")
          .replace(/\/+$/, ""),
      );
      const detail = await buildVerificationDetailForWorkflow(workflowId, query);
      jsonResponse(res, 200, detail);
      return;
    }

    if (url.pathname.startsWith("/api/v1/verification/workflows/") && url.pathname.endsWith("/projection")) {
      const workflowId = decodeURIComponent(
        url.pathname
          .replace("/api/v1/verification/workflows/", "")
          .replace("/projection", "")
          .replace(/\/+$/, ""),
      );
      const scenario = await buildTransferScenarioByWorkflowId(workflowId, query);
      jsonResponse(res, 200, scenario.verification_projection);
      return;
    }

    if (url.pathname.startsWith("/api/v1/verification/transfers/")) {
      const workflowId = decodeURIComponent(url.pathname.replace("/api/v1/verification/transfers/", ""));
      const scenario = await buildTransferScenarioByWorkflowId(workflowId, query);
      jsonResponse(res, 200, scenario.transfer_audit_trail);
      return;
    }

    jsonResponse(res, 404, { error: "not_found" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown_error";
    jsonResponse(res, errorStatus(message), { error: "verification_failed", detail: message });
  }
});

const port = Number.parseInt(process.env.PORT ?? "7071", 10);
server.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`verification-api listening on http://127.0.0.1:${port}`);
});
