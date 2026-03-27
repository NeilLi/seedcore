use seedcore_approval_core::{
    apply_transition, approval_binding_hash, validate_envelope, ApprovalTransition,
};
use seedcore_kernel_testkit::FixtureStaticResolver;
use seedcore_kernel_testkit::{
    load_transfer_fixture, run_transfer_fixture_dir, FixtureDebugSigner, TransferVerificationReport,
};
use seedcore_kernel_types::{
    ApprovalStatus, ApprovalTransitionEvent, ApprovalTransitionHistory, ArtifactHash, Disposition,
    ReplayArtifactPayload, RevocationRecord, RoleApproval, SignatureEnvelope, Timestamp,
    TransferApprovalEnvelope, TransitionReceipt, TrustBundle, TrustProof,
};
use seedcore_policy_core::PolicyEvaluation;
use seedcore_policy_core::FrozenDecisionInput;
use seedcore_proof_core::{
    hash_artifact, verify_detached_signature, verify_receipt_artifact, verify_replay_chain,
    ReplayArtifact, ReplayBundle, ReplayVerificationReport, Signer, VerificationReport,
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
        "evaluate-policy" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let input: FrozenDecisionInput = read_json_file(&artifact_path)?;
            let evaluation = seedcore_policy_core::evaluate(&input)
                .map_err(|error| format!("policy_evaluation_failed:{error}"))?;
            print_json(&evaluation)
        }
        "verify-transfer" | "verify-transfer-dir" => {
            let dir = PathBuf::from(flag_value(&args, "--dir")?);
            let report = verify_transfer_dir(&dir)?;
            print_json(&report)
        }
        "summarize-transfer" => {
            let dir = PathBuf::from(flag_value(&args, "--dir")?);
            let summary = summarize_transfer_dir(&dir)?;
            print_json(&summary)
        }
        "validate-approval" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let report = validate_approval_path(Path::new(&artifact_path))?;
            print_json(&report)
        }
        "approval-binding-hash" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let report = approval_binding_hash_path(Path::new(&artifact_path))?;
            print_json(&report)
        }
        "approval-summary" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let report = approval_summary_path(Path::new(&artifact_path))?;
            print_json(&report)
        }
        "apply-approval-transition" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let transition_path = flag_value(&args, "--transition")?;
            let history_path = optional_flag_value(&args, "--history");
            let now = timestamp_from_flag(&args, "--now", "2026-04-02T08:00:30Z")?;
            let report = apply_approval_transition_path(
                Path::new(&artifact_path),
                Path::new(&transition_path),
                history_path.as_deref().map(Path::new),
                now,
            )?;
            print_json(&report)
        }
        "verify-approval-history" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let report = verify_approval_history_path(Path::new(&artifact_path))?;
            print_json(&report)
        }
        "verify-receipt" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let trust_bundle_path = optional_flag_value(&args, "--trust-bundle");
            let previous_path = optional_flag_value(&args, "--previous");
            let report = verify_receipt_path(
                Path::new(&artifact_path),
                trust_bundle_path.as_deref().map(Path::new),
                previous_path.as_deref().map(Path::new),
            )?;
            print_json(&report)
        }
        "verify-chain" => {
            let bundle_path = flag_value(&args, "--bundle")?;
            let trust_bundle_path = optional_flag_value(&args, "--trust-bundle");
            let report = verify_chain_bundle(
                Path::new(&bundle_path),
                trust_bundle_path.as_deref().map(Path::new),
            )?;
            print_json(&report)
        }
        "inspect-trust" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let trust_bundle_path = flag_value(&args, "--trust-bundle")?;
            let report = inspect_trust_path(Path::new(&artifact_path), Path::new(&trust_bundle_path))?;
            print_json(&report)
        }
        "seal-replay-bundle" => {
            let artifact_path = flag_value(&args, "--artifact")?;
            let bundle = seal_replay_bundle_path(Path::new(&artifact_path))?;
            print_json(&bundle)
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
        "  seedcore-verify verify-receipt --artifact <path> --trust-bundle <path> [--previous <path>]",
        "  seedcore-verify verify-chain --bundle <path> [--trust-bundle <path>]",
        "  seedcore-verify inspect-trust --artifact <path> --trust-bundle <path>",
        "  seedcore-verify seal-replay-bundle --artifact <path>",
        "  seedcore-verify verify-transfer --dir <path>",
        "  seedcore-verify summarize-transfer --dir <path>",
        "  seedcore-verify validate-approval --artifact <path>",
        "  seedcore-verify approval-binding-hash --artifact <path>",
        "  seedcore-verify approval-summary --artifact <path>",
        "  seedcore-verify apply-approval-transition --artifact <path> --transition <path> [--history <path>] [--now <rfc3339>]",
        "  seedcore-verify verify-approval-history --artifact <path>",
        "  seedcore-verify mint-token --claims <path>",
        "  seedcore-verify verify-token --artifact <path>",
        "  seedcore-verify enforce-token --token <path> --request <path>",
        "  seedcore-verify verify-policy-eval --artifact <path>",
        "  seedcore-verify evaluate-policy --artifact <path>",
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct SignedTrustBundleEnvelope {
    trust_bundle: TrustBundle,
    payload_hash: String,
    signature_envelope: SignatureEnvelope,
    #[serde(default)]
    trust_proof: Option<TrustProof>,
}

fn load_trust_bundle(path: &Path) -> Result<TrustBundle, String> {
    let contents = std::fs::read_to_string(path)
        .map_err(|error| format!("read_failed:{}:{error}", path.display()))?;
    if let Ok(bundle) = serde_json::from_str::<TrustBundle>(&contents) {
        return Ok(bundle);
    }
    let envelope: SignedTrustBundleEnvelope = serde_json::from_str(&contents)
        .map_err(|error| format!("json_parse_failed:{}:{error}", path.display()))?;
    let computed_hash = hash_artifact(&envelope.trust_bundle)
        .map_err(|error| format!("trust_bundle_hash_failed:{error}"))?;
    let expected_hash_hex = normalize_sha256_hex(&envelope.payload_hash)
        .ok_or_else(|| "invalid_trust_bundle_payload_hash".to_string())?;
    if computed_hash.algorithm != "sha256" || computed_hash.value != expected_hash_hex {
        return Err(format!(
            "trust_bundle_payload_hash_mismatch:expected=sha256:{expected_hash_hex}:computed={computed_hash}"
        ));
    }
    let expected_key_ref = trust_bundle_signing_key_ref();
    let actual_key_ref = envelope
        .signature_envelope
        .key_ref
        .as_deref()
        .ok_or_else(|| "missing_trust_bundle_signing_key_ref".to_string())?;
    if actual_key_ref != expected_key_ref {
        return Err(format!(
            "trust_bundle_signing_key_ref_mismatch:expected={expected_key_ref}:actual={actual_key_ref}"
        ));
    }
    let resolver = TrustBundleEnvelopeResolver::new(expected_key_ref.clone());
    let report = verify_detached_signature(
        &envelope.signature_envelope,
        &ArtifactHash::sha256_hex(expected_hash_hex),
        "trust_bundle",
        &resolver,
    );
    if !report.verified {
        return Err(format!(
            "trust_bundle_signature_invalid:{}:{}",
            report.error_code.unwrap_or_else(|| "signature_invalid".to_string()),
            report.details.join(",")
        ));
    }
    Ok(envelope.trust_bundle)
}

fn normalize_sha256_hex(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    let candidate = if let Some(stripped) = trimmed.strip_prefix("sha256:") {
        stripped
    } else {
        trimmed
    };
    if candidate.is_empty() {
        return None;
    }
    if !candidate.chars().all(|item| item.is_ascii_hexdigit()) {
        return None;
    }
    Some(candidate.to_ascii_lowercase())
}

fn print_json<T: Serialize>(value: &T) -> Result<(), String> {
    let rendered = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    println!("{rendered}");
    Ok(())
}

fn verify_transfer_dir(dir: &Path) -> Result<TransferVerificationReport, String> {
    run_transfer_fixture_dir(dir).map_err(|error| error.to_string())
}

fn validate_approval_path(path: &Path) -> Result<ApprovalValidationReport, String> {
    let envelope: TransferApprovalEnvelope = read_json_file(path)?;
    match validate_envelope(&envelope) {
        Ok(()) => Ok(ApprovalValidationReport {
            valid: true,
            error_code: None,
            details: Vec::new(),
        }),
        Err(error) => Ok(ApprovalValidationReport {
            valid: false,
            error_code: Some("approval_invalid".to_string()),
            details: vec![error.to_string()],
        }),
    }
}

fn approval_binding_hash_path(path: &Path) -> Result<ApprovalBindingHashReport, String> {
    let envelope: TransferApprovalEnvelope = read_json_file(path)?;
    match approval_binding_hash(&envelope) {
        Ok(hash) => Ok(ApprovalBindingHashReport {
            valid: true,
            binding_hash: Some(artifact_hash_to_string(&hash)),
            error_code: None,
            details: Vec::new(),
        }),
        Err(error) => Ok(ApprovalBindingHashReport {
            valid: false,
            binding_hash: None,
            error_code: Some("approval_binding_hash_failed".to_string()),
            details: vec![error.to_string()],
        }),
    }
}

fn approval_summary_path(path: &Path) -> Result<ApprovalSummaryReport, String> {
    let envelope: TransferApprovalEnvelope = read_json_file(path)?;
    if let Err(error) = validate_envelope(&envelope) {
        return Ok(ApprovalSummaryReport {
            valid: false,
            status: None,
            required_roles: Vec::new(),
            approved_by: Vec::new(),
            co_signed: false,
            binding_hash: None,
            error_code: Some("approval_invalid".to_string()),
            details: vec![error.to_string()],
        });
    }

    let mut required_roles = Vec::new();
    let mut approved_by = Vec::new();
    for item in &envelope.required_approvals {
        let role = item.role.trim().to_string();
        if !role.is_empty() && !required_roles.contains(&role) {
            required_roles.push(role);
        }
        if item.status == ApprovalStatus::Approved {
            let principal = item.principal_ref.trim().to_string();
            if !principal.is_empty() && !approved_by.contains(&principal) {
                approved_by.push(principal);
            }
        }
    }
    let co_signed = envelope
        .required_approvals
        .iter()
        .all(|item| item.status == ApprovalStatus::Approved);
    match approval_binding_hash(&envelope) {
        Ok(hash) => Ok(ApprovalSummaryReport {
            valid: true,
            status: Some(approval_status_label(envelope.status).to_string()),
            required_roles,
            approved_by,
            co_signed,
            binding_hash: Some(artifact_hash_to_string(&hash)),
            error_code: None,
            details: Vec::new(),
        }),
        Err(error) => Ok(ApprovalSummaryReport {
            valid: false,
            status: Some(approval_status_label(envelope.status).to_string()),
            required_roles,
            approved_by,
            co_signed,
            binding_hash: None,
            error_code: Some("approval_binding_hash_failed".to_string()),
            details: vec![error.to_string()],
        }),
    }
}

fn apply_approval_transition_path(
    artifact_path: &Path,
    transition_path: &Path,
    history_path: Option<&Path>,
    now: Timestamp,
) -> Result<ApprovalTransitionReport, String> {
    let envelope: TransferApprovalEnvelope = read_json_file(artifact_path)?;
    let transition_input: ApprovalTransitionInput = read_json_file(transition_path)?;
    let history = match history_path {
        Some(path) => read_json_file(path)?,
        None => ApprovalTransitionHistory::default(),
    };
    Ok(apply_approval_transition(
        envelope,
        transition_input,
        history,
        now,
    ))
}

fn apply_approval_transition(
    envelope: TransferApprovalEnvelope,
    transition_input: ApprovalTransitionInput,
    history: ApprovalTransitionHistory,
    now: Timestamp,
) -> ApprovalTransitionReport {
    if let Err(error) = validate_transition_history(&history) {
        return ApprovalTransitionReport {
            valid: false,
            approval_envelope: None,
            binding_hash: None,
            transition_event: None,
            history: Some(history),
            error_code: Some("approval_transition_history_invalid".to_string()),
            details: vec![error],
        };
    }

    let transition_type = transition_input.transition_type().to_string();
    let previous_status = approval_status_label(envelope.status).to_string();
    let previous_binding_hash = envelope
        .approval_binding_hash
        .as_ref()
        .map(artifact_hash_to_string);
    let previous_event_hash = history.chain_head.clone();
    let transition = transition_input.into_core_transition();
    match apply_transition(&envelope, transition, now.clone()) {
        Ok(updated) => {
            let next_binding_hash = updated
                .approval_binding_hash
                .as_ref()
                .map(artifact_hash_to_string);
            let transition_event = match build_transition_event(
                &updated,
                previous_event_hash,
                now,
                transition_type,
                previous_status,
                previous_binding_hash,
                next_binding_hash.clone(),
            ) {
                Ok(value) => value,
                Err(error) => {
                    return ApprovalTransitionReport {
                        valid: false,
                        approval_envelope: None,
                        binding_hash: None,
                        transition_event: None,
                        history: Some(history),
                        error_code: Some("approval_transition_event_failed".to_string()),
                        details: vec![error],
                    };
                }
            };
            let mut updated_history = history;
            updated_history.events.push(transition_event.clone());
            updated_history.chain_head = Some(transition_event.event_hash.clone());
            ApprovalTransitionReport {
                valid: true,
                approval_envelope: Some(updated.clone()),
                binding_hash: next_binding_hash,
                transition_event: Some(transition_event),
                history: Some(updated_history),
                error_code: None,
                details: Vec::new(),
            }
        }
        Err(error) => ApprovalTransitionReport {
            valid: false,
            approval_envelope: None,
            binding_hash: None,
            transition_event: None,
            history: Some(history),
            error_code: Some("approval_transition_failed".to_string()),
            details: vec![error.to_string()],
        },
    }
}

fn verify_approval_history_path(path: &Path) -> Result<ApprovalTransitionHistoryReport, String> {
    let history: ApprovalTransitionHistory = read_json_file(path)?;
    Ok(verify_approval_history_path_from_value(&history))
}

fn verify_approval_history_path_from_value(
    history: &ApprovalTransitionHistory,
) -> ApprovalTransitionHistoryReport {
    match validate_transition_history(history) {
        Ok(()) => ApprovalTransitionHistoryReport {
            valid: true,
            chain_head: history.chain_head.clone(),
            event_count: history.events.len(),
            error_code: None,
            details: Vec::new(),
        },
        Err(error) => ApprovalTransitionHistoryReport {
            valid: false,
            chain_head: history.chain_head.clone(),
            event_count: history.events.len(),
            error_code: Some("approval_transition_history_invalid".to_string()),
            details: vec![error],
        },
    }
}

fn summarize_transfer_dir(dir: &Path) -> Result<TransferTrustSummary, String> {
    let report = verify_transfer_dir(dir)?;
    let fixture = load_transfer_fixture(dir).map_err(|error| error.to_string())?;
    let disposition = report.actual_policy_evaluation.disposition;

    Ok(TransferTrustSummary {
        verified: report.verified,
        business_state: business_state_label(report.verified, disposition).to_string(),
        disposition: disposition.as_str().to_string(),
        approval_status: approval_status_label(fixture.approval_envelope.status).to_string(),
        execution_token_expected: report
            .actual_policy_evaluation
            .execution_token_spec
            .is_some(),
        execution_token_present: report.actual_execution_token.is_some(),
        verification_error_code: report.error_code,
        checks: report.checks,
    })
}

fn business_state_label(verified: bool, disposition: Disposition) -> &'static str {
    if !verified {
        return "verification_failed";
    }
    match disposition {
        Disposition::Allow => "verified",
        Disposition::Deny => "rejected",
        Disposition::Quarantine => "quarantined",
        Disposition::Escalate => "review_required",
    }
}

fn approval_status_label(status: ApprovalStatus) -> &'static str {
    match status {
        ApprovalStatus::Pending => "PENDING",
        ApprovalStatus::PartiallyApproved => "PARTIALLY_APPROVED",
        ApprovalStatus::Approved => "APPROVED",
        ApprovalStatus::Expired => "EXPIRED",
        ApprovalStatus::Revoked => "REVOKED",
        ApprovalStatus::Superseded => "SUPERSEDED",
    }
}

fn artifact_hash_to_string(hash: &ArtifactHash) -> String {
    format!("{}:{}", hash.algorithm, hash.value)
}

fn build_transition_event(
    updated: &TransferApprovalEnvelope,
    previous_event_hash: Option<String>,
    now: Timestamp,
    transition_type: String,
    previous_status: String,
    previous_binding_hash: Option<String>,
    next_binding_hash: Option<String>,
) -> Result<ApprovalTransitionEvent, String> {
    let material = ApprovalTransitionEventHashMaterial {
        previous_event_hash: previous_event_hash.clone(),
        occurred_at: now.clone(),
        transition_type: transition_type.clone(),
        envelope_id: updated.approval_envelope_id.clone(),
        previous_status,
        next_status: approval_status_label(updated.status).to_string(),
        previous_binding_hash,
        next_binding_hash,
        envelope_version: updated.version,
    };
    let event_hash = hash_artifact(&material)
        .map_err(|error| format!("transition_event_hash_failed:{error}"))
        .map(|hash| artifact_hash_to_string(&hash))?;
    Ok(ApprovalTransitionEvent {
        event_id: format!("approval-transition-event:{event_hash}"),
        event_hash,
        previous_event_hash,
        occurred_at: now,
        transition_type: material.transition_type,
        envelope_id: material.envelope_id,
        previous_status: material.previous_status,
        next_status: material.next_status,
        previous_binding_hash: material.previous_binding_hash,
        next_binding_hash: material.next_binding_hash,
        envelope_version: material.envelope_version,
    })
}

fn transition_event_hash_from_event(event: &ApprovalTransitionEvent) -> Result<String, String> {
    let material = ApprovalTransitionEventHashMaterial {
        previous_event_hash: event.previous_event_hash.clone(),
        occurred_at: event.occurred_at.clone(),
        transition_type: event.transition_type.clone(),
        envelope_id: event.envelope_id.clone(),
        previous_status: event.previous_status.clone(),
        next_status: event.next_status.clone(),
        previous_binding_hash: event.previous_binding_hash.clone(),
        next_binding_hash: event.next_binding_hash.clone(),
        envelope_version: event.envelope_version,
    };
    hash_artifact(&material)
        .map_err(|error| format!("transition_event_hash_failed:{error}"))
        .map(|hash| artifact_hash_to_string(&hash))
}

fn validate_transition_history(history: &ApprovalTransitionHistory) -> Result<(), String> {
    let mut expected_previous: Option<String> = None;
    for (index, event) in history.events.iter().enumerate() {
        if event.previous_event_hash != expected_previous {
            return Err(format!("history_chain_mismatch:{index}"));
        }
        let expected_hash = transition_event_hash_from_event(event)?;
        if expected_hash != event.event_hash {
            return Err(format!("history_hash_mismatch:{index}"));
        }
        expected_previous = Some(event.event_hash.clone());
    }
    if history.chain_head != expected_previous {
        return Err("history_chain_head_mismatch".to_string());
    }
    Ok(())
}

fn verify_chain_bundle(
    path: &Path,
    trust_bundle_path: Option<&Path>,
) -> Result<ReplayVerificationReport, String> {
    let bundle: ReplayBundle = read_json_file(path)?;
    if let Some(bundle_path) = trust_bundle_path {
        let trust_bundle = load_trust_bundle(bundle_path)?;
        let resolver = TrustBundleResolver::from_bundle(&trust_bundle);
        let mut report = verify_replay_chain(&bundle, &resolver);
        for (index, artifact) in bundle.artifacts.iter().enumerate() {
            let previous_transition = previous_transition_receipt(&bundle, index);
            report.artifact_reports[index] = apply_trust_bundle_checks(
                report.artifact_reports[index].clone(),
                artifact,
                &trust_bundle,
                previous_transition,
            );
        }
        report.verified = report.artifact_reports.iter().all(|item| item.verified)
            && report.error_code.is_none()
            && report.chain_checks.iter().all(|item| !item.contains("mismatch"));
        if !report.verified && report.error_code.is_none() {
            report.error_code = report
                .artifact_reports
                .iter()
                .find_map(|item| item.error_code.clone())
                .or_else(|| Some("replay_artifact_verification_failed".to_string()));
        }
        return Ok(report);
    }
    Ok(verify_replay_chain(&bundle, &FixtureStaticResolver))
}

fn seal_replay_bundle_path(path: &Path) -> Result<ReplayBundle, String> {
    let input: ReplayBundleInput = read_json_file(path)?;
    seal_replay_bundle(input)
}

fn seal_replay_bundle(input: ReplayBundleInput) -> Result<ReplayBundle, String> {
    if input.artifacts.is_empty() {
        return Err("empty_replay_bundle_input".to_string());
    }

    let mut previous_hash: Option<ArtifactHash> = None;
    let mut sealed = Vec::with_capacity(input.artifacts.len());
    for item in input.artifacts {
        let artifact_hash =
            hash_artifact(&item.payload).map_err(|error| format!("replay_hash_failed:{error}"))?;
        let signature = FixtureDebugSigner
            .sign_hash(&artifact_hash)
            .map_err(|error| format!("replay_sign_failed:{error}"))?;
        sealed.push(ReplayArtifact {
            artifact_id: item.artifact_id,
            payload: item.payload,
            artifact_hash: artifact_hash.clone(),
            signature,
            previous_artifact_hash: previous_hash.clone(),
        });
        previous_hash = Some(artifact_hash);
    }
    Ok(ReplayBundle { artifacts: sealed })
}

fn verify_receipt_path(
    path: &Path,
    trust_bundle_path: Option<&Path>,
    previous_path: Option<&Path>,
) -> Result<VerificationReport, String> {
    let artifact: ReplayArtifact = read_json_file(path)?;
    if let Some(bundle_path) = trust_bundle_path {
        let trust_bundle = load_trust_bundle(bundle_path)?;
        let resolver = TrustBundleResolver::from_bundle(&trust_bundle);
        let report = verify_receipt_artifact(&artifact, &resolver);
        let previous_artifact = match previous_path {
            Some(path) => Some(read_json_file(path)?),
            None => None,
        };
        return Ok(apply_trust_bundle_checks(
            report,
            &artifact,
            &trust_bundle,
            previous_artifact.as_ref(),
        ));
    }
    Ok(verify_receipt_artifact(&artifact, &FixtureStaticResolver))
}

fn inspect_trust_path(path: &Path, trust_bundle_path: &Path) -> Result<TrustInspectionReport, String> {
    let artifact: ReplayArtifact = read_json_file(path)?;
    let trust_bundle = load_trust_bundle(trust_bundle_path)?;
    let resolver = TrustBundleResolver::from_bundle(&trust_bundle);
    let verification = verify_receipt_artifact(&artifact, &resolver);
    let checked = apply_trust_bundle_checks(verification, &artifact, &trust_bundle, None);
    let trust_proof = trust_proof_from_artifact(&artifact).cloned();
    Ok(TrustInspectionReport {
        artifact_id: artifact.artifact_id.clone(),
        artifact_type: artifact.payload.artifact_type().to_string(),
        key_ref: artifact.signature.key_ref.clone(),
        trust_proof,
        signature_valid: checked.signature_valid,
        artifact_hash_valid: checked.artifact_hash_valid,
        trust_anchor_valid: checked.trust_anchor_valid,
        attestation_valid: checked.attestation_valid,
        revocation_valid: checked.revocation_valid,
        replay_status: checked.replay_status,
        transparency_status: checked.transparency_status,
        verified: checked.verified,
        error_code: checked.error_code,
        details: checked.details,
    })
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

#[derive(Debug, Clone)]
struct TrustBundleResolver {
    bundle: TrustBundle,
}

impl TrustBundleResolver {
    fn from_bundle(bundle: &TrustBundle) -> Self {
        Self { bundle: bundle.clone() }
    }
}

impl seedcore_proof_core::KeyResolver for TrustBundleResolver {
    fn resolve(&self, key_ref: &str) -> Result<seedcore_proof_core::KeyMaterial, seedcore_proof_core::VerificationError> {
        if let Some(entry) = self.bundle.trusted_keys.get(key_ref) {
            let mut metadata = entry.metadata.clone();
            metadata.insert("key_algorithm".to_string(), entry.key_algorithm.clone());
            metadata.insert("trust_anchor_type".to_string(), entry.trust_anchor_type.clone());
            if let Some(value) = &entry.endpoint_id {
                metadata.insert("endpoint_id".to_string(), value.clone());
            }
            if let Some(value) = &entry.node_id {
                metadata.insert("node_id".to_string(), value.clone());
            }
            if let Some(value) = &entry.revocation_id {
                metadata.insert("revocation_id".to_string(), value.clone());
            }
            return Ok(seedcore_proof_core::KeyMaterial {
                key_ref: key_ref.to_string(),
                public_material: entry.public_key.clone(),
                metadata,
            });
        }
        Err(seedcore_proof_core::VerificationError::KeyNotFound)
    }
}

#[derive(Debug, Clone)]
struct TrustBundleEnvelopeResolver {
    key_ref: String,
    secret: String,
}

impl TrustBundleEnvelopeResolver {
    fn new(key_ref: String) -> Self {
        Self {
            key_ref,
            secret: trust_bundle_signing_secret(),
        }
    }
}

impl seedcore_proof_core::KeyResolver for TrustBundleEnvelopeResolver {
    fn resolve(
        &self,
        key_ref: &str,
    ) -> Result<seedcore_proof_core::KeyMaterial, seedcore_proof_core::VerificationError> {
        if key_ref != self.key_ref {
            return Err(seedcore_proof_core::VerificationError::KeyNotFound);
        }
        let mut metadata = std::collections::BTreeMap::new();
        metadata.insert("hmac_secret".to_string(), self.secret.clone());
        Ok(seedcore_proof_core::KeyMaterial {
            key_ref: key_ref.to_string(),
            public_material: String::new(),
            metadata,
        })
    }
}

fn trust_bundle_signing_secret() -> String {
    env::var("SEEDCORE_TRUST_BUNDLE_SIGNING_SECRET")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            env::var("SEEDCORE_TRUST_SIGNING_SECRET")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .or_else(|| {
            env::var("SEEDCORE_EVIDENCE_SIGNING_SECRET")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .unwrap_or_else(|| "seedcore-dev-evidence-secret".to_string())
}

fn trust_bundle_signing_key_ref() -> String {
    env::var("SEEDCORE_TRUST_BUNDLE_SIGNING_KEY_REF")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "seedcore-trust-bundle-hmac".to_string())
}

fn apply_trust_bundle_checks(
    mut report: VerificationReport,
    artifact: &ReplayArtifact,
    trust_bundle: &TrustBundle,
    previous_transition: Option<&ReplayArtifact>,
) -> VerificationReport {
    if !report.artifact_hash_valid {
        return report;
    }
    if !report.signature_valid {
        return report;
    }
    let Some(trust_proof) = trust_proof_from_artifact(artifact) else {
        return report;
    };

    report.trust_anchor_valid = trust_bundle.accepted_trust_anchor_types.is_empty()
        || trust_bundle
            .accepted_trust_anchor_types
            .iter()
            .any(|item| item == &trust_proof.trust_anchor_type);
    if !report.trust_anchor_valid {
        report.verified = false;
        report.error_code = Some("invalid_trust_anchor".to_string());
        return report;
    }

    if let Some(key_ref) = artifact.signature.key_ref.as_deref() {
        if key_ref != trust_proof.key_ref {
            report.verified = false;
            report.error_code = Some("key_ref_mismatch".to_string());
            return report;
        }
        if let Some(entry) = trust_bundle.trusted_keys.get(key_ref) {
            if entry.key_algorithm != trust_proof.key_algorithm {
                report.verified = false;
                report.error_code = Some("invalid_key_algorithm".to_string());
                return report;
            }
            if let Some(endpoint_id) = &entry.endpoint_id {
                if !artifact_endpoint_matches(artifact, endpoint_id) {
                    report.verified = false;
                    report.error_code = Some("endpoint_binding_mismatch".to_string());
                    return report;
                }
            }
        }
    }

    report.attestation_valid = trust_proof
        .attestation
        .as_ref()
        .map(|item| item.attestation_type != "none")
        .unwrap_or(false);
    if !report.attestation_valid {
        report.verified = false;
        report.error_code = Some("missing_attestation_binding".to_string());
        return report;
    }

    report.revocation_valid = !is_trust_proof_revoked(trust_proof, artifact, trust_bundle);
    if !report.revocation_valid {
        report.verified = false;
        report.error_code = Some("revoked_signer".to_string());
        return report;
    }

    let replay_status = replay_status_for_artifact(artifact, trust_proof, previous_transition);
    report.replay_status = replay_status.clone();
    if replay_status == "replayed" {
        report.verified = false;
        report.error_code = Some("replayed".to_string());
        return report;
    }

    report.transparency_status = trust_proof
        .transparency
        .as_ref()
        .map(|item| item.status.clone())
        .unwrap_or_else(|| "not_configured".to_string());
    if report.transparency_status == "anchor_verification_failed" {
        report.verified = false;
        report.error_code = Some("anchor_verification_failed".to_string());
        return report;
    }

    report
}

fn trust_proof_from_artifact(artifact: &ReplayArtifact) -> Option<&TrustProof> {
    match &artifact.payload {
        ReplayArtifactPayload::PolicyReceipt(value) => value.trust_proof.as_ref(),
        ReplayArtifactPayload::TransitionReceipt(value) => value.trust_proof.as_ref(),
        ReplayArtifactPayload::EvidenceBundle(value) => value.trust_proof.as_ref(),
        _ => None,
    }
}

fn artifact_endpoint_matches(artifact: &ReplayArtifact, expected: &str) -> bool {
    match &artifact.payload {
        ReplayArtifactPayload::TransitionReceipt(value) => value.endpoint_id == expected,
        _ => true,
    }
}

fn previous_transition_receipt(bundle: &ReplayBundle, index: usize) -> Option<&ReplayArtifact> {
    if index == 0 {
        return None;
    }
    for candidate in bundle.artifacts[..index].iter().rev() {
        if matches!(candidate.payload, ReplayArtifactPayload::TransitionReceipt(_)) {
            return Some(candidate);
        }
    }
    None
}

fn replay_status_for_artifact(
    _artifact: &ReplayArtifact,
    trust_proof: &TrustProof,
    previous_transition: Option<&ReplayArtifact>,
) -> String {
    let Some(replay) = trust_proof.replay.as_ref() else {
        return "not_proven_offline".to_string();
    };
    let Some(counter) = replay.receipt_counter else {
        return "not_proven_offline".to_string();
    };
    if let Some(previous) = previous_transition {
        if let ReplayArtifactPayload::TransitionReceipt(previous_receipt) = &previous.payload {
            let previous_hash = previous_receipt.payload_hash.to_string();
            let previous_counter = previous_receipt
                .trust_proof
                .as_ref()
                .and_then(|item| item.replay.as_ref())
                .and_then(|item| item.receipt_counter);
            if replay.previous_receipt_hash.as_deref() != Some(previous_hash.as_str()) {
                return "replayed".to_string();
            }
            if let Some(previous_counter) = previous_counter {
                if counter <= previous_counter {
                    return "replayed".to_string();
                }
            }
            return "valid".to_string();
        }
    }
    "not_proven_offline".to_string()
}

fn is_trust_proof_revoked(
    trust_proof: &TrustProof,
    artifact: &ReplayArtifact,
    trust_bundle: &TrustBundle,
) -> bool {
    if trust_bundle.revoked_keys.iter().any(|item| item == &trust_proof.key_ref) {
        return true;
    }
    if let Some(revocation_id) = &trust_proof.revocation_id {
        if let Some(cutoff) = trust_bundle.revocation_cutoffs.get(revocation_id) {
            if let Ok(cutoff_counter) = cutoff.parse::<u64>() {
                let receipt_counter = trust_proof
                    .replay
                    .as_ref()
                    .and_then(|item| item.receipt_counter)
                    .unwrap_or_default();
                if receipt_counter <= cutoff_counter {
                    return true;
                }
            }
        }
    }
    if let ReplayArtifactPayload::TransitionReceipt(TransitionReceipt { endpoint_id, .. }) = &artifact.payload {
        if trust_bundle.revoked_nodes.iter().any(|item| item == endpoint_id) {
            return true;
        }
    }
    false
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct PolicyEvaluationReport {
    verified: bool,
    disposition: String,
    execution_token_expected: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct TrustInspectionReport {
    artifact_id: String,
    artifact_type: String,
    key_ref: Option<String>,
    trust_proof: Option<TrustProof>,
    signature_valid: bool,
    artifact_hash_valid: bool,
    trust_anchor_valid: bool,
    attestation_valid: bool,
    revocation_valid: bool,
    replay_status: String,
    transparency_status: String,
    verified: bool,
    error_code: Option<String>,
    details: Vec<String>,
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
struct TransferTrustSummary {
    verified: bool,
    business_state: String,
    disposition: String,
    approval_status: String,
    execution_token_expected: bool,
    execution_token_present: bool,
    verification_error_code: Option<String>,
    checks: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ApprovalValidationReport {
    valid: bool,
    error_code: Option<String>,
    details: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ApprovalBindingHashReport {
    valid: bool,
    binding_hash: Option<String>,
    error_code: Option<String>,
    details: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ApprovalSummaryReport {
    valid: bool,
    status: Option<String>,
    required_roles: Vec<String>,
    approved_by: Vec<String>,
    co_signed: bool,
    binding_hash: Option<String>,
    error_code: Option<String>,
    details: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum ApprovalTransitionInput {
    AddApproval {
        role: String,
        principal_ref: String,
        approval_ref: String,
        approved_at: Option<Timestamp>,
    },
    Revoke {
        revoked_by: String,
        revoked_at: Timestamp,
        reason: String,
    },
    Expire {
        expired_at: Timestamp,
    },
    Supersede {
        successor_envelope_id: String,
    },
}

impl ApprovalTransitionInput {
    fn transition_type(&self) -> &'static str {
        match self {
            Self::AddApproval { .. } => "add_approval",
            Self::Revoke { .. } => "revoke",
            Self::Expire { .. } => "expire",
            Self::Supersede { .. } => "supersede",
        }
    }

    fn into_core_transition(self) -> ApprovalTransition {
        match self {
            Self::AddApproval {
                role,
                principal_ref,
                approval_ref,
                approved_at,
            } => ApprovalTransition::AddApproval(RoleApproval {
                role,
                principal_ref,
                status: ApprovalStatus::Approved,
                approved_at,
                approval_ref,
            }),
            Self::Revoke {
                revoked_by,
                revoked_at,
                reason,
            } => ApprovalTransition::Revoke(RevocationRecord {
                revoked_by,
                revoked_at,
                reason,
            }),
            Self::Expire { expired_at } => ApprovalTransition::Expire(expired_at),
            Self::Supersede {
                successor_envelope_id,
            } => ApprovalTransition::Supersede {
                successor_envelope_id,
            },
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ApprovalTransitionReport {
    valid: bool,
    approval_envelope: Option<TransferApprovalEnvelope>,
    binding_hash: Option<String>,
    transition_event: Option<ApprovalTransitionEvent>,
    history: Option<ApprovalTransitionHistory>,
    error_code: Option<String>,
    details: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ApprovalTransitionHistoryReport {
    valid: bool,
    chain_head: Option<String>,
    event_count: usize,
    error_code: Option<String>,
    details: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct ApprovalTransitionEventHashMaterial {
    previous_event_hash: Option<String>,
    occurred_at: Timestamp,
    transition_type: String,
    envelope_id: String,
    previous_status: String,
    next_status: String,
    previous_binding_hash: Option<String>,
    next_binding_hash: Option<String>,
    envelope_version: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ReplayArtifactInput {
    artifact_id: String,
    #[serde(flatten)]
    payload: ReplayArtifactPayload,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
struct ReplayBundleInput {
    #[serde(default)]
    artifacts: Vec<ReplayArtifactInput>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use seedcore_kernel_testkit::load_replay_bundle;

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

    fn trust_bundle_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/receipts")
            .join(name)
    }

    fn token_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/tokens")
            .join(name)
    }

    fn approval_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/transfers")
            .join(name)
            .join("input.approval_envelope.json")
    }

    fn approval_history_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/approval_envelopes")
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
        let report = verify_chain_bundle(&replay_bundle_fixture("allow_chain.json"), None)
            .expect("allow replay bundle should verify");
        assert!(report.verified);
        assert_eq!(report.error_code, None);
        assert_eq!(report.artifact_reports.len(), 2);
    }

    #[test]
    fn verify_replay_bundle_fixture_with_approval_transition_chain() {
        let report = verify_chain_bundle(&replay_bundle_fixture(
            "allow_chain_with_approval_transition.json",
        ), None)
        .expect("approval transition replay bundle should verify");
        assert!(report.verified);
        assert_eq!(report.error_code, None);
        assert_eq!(report.artifact_reports.len(), 3);
        assert_eq!(
            report.artifact_reports[1].artifact_type,
            "approval_transition_history"
        );
    }

    #[test]
    fn verify_receipt_fixture() {
        let report = verify_receipt_path(&receipt_fixture("policy_receipt_artifact.json"), None, None)
            .expect("policy receipt artifact should verify");
        assert!(report.verified);
        assert_eq!(report.error_code, None);
        assert_eq!(report.artifact_type, "policy_receipt");
    }

    #[test]
    fn verify_restricted_transition_receipt_with_trust_bundle() {
        let report = verify_receipt_path(
            &receipt_fixture("restricted_transition_receipt_artifact.json"),
            Some(&trust_bundle_fixture("restricted_transition_trust_bundle.json")),
            None,
        )
        .expect("restricted transition receipt should verify with trust bundle");
        assert!(report.verified);
        assert!(report.signature_valid);
        assert!(report.artifact_hash_valid);
        assert!(report.trust_anchor_valid);
        assert!(report.attestation_valid);
        assert!(report.revocation_valid);
        assert_eq!(report.transparency_status, "anchored");
    }

    #[test]
    fn verify_restricted_transition_receipt_rejects_revoked_key() {
        let artifact: ReplayArtifact = read_json_file(receipt_fixture("restricted_transition_receipt_artifact.json"))
            .expect("restricted transition receipt fixture should load");
        let mut trust_bundle: TrustBundle =
            read_json_file(trust_bundle_fixture("restricted_transition_trust_bundle.json"))
                .expect("restricted trust bundle fixture should load");
        trust_bundle.revoked_keys.push("tpm-phase-a-key-01".to_string());
        let resolver = TrustBundleResolver::from_bundle(&trust_bundle);
        let base = verify_receipt_artifact(&artifact, &resolver);
        let report = apply_trust_bundle_checks(base, &artifact, &trust_bundle, None);
        assert!(!report.verified);
        assert_eq!(report.error_code.as_deref(), Some("revoked_signer"));
        assert!(!report.revocation_valid);
    }

    #[test]
    fn load_signed_trust_bundle_envelope() {
        let trust_bundle: TrustBundle = read_json_file(trust_bundle_fixture("restricted_transition_trust_bundle.json"))
            .expect("restricted trust bundle fixture should load");
        let payload_hash = hash_artifact(&trust_bundle).expect("bundle hash should compute");
        let envelope = SignedTrustBundleEnvelope {
            trust_bundle: trust_bundle.clone(),
            payload_hash: payload_hash.value.clone(),
            signature_envelope: SignatureEnvelope {
                signer_type: "service".to_string(),
                signer_id: "seedcore-trust-bundle-signer".to_string(),
                signing_scheme: "debug_hash_v1".to_string(),
                key_ref: Some(trust_bundle_signing_key_ref()),
                attestation_level: "baseline".to_string(),
                signature: payload_hash.to_string(),
            },
            trust_proof: None,
        };
        let temp = std::env::temp_dir().join(format!(
            "seedcore-signed-trust-bundle-{}.json",
            std::process::id()
        ));
        let rendered = serde_json::to_string(&envelope).expect("envelope should serialize");
        std::fs::write(&temp, rendered).expect("envelope fixture should write");
        let loaded = load_trust_bundle(&temp).expect("signed trust-bundle envelope should load");
        assert_eq!(loaded.version, trust_bundle.version);
        assert!(loaded.trusted_keys.contains_key("tpm-phase-a-key-01"));
        let _ = std::fs::remove_file(&temp);
    }

    #[test]
    fn seal_replay_bundle_produces_linked_verifiable_chain() {
        let bundle = load_replay_bundle(replay_bundle_fixture("allow_chain.json"))
            .expect("fixture should load");
        let input = ReplayBundleInput {
            artifacts: bundle
                .artifacts
                .into_iter()
                .map(|artifact| ReplayArtifactInput {
                    artifact_id: artifact.artifact_id,
                    payload: artifact.payload,
                })
                .collect(),
        };

        let sealed = seal_replay_bundle(input).expect("replay bundle should seal");
        assert_eq!(sealed.artifacts.len(), 2);
        assert!(sealed.artifacts[0].previous_artifact_hash.is_none());
        assert_eq!(
            sealed.artifacts[1].previous_artifact_hash.as_ref(),
            Some(&sealed.artifacts[0].artifact_hash)
        );
        let report = verify_replay_chain(&sealed, &FixtureStaticResolver);
        assert!(report.verified);
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

    #[test]
    fn summarize_transfer_fixture_maps_business_state() {
        let summary = summarize_transfer_dir(&fixture_dir("allow_case"))
            .expect("allow_case summary should be produced");
        assert!(summary.verified);
        assert_eq!(summary.business_state, "verified");
        assert_eq!(summary.disposition, "allow");
        assert_eq!(summary.approval_status, "APPROVED");
        assert!(summary.execution_token_expected);
        assert!(summary.execution_token_present);
    }

    #[test]
    fn validate_approval_fixture_succeeds() {
        let report = validate_approval_path(&approval_fixture("allow_case"))
            .expect("approval validation should execute");
        assert!(report.valid);
        assert_eq!(report.error_code, None);
    }

    #[test]
    fn approval_binding_hash_fixture_matches_expected_hash() {
        let report = approval_binding_hash_path(&approval_fixture("allow_case"))
            .expect("approval binding hash should execute");
        assert!(report.valid);
        assert_eq!(
            report.binding_hash.as_deref(),
            Some("sha256:788be3571af35b5719c93056f02f2fd839f5fadd93e18a929f2d080d8bfc67df")
        );
    }

    #[test]
    fn approval_summary_fixture_extracts_roles_binding_and_signers() {
        let report = approval_summary_path(&approval_fixture("allow_case"))
            .expect("approval summary should execute");
        assert!(report.valid);
        assert_eq!(report.status.as_deref(), Some("APPROVED"));
        assert_eq!(
            report.required_roles,
            vec![
                "FACILITY_MANAGER".to_string(),
                "QUALITY_INSPECTOR".to_string(),
            ]
        );
        assert_eq!(
            report.approved_by,
            vec![
                "principal:facility_mgr_001".to_string(),
                "principal:quality_insp_017".to_string(),
            ]
        );
        assert!(report.co_signed);
        assert_eq!(
            report.binding_hash.as_deref(),
            Some("sha256:788be3571af35b5719c93056f02f2fd839f5fadd93e18a929f2d080d8bfc67df")
        );
    }

    #[test]
    fn verify_approval_history_fixture_is_valid() {
        let report = verify_approval_history_path(&approval_history_fixture(
            "transition_history_allow.json",
        ))
        .expect("approval transition history fixture should load");
        assert!(report.valid);
        assert_eq!(report.event_count, 1);
        assert_eq!(
            report.chain_head.as_deref(),
            Some("sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72")
        );
    }

    #[test]
    fn apply_approval_transition_add_approval_advances_envelope() {
        let mut envelope: TransferApprovalEnvelope =
            read_json_file(approval_fixture("allow_case")).expect("fixture should load");
        envelope.status = ApprovalStatus::PartiallyApproved;
        if let Some(first) = envelope.required_approvals.get_mut(0) {
            first.status = ApprovalStatus::Approved;
            first.approved_at = Some(Timestamp::from_str("2026-04-02T08:00:01Z").unwrap());
        }
        if let Some(second) = envelope.required_approvals.get_mut(1) {
            second.status = ApprovalStatus::Pending;
            second.approved_at = None;
        }
        envelope.approval_binding_hash = None;
        envelope.version = 1;

        let report = apply_approval_transition(
            envelope,
            ApprovalTransitionInput::AddApproval {
                role: "QUALITY_INSPECTOR".to_string(),
                principal_ref: "principal:quality_insp_017".to_string(),
                approval_ref: "approval:quality_insp_017".to_string(),
                approved_at: Some(Timestamp::from_str("2026-04-02T08:00:30Z").unwrap()),
            },
            ApprovalTransitionHistory::default(),
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        );

        assert!(report.valid);
        let updated = report
            .approval_envelope
            .expect("updated envelope should be present");
        assert_eq!(updated.status, ApprovalStatus::Approved);
        assert_eq!(updated.version, 2);
        assert!(report.binding_hash.is_some());
        assert!(report.transition_event.is_some());
        let history = report.history.expect("history should be present");
        assert_eq!(history.events.len(), 1);
        assert_eq!(
            history.chain_head,
            report.transition_event.map(|event| event.event_hash)
        );
    }

    #[test]
    fn verify_approval_history_accepts_generated_chain_and_rejects_tamper() {
        let mut envelope: TransferApprovalEnvelope =
            read_json_file(approval_fixture("allow_case")).expect("fixture should load");
        envelope.status = ApprovalStatus::PartiallyApproved;
        if let Some(second) = envelope.required_approvals.get_mut(1) {
            second.status = ApprovalStatus::Pending;
            second.approved_at = None;
        }
        envelope.approval_binding_hash = None;
        envelope.version = 1;

        let report = apply_approval_transition(
            envelope,
            ApprovalTransitionInput::AddApproval {
                role: "QUALITY_INSPECTOR".to_string(),
                principal_ref: "principal:quality_insp_017".to_string(),
                approval_ref: "approval:quality_insp_017".to_string(),
                approved_at: Some(Timestamp::from_str("2026-04-02T08:00:30Z").unwrap()),
            },
            ApprovalTransitionHistory::default(),
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        );
        assert!(report.valid);
        let history = report.history.expect("history should be present");

        let summary = verify_approval_history_path_from_value(&history);
        assert!(summary.valid);
        assert_eq!(summary.event_count, 1);
        assert_eq!(summary.chain_head, history.chain_head);

        let mut tampered = history.clone();
        tampered.events[0].next_status = "PENDING".to_string();
        let tampered_summary = verify_approval_history_path_from_value(&tampered);
        assert!(!tampered_summary.valid);
        assert_eq!(
            tampered_summary.error_code.as_deref(),
            Some("approval_transition_history_invalid")
        );
    }
}
