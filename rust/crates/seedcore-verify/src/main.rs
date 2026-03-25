use seedcore_kernel_types::{ArtifactHash, SignatureEnvelope, Timestamp, TransferApprovalEnvelope};
use seedcore_kernel_testkit::{
    load_transfer_fixture, ActionIntentFixture, ExpectedExecutionToken,
};
use seedcore_policy_core::{
    evaluate, FrozenDecisionInput, PolicyEvaluation,
};
use seedcore_proof_core::{KeyMaterial, KeyResolver, Signer, VerificationError};
use seedcore_token_core::{
    enforce_constraints, mint_token, verify_token, ExecutionRequestContext, ExecutionToken,
    ExecutionTokenClaims, TokenConstraints,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::env;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::str::FromStr;

fn main() -> ExitCode {
    match run(env::args().collect()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::from(1)
        }
    }
}

fn run(args: Vec<String>) -> Result<(), String> {
    let Some(command) = args.get(1).map(String::as_str) else {
        return Err(usage());
    };

    match command {
        "verify-token" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let token: ExecutionToken = read_json_file(&artifact_path)?;
            let report = verify_token(
                &token,
                &StaticResolver,
                Timestamp::from_str("2026-04-02T08:00:30Z").map_err(|e| e.to_string())?,
            );
            print_json(&report)
        }
        "verify-policy-eval" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let evaluation: PolicyEvaluation = read_json_file(&artifact_path)?;
            let report = PolicyEvaluationReport::from(&evaluation);
            print_json(&report)
        }
        "verify-transfer-dir" => {
            let dir = PathBuf::from(flag_value(&args, "--dir")?);
            let report = verify_transfer_dir(&dir)?;
            print_json(&report)
        }
        "explain" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let evaluation: PolicyEvaluation = read_json_file(&artifact_path)?;
            print_json(&evaluation.explanation)
        }
        _ => Err(usage()),
    }
}

fn usage() -> String {
    [
        "usage:",
        "  seedcore-verify verify-token --artifact <path>",
        "  seedcore-verify verify-policy-eval --artifact <path>",
        "  seedcore-verify verify-transfer-dir --dir <path>",
        "  seedcore-verify explain --artifact <path>",
    ]
    .join("\n")
}

fn flag_value(args: &[String], flag: &str) -> Result<String, String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
        .ok_or_else(|| format!("missing_flag:{flag}"))
}

fn read_json_file<T: for<'de> Deserialize<'de>>(path: impl AsRef<Path>) -> Result<T, String> {
    let path = path.as_ref();
    let contents = std::fs::read_to_string(path)
        .map_err(|error| format!("read_failed:{}:{error}", path.display()))?;
    serde_json::from_str(&contents)
        .map_err(|error| format!("json_parse_failed:{}:{error}", path.display()))
}

fn print_json<T: Serialize>(value: &T) -> Result<(), String> {
    let rendered = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    println!("{rendered}");
    Ok(())
}

fn verify_transfer_dir(dir: &Path) -> Result<TransferVerificationReport, String> {
    let fixture = load_transfer_fixture(dir).map_err(|error| error.to_string())?;
    let action_intent: ActionIntentFixture = fixture.action_intent.clone();
    let approval_envelope: TransferApprovalEnvelope = fixture.approval_envelope.clone();

    let input = FrozenDecisionInput {
        action_intent_ref: action_intent.action_intent_ref.clone(),
        approval_envelope: Some(approval_envelope.clone()),
        policy_snapshot_ref: approval_envelope.policy_snapshot_ref.clone(),
        asset_state: fixture.asset_state.clone(),
        authority_graph_summary: fixture.authority_graph_summary.clone(),
        telemetry_summary: fixture.telemetry_summary.clone(),
        break_glass: fixture.break_glass.clone(),
    };
    let actual_policy_evaluation = evaluate(&input).map_err(|error| error.to_string())?;
    let expected_policy_evaluation: Option<PolicyEvaluation> = fixture.expected_policy_evaluation.clone();

    let mut checks = Vec::new();
    let mut verified = true;
    let mut error_code = None;

    if let Some(expected) = expected_policy_evaluation.as_ref() {
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
            token_id: format!("token:{}", action_intent.action_intent_ref),
            intent_id: action_intent.action_intent_ref.clone(),
            issued_at: Timestamp::from_str("2026-04-02T08:00:15Z").map_err(|e| e.to_string())?,
            valid_until: Timestamp::from_str("2026-04-02T08:01:15Z").map_err(|e| e.to_string())?,
            contract_version: "transfer-v1".to_string(),
            constraints: TokenConstraints {
                action_type: action_intent.action_type.clone(),
                target_zone: approval_envelope.transfer_context.to_zone.clone(),
                asset_id: Some(input.asset_state.asset_ref.clone()),
                principal_agent_id: action_intent.principal_agent_id.clone(),
                source_registration_id: action_intent.source_registration_id.clone(),
                registration_decision_id: action_intent.registration_decision_id.clone(),
                endpoint_id: action_intent.endpoint_id.clone(),
            },
        };
        let token = mint_token(claims, &DebugSigner).map_err(|error| error.to_string())?;
        let verification = verify_token(
            &token,
            &StaticResolver,
            Timestamp::from_str("2026-04-02T08:00:30Z").map_err(|e| e.to_string())?,
        );
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
                action_type: action_intent.action_type.clone(),
                target_zone: approval_envelope.transfer_context.to_zone.clone(),
                asset_id: Some(input.asset_state.asset_ref.clone()),
                principal_agent_id: action_intent.principal_agent_id.clone(),
                source_registration_id: action_intent.source_registration_id.clone(),
                registration_decision_id: action_intent.registration_decision_id.clone(),
                endpoint_id: action_intent.endpoint_id.clone(),
            },
            Timestamp::from_str("2026-04-02T08:00:30Z").map_err(|e| e.to_string())?,
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

    if let Some(expected_report_value) = fixture.expected_verification_report.as_ref() {
        let expected_report: TransferVerificationReport = serde_json::from_value(expected_report_value.clone())
            .map_err(|error| format!("json_parse_failed:{}:{error}", dir.join("expected.verification_report.json").display()))?;
        if expected_report != report {
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct PolicyEvaluationReport {
    verified: bool,
    disposition: String,
    execution_token_expected: bool,
}

impl From<&PolicyEvaluation> for PolicyEvaluationReport {
    fn from(value: &PolicyEvaluation) -> Self {
        Self {
            verified: !matches!(value.disposition, seedcore_kernel_types::Disposition::Allow)
                || value.execution_token_spec.is_some(),
            disposition: value.disposition.as_str().to_string(),
            execution_token_expected: value.execution_token_spec.is_some(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct TransferVerificationReport {
    verified: bool,
    checks: Vec<String>,
    error_code: Option<String>,
    actual_policy_evaluation: PolicyEvaluation,
    actual_execution_token: Option<ExecutionToken>,
    token_verification: Option<seedcore_token_core::TokenVerificationReport>,
}

struct DebugSigner;

impl Signer for DebugSigner {
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

struct StaticResolver;

impl KeyResolver for StaticResolver {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_dir(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/transfers")
            .join(name)
    }

    #[test]
    fn verify_allow_case_fixture() {
        let report =
            verify_transfer_dir(&fixture_dir("allow_case")).expect("allow_case should evaluate");
        assert!(report.verified);
        assert_eq!(
            report.actual_policy_evaluation.disposition,
            seedcore_kernel_types::Disposition::Allow
        );
    }

    #[test]
    fn verify_deny_case_fixture() {
        let report = verify_transfer_dir(&fixture_dir("deny_missing_approval"))
            .expect("deny_missing_approval should evaluate");
        assert!(report.verified);
        assert_eq!(
            report.actual_policy_evaluation.disposition,
            seedcore_kernel_types::Disposition::Deny
        );
    }

    #[test]
    fn verify_quarantine_case_fixture() {
        let report = verify_transfer_dir(&fixture_dir("quarantine_stale_telemetry"))
            .expect("quarantine_stale_telemetry should evaluate");
        assert!(report.verified);
        assert_eq!(
            report.actual_policy_evaluation.disposition,
            seedcore_kernel_types::Disposition::Quarantine
        );
    }

    #[test]
    fn verify_escalate_case_fixture() {
        let report = verify_transfer_dir(&fixture_dir("escalate_break_glass"))
            .expect("escalate_break_glass should evaluate");
        assert!(report.verified);
        assert_eq!(
            report.actual_policy_evaluation.disposition,
            seedcore_kernel_types::Disposition::Escalate
        );
    }
}
