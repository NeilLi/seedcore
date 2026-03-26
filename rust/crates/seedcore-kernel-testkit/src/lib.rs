//! Shared test harness support for the SeedCore Rust kernel workspace.
//!
//! This crate loads deterministic fixtures and runs canonical transfer-scenario
//! verification across policy and token kernels.

use seedcore_approval_core::{approval_binding_hash, validate_envelope};
use seedcore_kernel_types::{
    ActionIntent, ApprovalTransitionHistory, ArtifactHash, IntentAction, IntentEnvironment,
    IntentPrincipal, IntentResource, SignatureEnvelope, Timestamp, TransferApprovalEnvelope,
};
use seedcore_policy_core::{evaluate, FrozenDecisionInput, PolicyEvaluation};
use seedcore_proof_core::{
    KeyMaterial, KeyResolver, ReplayArtifact, ReplayBundle, Signer, VerificationError,
};
use seedcore_token_core::{
    enforce_constraints, mint_token, verify_token, ExecutionRequestContext, ExecutionToken,
    ExecutionTokenClaims, TokenConstraints, TokenVerificationReport,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use thiserror::Error;

/// Minimal action-intent fields required by the fixture harness.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActionIntentFixture {
    pub action_intent_ref: String,
    pub action_type: String,
    pub principal_agent_id: Option<String>,
    pub source_registration_id: Option<String>,
    pub registration_decision_id: Option<String>,
    pub endpoint_id: Option<String>,
}

/// Explicit expected execution-token assertion policy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExpectedExecutionToken {
    NotProvided,
    ExpectedNull,
    ExpectedSome(ExecutionToken),
}

/// Canonical scenario verification report.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransferVerificationReport {
    pub verified: bool,
    pub checks: Vec<String>,
    pub error_code: Option<String>,
    pub actual_policy_evaluation: PolicyEvaluation,
    pub actual_execution_token: Option<ExecutionToken>,
    pub token_verification: Option<TokenVerificationReport>,
}

/// Loaded transfer scenario fixture bundle.
#[derive(Debug, Clone, PartialEq)]
pub struct TransferScenarioFixture {
    pub dir: PathBuf,
    pub action_intent: ActionIntentFixture,
    pub approval_envelope: TransferApprovalEnvelope,
    pub asset_state: seedcore_policy_core::FrozenAssetState,
    pub telemetry_summary: seedcore_policy_core::TelemetrySummary,
    pub authority_graph_summary: seedcore_policy_core::AuthorityGraphSummary,
    pub break_glass: Option<seedcore_policy_core::BreakGlassContext>,
    pub expected_policy_evaluation: Option<PolicyEvaluation>,
    pub expected_execution_token: ExpectedExecutionToken,
    pub expected_verification_report: Option<TransferVerificationReport>,
}

/// Fixture loading and parsing errors.
#[derive(Debug, Error)]
pub enum FixtureError {
    #[error("read_failed:{path}:{source}")]
    ReadFailed {
        path: String,
        source: std::io::Error,
    },
    #[error("json_parse_failed:{path}:{source}")]
    JsonParseFailed {
        path: String,
        source: serde_json::Error,
    },
}

/// Scenario execution errors.
#[derive(Debug, Error)]
pub enum ScenarioError {
    #[error(transparent)]
    Fixture(#[from] FixtureError),
    #[error("approval_error:{0}")]
    Approval(String),
    #[error("policy_evaluation_failed:{0}")]
    Policy(String),
    #[error("token_mint_failed:{0}")]
    TokenMint(String),
    #[error("timestamp_parse_failed:{0}")]
    Timestamp(String),
}

/// Deterministic debug signer used by fixture harnesses.
pub struct FixtureDebugSigner;

impl Signer for FixtureDebugSigner {
    fn sign_hash(
        &self,
        hash: &ArtifactHash,
    ) -> Result<SignatureEnvelope, seedcore_proof_core::SigningError> {
        Ok(SignatureEnvelope {
            signer_type: "service".to_string(),
            signer_id: "seedcore-verify".to_string(),
            signing_scheme: "debug_hash_v1".to_string(),
            key_ref: Some("test-key".to_string()),
            attestation_level: "baseline".to_string(),
            signature: hash.to_string(),
        })
    }
}

/// Deterministic static key resolver used by fixture harnesses.
pub struct FixtureStaticResolver;

impl KeyResolver for FixtureStaticResolver {
    fn resolve(&self, key_ref: &str) -> Result<KeyMaterial, VerificationError> {
        if key_ref == "test-key" {
            Ok(KeyMaterial {
                key_ref: key_ref.to_string(),
                public_material: "debug".to_string(),
                metadata: BTreeMap::new(),
            })
        } else {
            Err(VerificationError::KeyNotFound)
        }
    }
}

/// Loads one transfer fixture directory into a canonical scenario bundle.
pub fn load_transfer_fixture(
    dir: impl AsRef<Path>,
) -> Result<TransferScenarioFixture, FixtureError> {
    let dir = dir.as_ref().to_path_buf();
    Ok(TransferScenarioFixture {
        action_intent: read_json_file(dir.join("input.action_intent.json"))?,
        approval_envelope: read_json_file(dir.join("input.approval_envelope.json"))?,
        asset_state: read_json_file(dir.join("input.asset_state.json"))?,
        telemetry_summary: read_json_file(dir.join("input.telemetry_summary.json"))?,
        authority_graph_summary: read_json_file(dir.join("input.authority_graph_summary.json"))?,
        break_glass: read_optional_json_file(dir.join("input.break_glass.json"))?,
        expected_policy_evaluation: read_optional_json_file(
            dir.join("expected.policy_evaluation.json"),
        )?,
        expected_execution_token: read_expected_execution_token(
            dir.join("expected.execution_token.json"),
        )?,
        expected_verification_report: read_optional_json_file(
            dir.join("expected.verification_report.json"),
        )?,
        dir,
    })
}

/// Loads one replay bundle fixture file.
pub fn load_replay_bundle(path: impl AsRef<Path>) -> Result<ReplayBundle, FixtureError> {
    read_json_file(path)
}

/// Loads one receipt artifact fixture file.
pub fn load_receipt_artifact(path: impl AsRef<Path>) -> Result<ReplayArtifact, FixtureError> {
    read_json_file(path)
}

/// Loads one approval transition history fixture file.
pub fn load_approval_transition_history(
    path: impl AsRef<Path>,
) -> Result<ApprovalTransitionHistory, FixtureError> {
    read_json_file(path)
}

/// Runs the canonical transfer scenario evaluation for a fixture directory,
/// using deterministic signer/resolver defaults.
pub fn run_transfer_fixture_dir(
    dir: impl AsRef<Path>,
) -> Result<TransferVerificationReport, ScenarioError> {
    let fixture = load_transfer_fixture(dir)?;
    run_transfer_fixture(&fixture, &FixtureDebugSigner, &FixtureStaticResolver)
}

/// Runs the canonical transfer scenario evaluation for a loaded fixture.
pub fn run_transfer_fixture(
    fixture: &TransferScenarioFixture,
    signer: &dyn Signer,
    resolver: &dyn KeyResolver,
) -> Result<TransferVerificationReport, ScenarioError> {
    validate_envelope(&fixture.approval_envelope)
        .map_err(|error| ScenarioError::Approval(error.to_string()))?;
    let computed_approval_hash = approval_binding_hash(&fixture.approval_envelope)
        .map_err(|error| ScenarioError::Approval(error.to_string()))?;

    let input = FrozenDecisionInput {
        action_intent: ActionIntent {
            intent_id: fixture.action_intent.action_intent_ref.clone(),
            timestamp: fixed_ts("2026-04-02T08:00:00Z")?,
            valid_until: fixed_ts("2026-04-02T08:01:00Z")?,
            principal: IntentPrincipal {
                principal_ref: fixture
                    .action_intent
                    .principal_agent_id
                    .clone()
                    .unwrap_or_else(|| "principal:unknown".to_string()),
                organization_ref: None,
                role_refs: Vec::new(),
            },
            action: IntentAction {
                action_type: fixture.action_intent.action_type.clone(),
                target_zone: fixture.approval_envelope.transfer_context.to_zone.clone(),
                endpoint_id: fixture.action_intent.endpoint_id.clone(),
            },
            resource: IntentResource {
                asset_ref: fixture.asset_state.asset_ref.clone(),
                lot_id: fixture.approval_envelope.lot_id.clone(),
            },
            environment: IntentEnvironment {
                source_registration_id: fixture.action_intent.source_registration_id.clone(),
                registration_decision_id: fixture.action_intent.registration_decision_id.clone(),
                attributes: BTreeMap::new(),
            },
        },
        approval_envelope: Some(fixture.approval_envelope.clone()),
        policy_snapshot_ref: fixture.approval_envelope.policy_snapshot_ref.clone(),
        asset_state: fixture.asset_state.clone(),
        authority_graph_summary: fixture.authority_graph_summary.clone(),
        telemetry_summary: fixture.telemetry_summary.clone(),
        break_glass: fixture.break_glass.clone(),
    };

    let actual_policy_evaluation =
        evaluate(&input).map_err(|error| ScenarioError::Policy(error.to_string()))?;

    let mut checks = Vec::new();
    let mut verified = true;
    let mut error_code = None;

    if let Some(expected_hash) = fixture.approval_envelope.approval_binding_hash.as_ref() {
        if expected_hash != &computed_approval_hash {
            verified = false;
            error_code = Some("approval_binding_hash_mismatch".to_string());
        } else {
            checks.push("approval_binding_hash_match".to_string());
        }
    } else {
        checks.push("approval_binding_hash_computed".to_string());
    }

    if let Some(expected) = fixture.expected_policy_evaluation.as_ref() {
        if expected != &actual_policy_evaluation {
            verified = false;
            error_code = Some("policy_evaluation_mismatch".to_string());
        } else {
            checks.push("policy_evaluation_match".to_string());
        }
    }

    let mut actual_execution_token = None;
    let mut token_verification = None;

    if actual_policy_evaluation.execution_token_spec.is_some() {
        let claims = ExecutionTokenClaims {
            token_id: format!("token:{}", fixture.action_intent.action_intent_ref),
            intent_id: fixture.action_intent.action_intent_ref.clone(),
            issued_at: fixed_ts("2026-04-02T08:00:15Z")?,
            valid_until: fixed_ts("2026-04-02T08:01:15Z")?,
            contract_version: "transfer-v1".to_string(),
            constraints: TokenConstraints {
                action_type: fixture.action_intent.action_type.clone(),
                target_zone: fixture.approval_envelope.transfer_context.to_zone.clone(),
                asset_id: Some(input.asset_state.asset_ref.clone()),
                principal_agent_id: fixture.action_intent.principal_agent_id.clone(),
                source_registration_id: fixture.action_intent.source_registration_id.clone(),
                registration_decision_id: fixture.action_intent.registration_decision_id.clone(),
                endpoint_id: fixture.action_intent.endpoint_id.clone(),
            },
        };

        let token = mint_token(claims, signer)
            .map_err(|error| ScenarioError::TokenMint(error.to_string()))?;
        let verification = verify_token(&token, resolver, fixed_ts("2026-04-02T08:00:30Z")?);
        if !verification.verified {
            verified = false;
            error_code.get_or_insert_with(|| {
                verification
                    .error_code
                    .clone()
                    .unwrap_or_else(|| "token_verification_failed".to_string())
            });
        } else {
            checks.push("execution_token_verified".to_string());
        }

        let enforcement = enforce_constraints(
            &token,
            &ExecutionRequestContext {
                action_type: fixture.action_intent.action_type.clone(),
                target_zone: fixture.approval_envelope.transfer_context.to_zone.clone(),
                asset_id: Some(input.asset_state.asset_ref.clone()),
                principal_agent_id: fixture.action_intent.principal_agent_id.clone(),
                source_registration_id: fixture.action_intent.source_registration_id.clone(),
                registration_decision_id: fixture.action_intent.registration_decision_id.clone(),
                endpoint_id: fixture.action_intent.endpoint_id.clone(),
            },
            fixed_ts("2026-04-02T08:00:30Z")?,
        );
        if !enforcement.allowed {
            verified = false;
            error_code.get_or_insert_with(|| {
                enforcement
                    .error_code
                    .clone()
                    .unwrap_or_else(|| "token_enforcement_failed".to_string())
            });
        } else {
            checks.push("execution_token_constraints_satisfied".to_string());
        }

        actual_execution_token = Some(token);
        token_verification = Some(verification);
    }

    match &fixture.expected_execution_token {
        ExpectedExecutionToken::NotProvided => {}
        ExpectedExecutionToken::ExpectedNull => {
            if actual_execution_token.is_some() {
                verified = false;
                error_code.get_or_insert_with(|| "execution_token_expected_null".to_string());
            } else {
                checks.push("execution_token_null_match".to_string());
            }
        }
        ExpectedExecutionToken::ExpectedSome(expected_token) => {
            if let Some(actual_token) = actual_execution_token.as_ref() {
                if actual_token != expected_token {
                    verified = false;
                    error_code.get_or_insert_with(|| "execution_token_mismatch".to_string());
                } else {
                    checks.push("execution_token_match".to_string());
                }
            } else {
                verified = false;
                error_code.get_or_insert_with(|| "execution_token_missing".to_string());
            }
        }
    }

    let report = TransferVerificationReport {
        verified,
        checks,
        error_code,
        actual_policy_evaluation,
        actual_execution_token,
        token_verification,
    };

    if let Some(expected_report) = fixture.expected_verification_report.as_ref() {
        if expected_report != &report {
            return Ok(TransferVerificationReport {
                verified: false,
                checks: report.checks,
                error_code: Some("verification_report_mismatch".to_string()),
                actual_policy_evaluation: report.actual_policy_evaluation,
                actual_execution_token: report.actual_execution_token,
                token_verification: report.token_verification,
            });
        }
    }

    Ok(report)
}

fn fixed_ts(value: &str) -> Result<Timestamp, ScenarioError> {
    Timestamp::from_str(value).map_err(|error| ScenarioError::Timestamp(error.to_string()))
}

fn read_expected_execution_token(
    path: impl AsRef<Path>,
) -> Result<ExpectedExecutionToken, FixtureError> {
    let path = path.as_ref();
    if !path.exists() {
        return Ok(ExpectedExecutionToken::NotProvided);
    }

    let value: serde_json::Value = read_json_file(path)?;
    if value.is_null() {
        return Ok(ExpectedExecutionToken::ExpectedNull);
    }
    let token = serde_json::from_value::<ExecutionToken>(value).map_err(|source| {
        FixtureError::JsonParseFailed {
            path: path.display().to_string(),
            source,
        }
    })?;
    Ok(ExpectedExecutionToken::ExpectedSome(token))
}

fn read_json_file<T: for<'de> Deserialize<'de>>(path: impl AsRef<Path>) -> Result<T, FixtureError> {
    let path = path.as_ref();
    let contents = fs::read_to_string(path).map_err(|source| FixtureError::ReadFailed {
        path: path.display().to_string(),
        source,
    })?;
    serde_json::from_str(&contents).map_err(|source| FixtureError::JsonParseFailed {
        path: path.display().to_string(),
        source,
    })
}

fn read_optional_json_file<T: for<'de> Deserialize<'de>>(
    path: impl AsRef<Path>,
) -> Result<Option<T>, FixtureError> {
    let path = path.as_ref();
    if !path.exists() {
        return Ok(None);
    }
    read_json_file(path).map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;
    use seedcore_kernel_types::Disposition;

    fn fixture_dir(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/transfers")
            .join(name)
    }

    fn approval_history_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/approval_envelopes")
            .join(name)
    }

    #[test]
    fn loads_allow_case_with_expected_token_object() {
        let fixture =
            load_transfer_fixture(fixture_dir("allow_case")).expect("allow_case should load");
        assert!(fixture.expected_policy_evaluation.is_some());
        assert!(matches!(
            fixture.expected_execution_token,
            ExpectedExecutionToken::ExpectedSome(_)
        ));
    }

    #[test]
    fn loads_deny_case_with_expected_token_null() {
        let fixture = load_transfer_fixture(fixture_dir("deny_missing_approval"))
            .expect("deny_missing_approval should load");
        assert!(matches!(
            fixture.expected_execution_token,
            ExpectedExecutionToken::ExpectedNull
        ));
    }

    #[test]
    fn runs_all_fixture_dispositions() {
        for (name, disposition) in [
            ("allow_case", Disposition::Allow),
            ("deny_missing_approval", Disposition::Deny),
            ("quarantine_stale_telemetry", Disposition::Quarantine),
            ("escalate_break_glass", Disposition::Escalate),
        ] {
            let report =
                run_transfer_fixture_dir(fixture_dir(name)).expect("fixture should execute");
            assert!(report.verified, "fixture `{name}` should verify");
            assert_eq!(report.actual_policy_evaluation.disposition, disposition);
        }
    }

    #[test]
    fn loads_approval_transition_history_fixture() {
        let history = load_approval_transition_history(approval_history_fixture(
            "transition_history_allow.json",
        ))
        .expect("approval history fixture should load");
        assert_eq!(history.events.len(), 1);
        assert_eq!(
            history.chain_head.as_deref(),
            Some("sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72")
        );
    }
}
