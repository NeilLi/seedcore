use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use seedcore_kernel_testkit::{FixtureDebugSigner, FixtureStaticResolver};
use seedcore_kernel_types::{
    ApprovalTransitionEvent, ApprovalTransitionHistory, ArtifactHash, EvidenceBundle,
    ReplayArtifactPayload, SignatureEnvelope, Timestamp,
};
use seedcore_proof_core::{
    hash_artifact, replay_artifact_source_hash, verify_detached_signature, verify_replay_chain,
    ReplayArtifact, ReplayBundle, ReplayVerificationReport, VerificationReport,
};
use seedcore_token_core::{mint_token, ExecutionToken, ExecutionTokenClaims};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ReplayArtifactInput {
    artifact_id: String,
    #[serde(flatten)]
    payload: ReplayArtifactPayload,
    #[serde(default)]
    source_artifact_hash: Option<ArtifactHash>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
struct ReplayBundleInput {
    #[serde(default)]
    artifacts: Vec<ReplayArtifactInput>,
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

fn verify_chain_inner(bundle: ReplayBundle) -> ReplayVerificationReport {
    let mut report = verify_replay_chain(&bundle, &FixtureStaticResolver);
    for (index, artifact) in bundle.artifacts.iter().enumerate() {
        report.artifact_reports[index] = apply_post_verification_checks(
            report.artifact_reports[index].clone(),
            artifact,
            &FixtureStaticResolver,
        );
    }
    report.verified = report.artifact_reports.iter().all(|item| item.verified)
        && report.error_code.is_none()
        && report
            .chain_checks
            .iter()
            .all(|item| !item.contains("mismatch"));
    if !report.verified && report.error_code.is_none() {
        report.error_code = report
            .artifact_reports
            .iter()
            .find_map(|item| item.error_code.clone())
            .or_else(|| Some("replay_artifact_verification_failed".to_string()));
    }
    report
}

fn apply_post_verification_checks(
    mut report: VerificationReport,
    artifact: &ReplayArtifact,
    resolver: &dyn seedcore_proof_core::KeyResolver,
) -> VerificationReport {
    if !report.verified {
        return report;
    }
    if let ReplayArtifactPayload::EvidenceBundle(bundle) = &artifact.payload {
        if let Err(error_code) = verify_evidence_bundle_cosignatures(bundle, resolver) {
            report.verified = false;
            report.error_code = Some(error_code);
            return report;
        }
    }
    report
}

fn verify_evidence_bundle_cosignatures(
    bundle: &EvidenceBundle,
    resolver: &dyn seedcore_proof_core::KeyResolver,
) -> Result<(), String> {
    if !bundle.co_sign_required && bundle.co_signatures.is_empty() {
        return Ok(());
    }
    let Some(binding_hash) = bundle.co_sign_binding_hash.as_ref() else {
        return Err("missing_co_sign_binding_hash".to_string());
    };

    let mut seen_principals = std::collections::BTreeSet::new();
    for co_signature in &bundle.co_signatures {
        if !seen_principals.insert(co_signature.principal_ref.clone()) {
            return Err("duplicate_co_signer".to_string());
        }
        let report = verify_detached_signature(
            &co_signature.signature,
            binding_hash,
            "evidence_bundle_co_sign",
            resolver,
        );
        if !report.verified {
            return Err(report
                .error_code
                .unwrap_or_else(|| "co_sign_signature_invalid".to_string()));
        }
    }

    let outcome = bundle
        .transfer_outcome
        .as_deref()
        .unwrap_or_default()
        .to_ascii_uppercase();
    let status = bundle
        .co_sign_status
        .as_deref()
        .unwrap_or_default()
        .to_ascii_lowercase();
    if outcome == "EMERGENCY_OVERRIDE" || status == "emergency_override" {
        if bundle.co_signatures.is_empty() {
            return Err("missing_emergency_override_signature".to_string());
        }
        let has_zone_admin = bundle.co_signatures.iter().any(|item| {
            let role = item.signer_role.to_ascii_uppercase();
            role == "ZONE_ADMIN" || role == "ZONE_ADMINISTRATOR"
        });
        if !has_zone_admin {
            return Err("missing_zone_admin_override_signature".to_string());
        }
        return Ok(());
    }

    if bundle.co_sign_required {
        if bundle.co_signatures.len() < 2 {
            return Err("missing_co_signatures".to_string());
        }
        for expected in &bundle.expected_co_signers {
            if !bundle
                .co_signatures
                .iter()
                .any(|item| item.principal_ref == expected.principal_ref)
            {
                return Err("co_signer_mismatch".to_string());
            }
        }
    }
    Ok(())
}

fn materialize_replay_bundle_inner(input: ReplayBundleInput) -> Result<ReplayBundle, String> {
    if input.artifacts.is_empty() {
        return Err("empty_replay_bundle_input".to_string());
    }

    let mut previous_hash: Option<ArtifactHash> = None;
    let mut materialized = Vec::with_capacity(input.artifacts.len());
    for item in input.artifacts {
        let source_artifact_hash = match item.source_artifact_hash {
            Some(value) => Some(value),
            None => replay_artifact_source_hash(&item.payload)
                .map_err(|error| format!("replay_hash_failed:{error}"))?,
        };
        let artifact_hash = match source_artifact_hash.as_ref() {
            Some(value) => value.clone(),
            None => hash_artifact(&item.payload)
                .map_err(|error| format!("replay_hash_failed:{error}"))?,
        };
        let signature = replay_signature_for_payload(&item.payload)?;
        materialized.push(ReplayArtifact {
            artifact_id: item.artifact_id,
            payload: item.payload,
            artifact_hash: artifact_hash.clone(),
            source_artifact_hash,
            signature,
            previous_artifact_hash: previous_hash.clone(),
        });
        previous_hash = Some(artifact_hash);
    }
    Ok(ReplayBundle {
        artifacts: materialized,
    })
}

fn replay_signature_for_payload(
    payload: &ReplayArtifactPayload,
) -> Result<SignatureEnvelope, String> {
    match payload {
        ReplayArtifactPayload::ExecutionToken(token) => {
            Ok(normalize_replay_signature(token.signature.clone(), None))
        }
        ReplayArtifactPayload::PolicyReceipt(receipt) => Ok(normalize_replay_signature(
            receipt.signer.clone(),
            receipt
                .trust_proof
                .as_ref()
                .map(|proof| proof.key_ref.as_str()),
        )),
        ReplayArtifactPayload::TransitionReceipt(receipt) => Ok(normalize_replay_signature(
            receipt.signer.clone(),
            receipt
                .trust_proof
                .as_ref()
                .map(|proof| proof.key_ref.as_str()),
        )),
        ReplayArtifactPayload::EvidenceBundle(bundle) => Ok(normalize_replay_signature(
            bundle.signer.clone(),
            bundle
                .trust_proof
                .as_ref()
                .map(|proof| proof.key_ref.as_str()),
        )),
        ReplayArtifactPayload::ActionIntent(_)
        | ReplayArtifactPayload::TransferApprovalEnvelope(_)
        | ReplayArtifactPayload::PolicyDecision(_)
        | ReplayArtifactPayload::ApprovalTransitionHistory(_) => {
            Err("unsupported_unsigned_replay_artifact".to_string())
        }
    }
}

fn normalize_replay_signature(
    mut signature: SignatureEnvelope,
    trust_key_ref: Option<&str>,
) -> SignatureEnvelope {
    if signature.key_ref.is_none() {
        if let Some(key_ref) = trust_key_ref.filter(|value| !value.trim().is_empty()) {
            signature.key_ref = Some(key_ref.to_string());
        } else if signature.signing_scheme == "hmac_sha256"
            && !signature.signer_id.trim().is_empty()
        {
            signature.key_ref = Some(format!("legacy-hmac:{}", signature.signer_id.trim()));
        }
    }
    signature
}

fn verify_approval_history_inner(
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
        .map(|hash| format!("{}:{}", hash.algorithm, hash.value))
}

fn parse_json<T: for<'de> Deserialize<'de>>(raw: &str) -> Result<T, PyErr> {
    serde_json::from_str(raw).map_err(|error| PyValueError::new_err(error.to_string()))
}

fn to_json<T: Serialize>(value: &T) -> Result<String, PyErr> {
    serde_json::to_string(value).map_err(|error| PyValueError::new_err(error.to_string()))
}

fn trust_bundle_enabled() -> bool {
    std::env::var("SEEDCORE_VERIFY_TRUST_BUNDLE")
        .ok()
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false)
}

#[pyfunction]
fn verify_chain(bundle_json: &str) -> PyResult<String> {
    if trust_bundle_enabled() {
        return Err(PyValueError::new_err(
            "trust_bundle_mode_requires_cli_fallback",
        ));
    }
    let bundle: ReplayBundle = parse_json(bundle_json)?;
    let report = verify_chain_inner(bundle);
    to_json(&report)
}

#[pyfunction]
fn materialize_replay_bundle(input_json: &str) -> PyResult<String> {
    let input: ReplayBundleInput = parse_json(input_json)?;
    let bundle = materialize_replay_bundle_inner(input).map_err(PyValueError::new_err)?;
    to_json(&bundle)
}

#[pyfunction]
fn mint_execution_token(claims_json: &str) -> PyResult<String> {
    let claims: ExecutionTokenClaims = parse_json(claims_json)?;
    let token: ExecutionToken = mint_token(claims, &FixtureDebugSigner)
        .map_err(|error| PyValueError::new_err(error.to_string()))?;
    to_json(&token)
}

#[pyfunction]
fn verify_approval_history(history_json: &str) -> PyResult<String> {
    let history: ApprovalTransitionHistory = parse_json(history_json)?;
    let report = verify_approval_history_inner(&history);
    to_json(&report)
}

#[pymodule]
fn seedcore_proof_py(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(verify_chain, module)?)?;
    module.add_function(wrap_pyfunction!(materialize_replay_bundle, module)?)?;
    module.add_function(wrap_pyfunction!(mint_execution_token, module)?)?;
    module.add_function(wrap_pyfunction!(verify_approval_history, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use seedcore_kernel_testkit::load_replay_bundle;
    use std::path::PathBuf;
    use std::str::FromStr;

    fn replay_bundle_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/replay_bundles")
            .join(name)
    }

    #[test]
    fn verify_chain_accepts_valid_fixture_bundle() {
        let bundle = load_replay_bundle(&replay_bundle_fixture("allow_case.replay_bundle.json"))
            .expect("bundle should load");
        let report = verify_chain_inner(bundle);
        assert!(report.verified);
    }

    #[test]
    fn verify_approval_history_detects_hash_mismatch() {
        let mut history = ApprovalTransitionHistory {
            chain_head: Some("sha256:bad".to_string()),
            events: vec![],
        };
        let report = verify_approval_history_inner(&history);
        assert!(!report.valid);
        assert_eq!(
            report.error_code.as_deref(),
            Some("approval_transition_history_invalid")
        );

        history.chain_head = None;
        let valid_report = verify_approval_history_inner(&history);
        assert!(valid_report.valid);
    }

    #[test]
    fn materialize_replay_bundle_errors_on_empty_input() {
        let report = materialize_replay_bundle_inner(ReplayBundleInput { artifacts: vec![] });
        assert!(matches!(report, Err(error) if error == "empty_replay_bundle_input"));
    }

    #[test]
    fn trust_bundle_flag_blocks_bridge_chain_verification() {
        std::env::set_var("SEEDCORE_VERIFY_TRUST_BUNDLE", "fixtures/example.json");
        let response = verify_chain("{\"artifacts\":[]}");
        assert!(response.is_err());
        std::env::remove_var("SEEDCORE_VERIFY_TRUST_BUNDLE");
    }

    #[test]
    fn mint_execution_token_rejects_invalid_payload() {
        let response = mint_execution_token("{\"token_id\":\"missing_required_fields\"}");
        assert!(response.is_err());
    }

    #[test]
    fn parse_timestamp_material_is_stable() {
        let parsed = Timestamp::from_str("2026-04-02T08:00:30Z").expect("timestamp should parse");
        let material = ApprovalTransitionEventHashMaterial {
            previous_event_hash: None,
            occurred_at: parsed,
            transition_type: "add_approval".to_string(),
            envelope_id: "env-1".to_string(),
            previous_status: "PENDING".to_string(),
            next_status: "APPROVED".to_string(),
            previous_binding_hash: None,
            next_binding_hash: Some("sha256:abc".to_string()),
            envelope_version: 1,
        };
        let hash = hash_artifact(&material).expect("hash should render");
        assert_eq!(hash.algorithm, "sha256");
    }
}
