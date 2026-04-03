import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

import {
  buildDeterministicCopilotBrief,
  deriveReplayVerdict,
  validateOperatorCopilotBriefForLlm,
  type OperatorCopilotBriefV1,
} from "@seedcore/contracts";

import {
  buildTransferScenario,
  buildTransferScenarioByWorkflowId,
  buildVerificationDetailFromScenario,
  type TransferScenario,
  type TransferSourceQuery,
} from "./transferSources.js";

function promptsDir(): string {
  return path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "prompts");
}

function loadPrompt(fileName: string): string {
  return readFileSync(path.join(promptsDir(), fileName), "utf8");
}

export async function buildScenarioForOperatorCopilot(query: TransferSourceQuery): Promise<TransferScenario> {
  const wf = query.workflow_id?.trim();
  if (wf) {
    return buildTransferScenarioByWorkflowId(wf, query);
  }
  return buildTransferScenario(query);
}

export function buildCopilotContextJson(scenario: TransferScenario): Record<string, unknown> {
  const t = scenario.transfer_audit_trail;
  const f = scenario.asset_forensic_projection;
  const p = scenario.verification_projection;
  return {
    workflow_id: scenario.workflow_id,
    verification_projection: p,
    transfer_audit_trail: {
      request: t.request,
      decision: t.decision,
      approvals: t.approvals,
      physical_evidence: t.physical_evidence,
      authority_scope: t.authority_scope,
    },
    asset_forensic_projection: {
      business_state: f.business_state,
      disposition: f.disposition,
      trust_gaps: f.trust_gaps,
      missing_prerequisites: f.missing_prerequisites,
      decision_id: f.decision_id,
      policy_snapshot_ref: f.policy_snapshot_ref,
    },
    note: "Cite only paths that exist under this object. Do not invent fields.",
  };
}

function stripJsonFence(raw: string): string {
  const s = raw.trim();
  if (s.startsWith("```")) {
    return s.replace(/^```[a-z0-9]*\n?/i, "").replace(/\n?```$/i, "").trim();
  }
  return s;
}

async function callOpenAiCopilotJson(params: {
  system: string;
  user: string;
  context: Record<string, unknown>;
}): Promise<string> {
  const key = process.env.OPENAI_API_KEY;
  if (!key) {
    throw new Error("OPENAI_API_KEY missing");
  }
  const model = process.env.SEEDCORE_OPERATOR_COPILOT_MODEL ?? "gpt-4o-mini";
  const base = (process.env.SEEDCORE_OPENAI_BASE_URL ?? "https://api.openai.com").replace(/\/+$/, "");
  const res = await fetch(`${base}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
    },
    body: JSON.stringify({
      model,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: params.system },
        {
          role: "user",
          content: `${params.user}\n\nCONTEXT_JSON:\n${JSON.stringify(params.context)}`,
        },
      ],
      temperature: 0.2,
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`openai_http_${res.status}:${t.slice(0, 240)}`);
  }
  const data = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
  const text = data.choices?.[0]?.message?.content?.trim() ?? "";
  if (!text) {
    throw new Error("openai_empty_content");
  }
  return text;
}

export type OperatorCopilotResolutionMeta = {
  used_llm: boolean;
  validation_errors?: string[];
  llm_error?: string;
};

export async function resolveOperatorCopilotBrief(scenario: TransferScenario): Promise<{
  brief: OperatorCopilotBriefV1;
  meta: OperatorCopilotResolutionMeta;
}> {
  const detail = buildVerificationDetailFromScenario(scenario);
  const chain = detail.receipt_chain;
  const steps = Array.isArray(chain.steps) ? chain.steps : [];
  const stepsOk = steps.length > 0 && steps.every((s) => s.ok);
  const failActive = Boolean(detail.failure_panel?.active);
  const projection = scenario.verification_projection;
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

  const deterministic = buildDeterministicCopilotBrief({
    workflow_id: scenario.workflow_id,
    projection,
    audit: scenario.transfer_audit_trail,
    forensics: scenario.asset_forensic_projection,
    replay_verdict: replayVerdict,
  });

  const llmOn = process.env.SEEDCORE_OPERATOR_COPILOT_LLM === "1" && Boolean(process.env.OPENAI_API_KEY?.trim());
  if (!llmOn) {
    return { brief: deterministic, meta: { used_llm: false } };
  }

  try {
    const system = loadPrompt("operator_copilot_system.md");
    const user = loadPrompt("operator_copilot_user.md");
    const context = buildCopilotContextJson(scenario);
    const rawText = await callOpenAiCopilotJson({ system, user, context });
    const parsed: unknown = JSON.parse(stripJsonFence(rawText));
    const validated = validateOperatorCopilotBriefForLlm(parsed);
    if (!validated.ok) {
      return {
        brief: {
          ...deterministic,
          audit_note: `LLM output failed validation; deterministic fallback. ${validated.errors.join("; ")}`,
          uncertainty_notes: [
            ...deterministic.uncertainty_notes,
            `LLM validation: ${validated.errors.join("; ")}`,
          ],
        },
        meta: { used_llm: true, validation_errors: validated.errors },
      };
    }
    validated.brief.case_id = scenario.workflow_id;
    return { brief: validated.brief, meta: { used_llm: true } };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return {
      brief: {
        ...deterministic,
        audit_note: `LLM error; deterministic fallback. ${msg}`,
        uncertainty_notes: [...deterministic.uncertainty_notes, `LLM error: ${msg}`],
      },
      meta: { used_llm: true, llm_error: msg },
    };
  }
}
