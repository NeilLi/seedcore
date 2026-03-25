use seedcore_kernel_testkit::FixtureStaticResolver;
use seedcore_kernel_testkit::{
    run_transfer_fixture_dir, FixtureDebugSigner, TransferVerificationReport,
};
use seedcore_kernel_types::Timestamp;
use seedcore_policy_core::PolicyEvaluation;
use seedcore_proof_core::{
    verify_receipt_artifact, verify_replay_chain, ReplayArtifact, ReplayBundle,
    ReplayVerificationReport, VerificationReport,
};
use seedcore_token_core::{
    enforce_constraints, mint_token, verify_token, ExecutionRequestContext, ExecutionToken,
    ExecutionTokenClaims, TokenEnforcementReport,
};
use serde::{Deserialize, Serialize};
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
            let now = timestamp_from_flag(&args, "--now", "2026-04-02T08:00:30Z")?;
            let report = verify_token(&token, &FixtureStaticResolver, now);
            print_json(&report)
        }
        "enforce-token" => {
            let token_path = flag_value(&args, "--token")?;
            let request_path = flag_value(&args, "--request")?;
            let now = timestamp_from_flag(&args, "--now", "2026-04-02T08:00:30Z")?;
            let report = enforce_token_path(Path::new(&token_path), Path::new(&request_path), now)?;
            print_json(&report)
        }
        "mint-token" => {
            let claims_path = flag_value(&args, "--claims")?;
            let token = mint_token_path(Path::new(&claims_path))?;
            print_json(&token)
        }
        "verify-policy-eval" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let evaluation: PolicyEvaluation = read_json_file(&artifact_path)?;
            let report = PolicyEvaluationReport::from(&evaluation);
            print_json(&report)
        }
        "verify-transfer" | "verify-transfer-dir" => {
            let dir = PathBuf::from(flag_value(&args, "--dir")?);
            let report = verify_transfer_dir(&dir)?;
            print_json(&report)
        }
        "verify-receipt" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let report = verify_receipt_path(Path::new(&artifact_path))?;
            print_json(&report)
        }
        "verify-chain" => {
            let bundle_path = flag_value(&args, "--bundle")?;
            let report = verify_chain_bundle(Path::new(&bundle_path))?;
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
        "  seedcore-verify verify-receipt --artifact <path>",
        "  seedcore-verify verify-chain --bundle <path>",
        "  seedcore-verify verify-transfer --dir <path>",
        "  seedcore-verify mint-token --claims <path>",
        "  seedcore-verify verify-token --artifact <path>",
        "  seedcore-verify enforce-token --token <path> --request <path>",
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

fn optional_flag_value(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn timestamp_from_flag(args: &[String], flag: &str, default: &str) -> Result<Timestamp, String> {
    let raw = optional_flag_value(args, flag).unwrap_or_else(|| default.to_string());
    Timestamp::from_str(&raw).map_err(|error| format!("invalid_timestamp:{flag}:{error}"))
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
    run_transfer_fixture_dir(dir).map_err(|error| error.to_string())
}

fn verify_chain_bundle(path: &Path) -> Result<ReplayVerificationReport, String> {
    let bundle: ReplayBundle = read_json_file(path)?;
    Ok(verify_replay_chain(&bundle, &FixtureStaticResolver))
}

fn verify_receipt_path(path: &Path) -> Result<VerificationReport, String> {
    let artifact: ReplayArtifact = read_json_file(path)?;
    Ok(verify_receipt_artifact(&artifact, &FixtureStaticResolver))
}

fn enforce_token_path(
    token_path: &Path,
    request_path: &Path,
    now: Timestamp,
) -> Result<TokenEnforcementReport, String> {
    let token: ExecutionToken = read_json_file(token_path)?;
    let request: ExecutionRequestContext = read_json_file(request_path)?;
    Ok(enforce_constraints(&token, &request, now))
}

fn mint_token_path(claims_path: &Path) -> Result<ExecutionToken, String> {
    let claims: ExecutionTokenClaims = read_json_file(claims_path)?;
    mint_token(claims, &FixtureDebugSigner).map_err(|error| error.to_string())
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

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_dir(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/transfers")
            .join(name)
    }

    fn replay_bundle_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/replay_bundles")
            .join(name)
    }

    fn receipt_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/receipts")
            .join(name)
    }

    fn token_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/tokens")
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

    #[test]
    fn verify_replay_bundle_fixture() {
        let report = verify_chain_bundle(&replay_bundle_fixture("allow_chain.json"))
            .expect("allow replay bundle should verify");
        assert!(report.verified);
        assert_eq!(report.error_code, None);
        assert_eq!(report.artifact_reports.len(), 2);
    }

    #[test]
    fn verify_receipt_fixture() {
        let report = verify_receipt_path(&receipt_fixture("policy_receipt_artifact.json"))
            .expect("policy receipt artifact should verify");
        assert!(report.verified);
        assert_eq!(report.error_code, None);
        assert_eq!(report.artifact_type, "policy_receipt");
    }

    #[test]
    fn enforce_token_fixture_allows_matching_request() {
        let report = enforce_token_path(
            &fixture_dir("allow_case").join("expected.execution_token.json"),
            &token_fixture("allow_request.json"),
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        )
        .expect("enforce-token should execute");
        assert!(report.allowed);
        assert_eq!(report.error_code, None);
    }

    #[test]
    fn mint_token_fixture_claims() {
        let token = mint_token_path(&token_fixture("mint_claims.json"))
            .expect("mint-token should return token");
        assert_eq!(token.token_id, "token-transfer-001");
        assert_eq!(token.signature.signing_scheme, "debug_hash_v1");
    }
}
