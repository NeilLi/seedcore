import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveTransferReadiness,
  parseAssetForensicProjection,
  parseTransferAuditTrail,
  parseTransferStatusView,
  parseVerificationSurfaceProjection,
} from "../packages/contracts/src/index.ts";
import {
  buildRuntimeScenarioFromReplay,
  buildAssetScenario,
  buildTransferScenario,
  buildVerificationDetailFromScenario,
  buildVerificationReplayFromScenario,
  listTransferCatalog,
  listTransferQueue,
} from "../services/verification-api/src/transferSources.ts";
import { getRunbook, listRunbookSummaries } from "../services/verification-api/src/runbooks.ts";
import {
  renderCatalogPage,
  renderForensicsPage,
  renderReplayPage,
  renderTransferPage,
} from "../apps/operator-console/src/ui.ts";

test("fixture scenarios map into Phase D business states and readiness", async () => {
  const cases = [
    {
      dir: "rust/fixtures/transfers/allow_case",
      businessState: "verified",
      readiness: "ready",
    },
    {
      dir: "rust/fixtures/transfers/deny_missing_approval",
      businessState: "rejected",
      readiness: "blocked",
    },
    {
      dir: "rust/fixtures/transfers/quarantine_stale_telemetry",
      businessState: "quarantined",
      readiness: "quarantined",
    },
    {
      dir: "rust/fixtures/transfers/escalate_break_glass",
      businessState: "review_required",
      readiness: "review_required",
    },
  ] as const;

  for (const item of cases) {
    const scenario = await buildTransferScenario({ source: "fixture", dir: item.dir });
    assert.equal(scenario.summary.business_state, item.businessState);
    assert.equal(scenario.status.transfer_readiness, item.readiness);
    assert.equal(scenario.asset_forensics.asset_ref.startsWith("asset:"), true);
    assert.ok(Array.isArray(scenario.asset_forensics.timeline));
    assert.ok(scenario.status.links.review.includes("/api/v1/verification/transfers/audit-trail"));
    assert.ok(parseTransferStatusView(scenario.status));
    assert.ok(parseVerificationSurfaceProjection(scenario.verification_projection));
    assert.ok(parseTransferAuditTrail(scenario.transfer_audit_trail));
    assert.ok(parseAssetForensicProjection(scenario.asset_forensic_projection));
  }
});

test("Q2 verification detail and replay contracts include runbook links", async () => {
  const scenario = await buildTransferScenario({
    source: "fixture",
    dir: "rust/fixtures/transfers/deny_missing_approval",
  });
  const detail = buildVerificationDetailFromScenario(scenario);
  assert.equal(detail.contract_version, "seedcore.verification_detail.v1");
  assert.ok(Array.isArray(detail.failure_panel.runbook_links));
  assert.ok(detail.failure_panel.runbook_links.length >= 1);

  const replay = buildVerificationReplayFromScenario(scenario, {
    source: "fixture",
    dir: "rust/fixtures/transfers/deny_missing_approval",
  });
  assert.equal(replay.contract_version, "seedcore.verification_replay.v1");
  assert.ok(replay.links.verification_detail.includes("/verification-detail"));
  assert.ok(replay.links.transfer_audit_trail.includes("/audit-trail"));
  assert.ok(replay.failure_panel.runbook_links.length >= 1);
});

test("transfer queue rows expose dedicated verification replay URL", async () => {
  const rows = await listTransferQueue({
    source: "fixture",
    root: "rust/fixtures/transfers",
    status: "verified",
    approval_state: "APPROVED",
  });
  const allow = rows.find((r) => r.queue_key === "allow_case");
  assert.ok(allow);
  assert.ok(allow!.links.verification_replay.includes("/replay"));
  assert.ok(allow!.links.verification_replay.includes("status=verified"));
  assert.ok(allow!.links.verification_replay.includes("approval_state=APPROVED"));
});

test("runbook index and entries are stable", () => {
  const slugs = listRunbookSummaries();
  assert.ok(slugs.some((s) => s.slug === "operator_transfer_overview"));
  const rb = getRunbook("trust_gap_quarantine");
  assert.ok(rb);
  assert.ok(rb!.steps.length >= 1);
});

test("catalog exposes status preview and forensic links", async () => {
  const items = await listTransferCatalog({ source: "fixture", root: "rust/fixtures/transfers" });
  assert.ok(items.length >= 4);
  const allowItem = items.find((item) => item.id === "allow_case");
  assert.ok(allowItem);
  assert.equal(allowItem.status_preview.transfer_readiness, "ready");
  assert.equal(typeof allowItem.status_preview.current_step, "string");
  assert.ok(allowItem.links.asset_forensics.includes("/api/v1/verification/assets/forensics"));
});

test("runtime replay view maps into the same Phase D scenario shape", () => {
  const runtimeScenario = buildRuntimeScenarioFromReplay(
    {
      subject_id: "asset:lot-8841",
      intent_id: "intent-transfer-001",
      authz_graph: {
        authority_path_summary: ["facility_manager -> transfer_lot"],
        minted_artifacts: [{ kind: "governed_decision", ref: "decision:intent-transfer-001" }],
        obligations: [],
      },
      policy_receipt: {
        policy_receipt_id: "policy-receipt:intent-transfer-001",
        policy_decision_id: "decision:intent-transfer-001",
        asset_ref: "asset:lot-8841",
        evaluated_rules: ["policy:transfer-v1"],
      },
      evidence_bundle: {
        execution_token_id: "token:intent-transfer-001",
        telemetry_refs: [{ kind: "telemetry_snapshot" }],
      },
      verification_status: {
        verified: true,
        issues: [],
        artifact_results: {
          policy_receipt: { verified: true },
          evidence_bundle: { verified: true },
        },
      },
      signer_chain: [
        {
          artifact_type: "policy_receipt",
          signer_metadata: {
            signer_type: "service",
            signer_id: "seedcore-verify",
            key_ref: "test-key",
            attestation_level: "baseline",
          },
        },
      ],
      replay_timeline: [
        {
          event_type: "policy_evaluated",
          timestamp: "2026-04-02T08:00:15Z",
          summary: "Disposition allow verified",
          artifact_ref: "policy-receipt:intent-transfer-001",
        },
      ],
      audit_record: {
        intent_id: "intent-transfer-001",
        token_id: "token:intent-transfer-001",
        policy_snapshot: "snapshot:pkg-prod-2026-04-02",
        recorded_at: "2026-04-02T08:00:15Z",
        actor_agent_id: "agent:custody_runtime_01",
        action_intent: {
          resource: {
            asset_id: "asset:lot-8841",
            category_envelope: {
              transfer_context: {
                from_zone: "vault_a",
                to_zone: "handoff_bay_3",
                facility_ref: "facility:north_warehouse",
                custody_point_ref: "custody_point:handoff_bay_3",
                expected_current_custodian: "principal:facility_mgr_001",
                next_custodian: "principal:outbound_mgr_002",
              },
            },
          },
          action: {
            parameters: {
              approval_context: {
                approval_envelope_id: "approval-transfer-001",
                approved_by: ["principal:facility_mgr_001", "principal:quality_insp_017"],
              },
            },
          },
        },
        policy_decision: {
          disposition: "allow",
          required_approvals: ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
          governed_receipt: {
            principal_ref: "principal:facility_mgr_001",
          },
        },
      },
      asset_custody_state: {
        current_custodian_ref: "principal:facility_mgr_001",
        custody_point_ref: "custody_point:vault_a",
      },
      transition_receipts: [
        {
          from_zone: "vault_a",
          to_zone: "handoff_bay_3",
        },
      ],
    },
    { source: "runtime", audit_id: "audit-allow-001" },
  );

  assert.equal(runtimeScenario.summary.business_state, "verified");
  assert.equal(runtimeScenario.status.transfer_readiness, "ready");
  assert.ok(runtimeScenario.asset_forensic_projection.telemetry_refs.includes("telemetry_snapshot"));
  assert.equal(runtimeScenario.asset_forensic_projection.custody_transition.to_zone, "handoff_bay_3");
  assert.equal(runtimeScenario.asset_forensic_projection.signer_provenance[0]?.signer_id, "seedcore-verify");
  assert.equal(runtimeScenario.asset_forensic_projection.signer_provenance[0]?.signer_type, "service");
});

test("fixture workflow requires explicit fixture dir for operator endpoints", async () => {
  await assert.rejects(
    () => buildTransferScenario({ source: "fixture" }),
    /invalid_fixture_lookup:dir/,
  );
  await assert.rejects(
    () => buildAssetScenario({ source: "fixture" }),
    /invalid_fixture_lookup:dir/,
  );
});

test("runtime transfer workflow rejects subject-only lookup keys", async () => {
  await assert.rejects(
    () => buildTransferScenario({ source: "runtime", subject_id: "asset:lot-8841" }),
    /invalid_runtime_lookup:audit_id\|intent_id/,
  );
});

test("missing prerequisites always force blocked readiness", () => {
  assert.equal(
    deriveTransferReadiness("quarantine", "APPROVED", false, ["missing_dual_approval"]),
    "blocked",
  );
  assert.equal(
    deriveTransferReadiness("allow", "APPROVED", true, []),
    "ready",
  );
});

test("operator console renders status-first transfer and forensic pages", async () => {
  const scenario = await buildTransferScenario({ source: "fixture", dir: "rust/fixtures/transfers/allow_case" });
  const query = "source=fixture&dir=rust/fixtures/transfers/allow_case";
  const transferHtml = renderTransferPage(scenario, query);
  const forensicHtml = renderForensicsPage(scenario.asset_forensic_projection, query);

  assert.match(transferHtml, /Transfer Workflow Review/);
  assert.match(transferHtml, /Request \+ Authority/);
  assert.match(transferHtml, /Decision \+ Artifacts/);
  assert.match(transferHtml, /Physical Evidence \+ Closure/);
  assert.match(transferHtml, /Governed Timeline/);
  assert.match(forensicHtml, /Asset Forensic View/);
  assert.match(forensicHtml, /Telemetry References/);
  assert.match(forensicHtml, /Signature Provenance/);
});

test("catalog replay links use workflow_id rather than catalog id", () => {
  const html = renderCatalogPage(
    {
      items: [
        {
          id: "intent-transfer-001",
          workflow_id: "audit-allow-001",
          query: "source=runtime&intent_id=intent-transfer-001",
          summary: {
            business_state: "verified",
            disposition: "allow",
            approval_status: "APPROVED",
            verified: true,
            execution_token_expected: true,
            execution_token_present: true,
          },
          status_preview: {
            transfer_readiness: "ready",
            current_step: "verification_complete",
            top_blocker: null,
          },
        },
      ],
    },
    "source=runtime&intent_id=intent-transfer-001",
  );
  assert.match(html, /workflow_id=audit-allow-001/);
  assert.doesNotMatch(html, /workflow_id=intent-transfer-001/);
});

test("replay page preserves runtime lookup links for transfer and forensics", async () => {
  const scenario = await buildTransferScenario({ source: "fixture", dir: "rust/fixtures/transfers/allow_case" });
  const html = renderReplayPage(
    {
      verification_projection: scenario.verification_projection,
      receipt_chain: {
        steps: [],
        terminal_disposition: "allow",
        replay_verifiable: false,
      },
      failure_panel: {
        active: false,
        path: "allow",
        business_state: "verified",
        headline: "ok",
        blockers: [],
        trust_gaps: [],
        missing_prerequisites: [],
        reason_code: "none",
        reason: "none",
        runbook_links: [],
      },
    },
    "source=runtime&workflow_id=audit-123",
    "audit-123",
  );
  assert.match(html, /\/transfer\?source=runtime&audit_id=audit-123/);
  assert.match(html, /\/forensics\?source=runtime&audit_id=audit-123/);
  assert.doesNotMatch(html, /source=fixture/);
});
