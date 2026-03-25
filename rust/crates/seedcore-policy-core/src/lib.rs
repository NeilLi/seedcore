//! Deterministic policy decision kernel for SeedCore.
//!
//! This crate will own frozen decision input evaluation, disposition
//! computation, explanation payload construction, and governed decision
//! artifacts for Restricted Custody Transfer and follow-on workflows.

use seedcore_kernel_types::{
    Disposition, ExplanationPayload, Obligation, Timestamp, TransferApprovalEnvelope,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Frozen asset-side facts required by deterministic policy evaluation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrozenAssetState {
    pub asset_ref: String,
    pub current_custodian_ref: Option<String>,
    pub current_zone_ref: Option<String>,
    pub custody_point_ref: Option<String>,
    pub transferable: bool,
    pub restricted: bool,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    #[serde(default)]
    pub approved_registration_refs: Vec<String>,
}

/// Frozen summary of authority graph outputs needed by the policy kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthorityGraphSummary {
    #[serde(default)]
    pub matched_policy_refs: Vec<String>,
    #[serde(default)]
    pub authority_paths: Vec<String>,
    #[serde(default)]
    pub missing_prerequisites: Vec<String>,
    #[serde(default)]
    pub trust_gaps: Vec<String>,
}

/// Frozen telemetry fields required by the policy kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TelemetrySummary {
    pub observed_at: Option<Timestamp>,
    pub stale: bool,
    pub attested: bool,
    pub seal_present: Option<bool>,
}

/// Frozen break-glass context for governed evaluation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BreakGlassContext {
    pub present: bool,
    pub validated: bool,
    pub principal_ref: Option<String>,
    pub reason: Option<String>,
}

/// Frozen decision input passed into the deterministic policy kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrozenDecisionInput {
    pub action_intent_ref: String,
    pub approval_envelope: Option<TransferApprovalEnvelope>,
    pub policy_snapshot_ref: String,
    pub asset_state: FrozenAssetState,
    pub authority_graph_summary: AuthorityGraphSummary,
    pub telemetry_summary: TelemetrySummary,
    pub break_glass: Option<BreakGlassContext>,
}

/// Minimal governed decision artifact emitted by the policy kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GovernedDecisionArtifact {
    pub decision_id: String,
    pub action_intent_ref: String,
    pub policy_snapshot_ref: String,
    pub disposition: Disposition,
    pub asset_ref: String,
}

/// Policy receipt payload prepared by the policy kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyReceiptPayload {
    pub policy_receipt_id: String,
    pub policy_snapshot_ref: String,
    pub action_intent_ref: String,
    pub disposition: Disposition,
}

/// Execution token spec prepared on allow paths.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionTokenSpec {
    pub intent_ref: String,
    pub asset_ref: String,
    pub policy_snapshot_ref: String,
}

/// Deterministic result of policy evaluation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyEvaluation {
    pub disposition: Disposition,
    pub explanation: ExplanationPayload,
    pub governed_decision_artifact: GovernedDecisionArtifact,
    pub policy_receipt_payload: PolicyReceiptPayload,
    pub execution_token_spec: Option<ExecutionTokenSpec>,
}

/// Policy-core validation and evaluation errors.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum PolicyError {
    #[error("missing_field:{0}")]
    MissingField(&'static str),
}

/// Evaluates a frozen input into one deterministic disposition and its
/// downstream artifacts.
pub fn evaluate(input: &FrozenDecisionInput) -> Result<PolicyEvaluation, PolicyError> {
    require_non_empty(&input.action_intent_ref, "action_intent_ref")?;
    require_non_empty(&input.policy_snapshot_ref, "policy_snapshot_ref")?;
    require_non_empty(&input.asset_state.asset_ref, "asset_state.asset_ref")?;

    let disposition = if input
        .break_glass
        .as_ref()
        .map(|ctx| ctx.present)
        .unwrap_or(false)
    {
        Disposition::Escalate
    } else if !input.authority_graph_summary.missing_prerequisites.is_empty() {
        Disposition::Deny
    } else if input
        .approval_envelope
        .as_ref()
        .map(|envelope| envelope.status)
        != Some(seedcore_kernel_types::ApprovalStatus::Approved)
    {
        Disposition::Deny
    } else if !input.asset_state.transferable {
        Disposition::Deny
    } else if input.telemetry_summary.stale
        || !input.telemetry_summary.attested
        || matches!(input.telemetry_summary.seal_present, Some(false))
    {
        Disposition::Quarantine
    } else {
        Disposition::Allow
    };

    let explanation = build_explanation(input, disposition);
    let governed_decision_artifact = GovernedDecisionArtifact {
        decision_id: format!("decision:{}", input.action_intent_ref),
        action_intent_ref: input.action_intent_ref.clone(),
        policy_snapshot_ref: input.policy_snapshot_ref.clone(),
        disposition,
        asset_ref: input.asset_state.asset_ref.clone(),
    };
    let policy_receipt_payload = PolicyReceiptPayload {
        policy_receipt_id: format!("policy-receipt:{}", input.action_intent_ref),
        policy_snapshot_ref: input.policy_snapshot_ref.clone(),
        action_intent_ref: input.action_intent_ref.clone(),
        disposition,
    };
    let execution_token_spec = (disposition == Disposition::Allow).then(|| ExecutionTokenSpec {
        intent_ref: input.action_intent_ref.clone(),
        asset_ref: input.asset_state.asset_ref.clone(),
        policy_snapshot_ref: input.policy_snapshot_ref.clone(),
    });

    Ok(PolicyEvaluation {
        disposition,
        explanation,
        governed_decision_artifact,
        policy_receipt_payload,
        execution_token_spec,
    })
}

fn build_explanation(input: &FrozenDecisionInput, disposition: Disposition) -> ExplanationPayload {
    let mut explanation = ExplanationPayload::empty(disposition);
    explanation.matched_policy_refs = input.authority_graph_summary.matched_policy_refs.clone();
    explanation.authority_path_summary = input.authority_graph_summary.authority_paths.clone();
    explanation.missing_prerequisites = input.authority_graph_summary.missing_prerequisites.clone();
    explanation.trust_gaps = input.authority_graph_summary.trust_gaps.clone();
    explanation.minted_artifacts = vec![
        format!("governed_decision:{}", input.action_intent_ref),
        format!("policy_receipt:{}", input.action_intent_ref),
    ];

    match disposition {
        Disposition::Allow => {
            explanation
                .minted_artifacts
                .push(format!("execution_token:{}", input.action_intent_ref));
        }
        Disposition::Deny => {
            if explanation.missing_prerequisites.is_empty() && !input.asset_state.transferable {
                explanation
                    .missing_prerequisites
                    .push("asset_not_transferable".to_string());
            }
        }
        Disposition::Quarantine => {
            if input.telemetry_summary.stale {
                explanation.trust_gaps.push("stale_telemetry".to_string());
            }
            if !input.telemetry_summary.attested {
                explanation.trust_gaps.push("missing_attestation".to_string());
            }
            if matches!(input.telemetry_summary.seal_present, Some(false)) {
                explanation.trust_gaps.push("seal_missing_or_broken".to_string());
            }
        }
        Disposition::Escalate => {
            explanation.obligations.push(Obligation {
                obligation_type: "human_review".to_string(),
                reference: input
                    .break_glass
                    .as_ref()
                    .and_then(|ctx| ctx.reason.clone())
                    .or_else(|| Some("break_glass_review".to_string())),
                details: std::collections::BTreeMap::new(),
            });
        }
    }

    explanation
}

fn require_non_empty(value: &str, field_name: &'static str) -> Result<(), PolicyError> {
    if value.trim().is_empty() {
        return Err(PolicyError::MissingField(field_name));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use seedcore_kernel_types::{
        ApprovalStatus, ArtifactHash, RoleApproval, TransferContext,
    };
    use std::str::FromStr;

    fn approved_envelope() -> TransferApprovalEnvelope {
        TransferApprovalEnvelope {
            approval_envelope_id: "approval-transfer-001".to_string(),
            workflow_type: "custody_transfer".to_string(),
            status: ApprovalStatus::Approved,
            asset_ref: "asset:lot-8841".to_string(),
            lot_id: Some("lot-8841".to_string()),
            from_custodian_ref: "principal:facility_mgr_001".to_string(),
            to_custodian_ref: "principal:outbound_mgr_002".to_string(),
            transfer_context: TransferContext {
                from_zone: Some("vault_a".to_string()),
                to_zone: Some("handoff_bay_3".to_string()),
                facility_ref: Some("facility:north_warehouse".to_string()),
                custody_point_ref: Some("custody_point:handoff_bay_3".to_string()),
            },
            required_approvals: vec![RoleApproval {
                role: "FACILITY_MANAGER".to_string(),
                principal_ref: "principal:facility_mgr_001".to_string(),
                status: ApprovalStatus::Approved,
                approved_at: Some(Timestamp::from_str("2026-04-02T08:00:05Z").unwrap()),
                approval_ref: "approval:facility_mgr_001".to_string(),
            }],
            approval_binding_hash: Some(ArtifactHash::sha256_hex("placeholder")),
            policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
            expires_at: Timestamp::from_str("2026-04-02T08:05:00Z").unwrap(),
            created_at: Timestamp::from_str("2026-04-02T08:00:00Z").unwrap(),
            version: 1,
        }
    }

    fn base_input() -> FrozenDecisionInput {
        FrozenDecisionInput {
            action_intent_ref: "intent-transfer-001".to_string(),
            approval_envelope: Some(approved_envelope()),
            policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
            asset_state: FrozenAssetState {
                asset_ref: "asset:lot-8841".to_string(),
                current_custodian_ref: Some("principal:facility_mgr_001".to_string()),
                current_zone_ref: Some("vault_a".to_string()),
                custody_point_ref: Some("custody_point:vault_a".to_string()),
                transferable: true,
                restricted: true,
                evidence_refs: vec!["evidence:telemetry-001".to_string()],
                approved_registration_refs: vec!["registration:approved-001".to_string()],
            },
            authority_graph_summary: AuthorityGraphSummary {
                matched_policy_refs: vec!["policy:transfer-v1".to_string()],
                authority_paths: vec!["facility_manager -> transfer_lot".to_string()],
                missing_prerequisites: Vec::new(),
                trust_gaps: Vec::new(),
            },
            telemetry_summary: TelemetrySummary {
                observed_at: Some(Timestamp::from_str("2026-04-02T08:00:10Z").unwrap()),
                stale: false,
                attested: true,
                seal_present: Some(true),
            },
            break_glass: None,
        }
    }

    #[test]
    fn evaluate_returns_allow_for_clean_happy_path() {
        let result = evaluate(&base_input()).expect("evaluation should succeed");
        assert_eq!(result.disposition, Disposition::Allow);
        assert!(result.execution_token_spec.is_some());
    }

    #[test]
    fn evaluate_returns_deny_when_prerequisites_are_missing() {
        let mut input = base_input();
        input.authority_graph_summary.missing_prerequisites = vec!["missing_dual_approval".to_string()];
        let result = evaluate(&input).expect("evaluation should succeed");
        assert_eq!(result.disposition, Disposition::Deny);
        assert!(result.execution_token_spec.is_none());
    }

    #[test]
    fn evaluate_returns_quarantine_when_telemetry_is_stale() {
        let mut input = base_input();
        input.telemetry_summary.stale = true;
        let result = evaluate(&input).expect("evaluation should succeed");
        assert_eq!(result.disposition, Disposition::Quarantine);
        assert!(result
            .explanation
            .trust_gaps
            .contains(&"stale_telemetry".to_string()));
    }

    #[test]
    fn evaluate_returns_escalate_when_break_glass_is_present() {
        let mut input = base_input();
        input.break_glass = Some(BreakGlassContext {
            present: true,
            validated: true,
            principal_ref: Some("principal:ops_override_001".to_string()),
            reason: Some("urgent_release".to_string()),
        });
        let result = evaluate(&input).expect("evaluation should succeed");
        assert_eq!(result.disposition, Disposition::Escalate);
        assert_eq!(result.explanation.obligations.len(), 1);
    }
}
