use base64::Engine;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use seedcore_kernel_testkit::{FixtureDebugSigner, FixtureStaticResolver};
use seedcore_kernel_types::{
    ApprovalTransitionEvent, ApprovalTransitionHistory, ArtifactHash, EvidenceBundle,
    ReplayArtifactPayload, SignatureEnvelope, Timestamp, TransitionReceipt, TrustBundle,
    TrustProof,
};
use seedcore_proof_core::{
    hash_artifact, replay_artifact_source_hash, verify_detached_signature, verify_replay_chain,
    ReplayArtifact, ReplayBundle, ReplayVerificationReport, VerificationReport,
};
use seedcore_token_core::{mint_token, ExecutionToken, ExecutionTokenClaims};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

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
struct VerifyChainBridgeInput {
    bundle: ReplayBundle,
    #[serde(default)]
    trust_bundle_path: Option<String>,
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
struct SignedTrustBundleEnvelope {
    trust_bundle: TrustBundle,
    payload_hash: String,
    signature_envelope: SignatureEnvelope,
    #[serde(default)]
    trust_proof: Option<TrustProof>,
}

#[derive(Debug, Clone)]
struct TrustBundleResolver {
    bundle: TrustBundle,
}

impl TrustBundleResolver {
    fn from_bundle(bundle: &TrustBundle) -> Self {
        Self {
            bundle: bundle.clone(),
        }
    }
}

impl seedcore_proof_core::KeyResolver for TrustBundleResolver {
    fn resolve(
        &self,
        key_ref: &str,
    ) -> Result<seedcore_proof_core::KeyMaterial, seedcore_proof_core::VerificationError> {
        if let Some(entry) = self.bundle.trusted_keys.get(key_ref) {
            let mut metadata = entry.metadata.clone();
            metadata.insert("key_algorithm".to_string(), entry.key_algorithm.clone());
            metadata.insert(
                "trust_anchor_type".to_string(),
                entry.trust_anchor_type.clone(),
            );
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct TpmQuoteEnvelope {
    format: String,
    message_b64: String,
    signature_b64: String,
    #[serde(default)]
    nonce: Option<String>,
    #[serde(default)]
    pcr_digest: Option<String>,
}

fn parse_json<T: for<'de> Deserialize<'de>>(raw: &str) -> Result<T, PyErr> {
    serde_json::from_str(raw).map_err(|error| PyValueError::new_err(error.to_string()))
}

fn to_json<T: Serialize>(value: &T) -> Result<String, PyErr> {
    serde_json::to_string(value).map_err(|error| PyValueError::new_err(error.to_string()))
}

fn decode_verify_chain_input(raw: &str) -> Result<(ReplayBundle, Option<String>), PyErr> {
    let value: Value = parse_json(raw)?;
    if value.get("bundle").is_some() {
        let input: VerifyChainBridgeInput = serde_json::from_value(value)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        return Ok((input.bundle, input.trust_bundle_path));
    }
    let bundle: ReplayBundle =
        serde_json::from_value(value).map_err(|error| PyValueError::new_err(error.to_string()))?;
    Ok((bundle, None))
}

fn resolve_trust_bundle_path(explicit_path: Option<&str>) -> Option<PathBuf> {
    let configured = explicit_path
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .or_else(|| {
            env::var("SEEDCORE_VERIFY_TRUST_BUNDLE")
                .ok()
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
        })?;
    let candidate = PathBuf::from(configured);
    if candidate.is_absolute() {
        return Some(candidate);
    }
    std::env::current_dir().ok().map(|cwd| cwd.join(candidate))
}

fn verify_chain_inner(
    bundle: ReplayBundle,
    trust_bundle: Option<&TrustBundle>,
) -> ReplayVerificationReport {
    if let Some(bundle_trust) = trust_bundle {
        let resolver = TrustBundleResolver::from_bundle(bundle_trust);
        let mut report = verify_replay_chain(&bundle, &resolver);
        for (index, artifact) in bundle.artifacts.iter().enumerate() {
            let previous_transition = previous_transition_receipt(&bundle, index);
            let checked = apply_trust_bundle_checks(
                report.artifact_reports[index].clone(),
                artifact,
                bundle_trust,
                previous_transition,
            );
            report.artifact_reports[index] =
                apply_post_verification_checks(checked, artifact, &resolver);
        }
        return finalize_replay_report(report);
    }

    let mut report = verify_replay_chain(&bundle, &FixtureStaticResolver);
    for (index, artifact) in bundle.artifacts.iter().enumerate() {
        report.artifact_reports[index] = apply_post_verification_checks(
            report.artifact_reports[index].clone(),
            artifact,
            &FixtureStaticResolver,
        );
    }
    finalize_replay_report(report)
}

fn finalize_replay_report(mut report: ReplayVerificationReport) -> ReplayVerificationReport {
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
    report.trust_anchor_status = if report.trust_anchor_valid {
        "valid".to_string()
    } else {
        "invalid".to_string()
    };
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
    report.attestation_status = if report.attestation_valid {
        "valid".to_string()
    } else {
        "invalid".to_string()
    };
    if !report.attestation_valid {
        report.verified = false;
        report.error_code = Some("missing_attestation_binding".to_string());
        return report;
    }
    if should_enforce_strict_tpm_attestation(trust_bundle, trust_proof) {
        if let Err(error_code) = verify_tpm_attestation_cryptography(trust_proof) {
            report.verified = false;
            report.attestation_valid = false;
            report.attestation_status = "invalid".to_string();
            report.error_code = Some(error_code);
            return report;
        }
    }

    report.revocation_valid = !is_trust_proof_revoked(trust_proof, artifact, trust_bundle);
    report.revocation_status = if report.revocation_valid {
        "valid".to_string()
    } else {
        "invalid".to_string()
    };
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
    if let Err(error_code) = verify_transparency_proof_requirements(trust_bundle, trust_proof) {
        report.verified = false;
        report.error_code = Some(error_code);
        return report;
    }
    if report.transparency_status == "anchor_verification_failed" {
        report.verified = false;
        report.error_code = Some("anchor_verification_failed".to_string());
        return report;
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
        if matches!(
            candidate.payload,
            ReplayArtifactPayload::TransitionReceipt(_)
        ) {
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
    if trust_bundle
        .revoked_keys
        .iter()
        .any(|item| item == &trust_proof.key_ref)
    {
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
    if let ReplayArtifactPayload::TransitionReceipt(TransitionReceipt { endpoint_id, .. }) =
        &artifact.payload
    {
        if trust_bundle
            .revoked_nodes
            .iter()
            .any(|item| item == endpoint_id)
        {
            return true;
        }
    }
    false
}

fn should_enforce_strict_tpm_attestation(
    trust_bundle: &TrustBundle,
    trust_proof: &TrustProof,
) -> bool {
    if trust_proof.trust_anchor_type != "tpm2" {
        return false;
    }
    if env_flag("SEEDCORE_REQUIRE_TPM_ATTESTATION_CRYPTO", false) {
        return true;
    }
    matches!(
        trust_bundle
            .metadata
            .get("attestation_validation_mode")
            .map(|value| value.as_str()),
        Some("strict_tpm_v1") | Some("strict")
    )
}

fn verify_tpm_attestation_cryptography(trust_proof: &TrustProof) -> Result<(), String> {
    let key_binding = trust_proof
        .key_binding
        .as_ref()
        .ok_or_else(|| "missing_key_binding".to_string())?;
    let attestation = trust_proof
        .attestation
        .as_ref()
        .ok_or_else(|| "missing_attestation_binding".to_string())?;
    let quote_raw = attestation
        .quote
        .as_deref()
        .ok_or_else(|| "missing_tpm_quote".to_string())?;
    let quote: TpmQuoteEnvelope =
        serde_json::from_str(quote_raw).map_err(|_| "invalid_tpm_quote_format".to_string())?;
    if quote.format != "seedcore_tpm_quote_v1" {
        return Err("invalid_tpm_quote_format".to_string());
    }
    let nonce = quote.nonce.as_deref().unwrap_or("").trim();
    let expected_nonce = trust_proof
        .replay
        .as_ref()
        .and_then(|item| item.receipt_nonce.as_deref())
        .unwrap_or("")
        .trim();
    if !nonce.is_empty() && !expected_nonce.is_empty() && nonce != expected_nonce {
        return Err("tpm_quote_nonce_mismatch".to_string());
    }

    let ak_cert_raw = key_binding
        .certificate_chain
        .first()
        .ok_or_else(|| "missing_ak_certificate".to_string())?;
    let ak_cert_pem = normalize_certificate_pem(ak_cert_raw)
        .ok_or_else(|| "invalid_ak_certificate".to_string())?;
    let endorsement_pems = attestation
        .endorsement_chain
        .iter()
        .filter_map(|item| normalize_certificate_pem(item))
        .collect::<Vec<_>>();
    if endorsement_pems.is_empty() {
        return Err("missing_endorsement_chain".to_string());
    }
    if !verify_certificate_chain(&ak_cert_pem, &endorsement_pems) {
        return Err("endorsement_chain_invalid".to_string());
    }

    let quote_bytes = base64::engine::general_purpose::STANDARD
        .decode(quote.message_b64.as_bytes())
        .map_err(|_| "invalid_tpm_quote_message".to_string())?;
    let signature_bytes = base64::engine::general_purpose::STANDARD
        .decode(quote.signature_b64.as_bytes())
        .map_err(|_| "invalid_tpm_quote_signature".to_string())?;
    if !verify_quote_signature_with_ak_cert(&ak_cert_pem, &quote_bytes, &signature_bytes) {
        return Err("tpm_quote_signature_invalid".to_string());
    }
    Ok(())
}

fn verify_transparency_proof_requirements(
    trust_bundle: &TrustBundle,
    trust_proof: &TrustProof,
) -> Result<(), String> {
    let Some(config) = trust_bundle.transparency.as_ref() else {
        return Ok(());
    };
    if !config.enabled {
        return Ok(());
    }
    let Some(transparency) = trust_proof.transparency.as_ref() else {
        return Err("missing_transparency_proof".to_string());
    };
    if transparency.status != "anchored" {
        return Err("missing_transparency_anchor".to_string());
    }
    if let Some(expected_log_url) = config.log_url.as_deref() {
        if transparency.log_url.as_deref() != Some(expected_log_url) {
            return Err("transparency_log_mismatch".to_string());
        }
    }
    if transparency
        .entry_id
        .as_deref()
        .unwrap_or("")
        .trim()
        .is_empty()
    {
        return Err("missing_transparency_entry".to_string());
    }
    if transparency
        .proof_hash
        .as_deref()
        .unwrap_or("")
        .trim()
        .is_empty()
    {
        return Err("missing_transparency_proof_hash".to_string());
    }
    Ok(())
}

fn normalize_certificate_pem(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed.contains("BEGIN CERTIFICATE") {
        return Some(trimmed.to_string());
    }
    let der = base64::engine::general_purpose::STANDARD
        .decode(trimmed.as_bytes())
        .ok()?;
    let body = base64::engine::general_purpose::STANDARD.encode(der);
    let mut pem = String::from("-----BEGIN CERTIFICATE-----\n");
    for chunk in body.as_bytes().chunks(64) {
        let line = std::str::from_utf8(chunk).ok()?;
        pem.push_str(line);
        pem.push('\n');
    }
    pem.push_str("-----END CERTIFICATE-----\n");
    Some(pem)
}

fn verify_certificate_chain(leaf_pem: &str, chain_pems: &[String]) -> bool {
    let root_pem = match chain_pems.last() {
        Some(value) => value,
        None => return false,
    };
    let temp_root = write_temp_file("seedcore-tpm-root", root_pem.as_bytes());
    let temp_leaf = write_temp_file("seedcore-tpm-leaf", leaf_pem.as_bytes());
    let intermediates = &chain_pems[..chain_pems.len().saturating_sub(1)];
    let mut result = false;
    let temp_chain = if intermediates.is_empty() {
        None
    } else {
        let joined = intermediates.join("\n");
        write_temp_file("seedcore-tpm-chain", joined.as_bytes())
    };
    if let (Some(root_path), Some(leaf_path)) = (temp_root.as_ref(), temp_leaf.as_ref()) {
        let mut command = Command::new("openssl");
        command
            .arg("verify")
            .arg("-CAfile")
            .arg(root_path.as_path());
        if let Some(chain_path) = temp_chain.as_ref() {
            command.arg("-untrusted").arg(chain_path.as_path());
        }
        command.arg(leaf_path.as_path());
        if let Ok(completed) = command.output() {
            result = completed.status.success();
        }
    }
    cleanup_temp_files(&[temp_root, temp_leaf, temp_chain]);
    result
}

fn verify_quote_signature_with_ak_cert(
    ak_cert_pem: &str,
    quote_message: &[u8],
    signature: &[u8],
) -> bool {
    let temp_cert = write_temp_file("seedcore-tpm-ak-cert", ak_cert_pem.as_bytes());
    let temp_pubkey = write_temp_file("seedcore-tpm-ak-pub", b"");
    let temp_message = write_temp_file("seedcore-tpm-quote-msg", quote_message);
    let temp_signature = write_temp_file("seedcore-tpm-quote-sig", signature);
    let mut verified = false;
    if let (Some(cert_path), Some(pubkey_path), Some(message_path), Some(signature_path)) = (
        temp_cert.as_ref(),
        temp_pubkey.as_ref(),
        temp_message.as_ref(),
        temp_signature.as_ref(),
    ) {
        if let Ok(extract) = Command::new("openssl")
            .arg("x509")
            .arg("-in")
            .arg(cert_path.as_path())
            .arg("-pubkey")
            .arg("-noout")
            .output()
        {
            if extract.status.success() && fs::write(pubkey_path, extract.stdout).is_ok() {
                if let Ok(check) = Command::new("openssl")
                    .arg("dgst")
                    .arg("-sha256")
                    .arg("-verify")
                    .arg(pubkey_path.as_path())
                    .arg("-signature")
                    .arg(signature_path.as_path())
                    .arg(message_path.as_path())
                    .output()
                {
                    verified = check.status.success();
                }
            }
        }
    }
    cleanup_temp_files(&[temp_cert, temp_pubkey, temp_message, temp_signature]);
    verified
}

fn write_temp_file(prefix: &str, bytes: &[u8]) -> Option<PathBuf> {
    let path = std::env::temp_dir().join(format!(
        "{prefix}-{}-{}.bin",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()?
            .as_nanos()
    ));
    fs::write(&path, bytes).ok()?;
    Some(path)
}

fn cleanup_temp_files(paths: &[Option<PathBuf>]) {
    for path in paths {
        if let Some(item) = path {
            let _ = fs::remove_file(item);
        }
    }
}

fn env_flag(name: &str, default: bool) -> bool {
    let fallback = if default { "true" } else { "false" };
    let value = env::var(name).unwrap_or_else(|_| fallback.to_string());
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
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
            report
                .error_code
                .unwrap_or_else(|| "signature_invalid".to_string()),
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

#[pyfunction]
fn verify_chain(bundle_json: &str) -> PyResult<String> {
    let (bundle, explicit_trust_path) = decode_verify_chain_input(bundle_json)?;
    let trust_bundle = match resolve_trust_bundle_path(explicit_trust_path.as_deref()) {
        Some(path) => Some(load_trust_bundle(&path).map_err(PyValueError::new_err)?),
        None => None,
    };
    let report = verify_chain_inner(bundle, trust_bundle.as_ref());
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

    fn receipt_fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/receipts")
            .join(name)
    }

    #[test]
    fn verify_chain_accepts_valid_fixture_bundle() {
        let bundle = load_replay_bundle(&replay_bundle_fixture("allow_case.replay_bundle.json"))
            .expect("bundle should load");
        let report = verify_chain_inner(bundle, None);
        assert!(report.verified);
    }

    #[test]
    fn verify_chain_accepts_wrapped_bridge_payload() {
        let bundle = load_replay_bundle(&replay_bundle_fixture("allow_case.replay_bundle.json"))
            .expect("bundle should load");
        let wrapped = serde_json::json!({ "bundle": bundle });
        let rendered = serde_json::to_string(&wrapped).expect("wrapped bundle should serialize");
        let response = verify_chain(&rendered).expect("verify_chain should succeed");
        let report: ReplayVerificationReport =
            serde_json::from_str(&response).expect("report should deserialize");
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
    fn trust_bundle_env_path_is_used_by_verify_chain() {
        std::env::set_var(
            "SEEDCORE_VERIFY_TRUST_BUNDLE",
            receipt_fixture("restricted_transition_trust_bundle.json"),
        );
        let artifact: ReplayArtifact = serde_json::from_str(
            &std::fs::read_to_string(receipt_fixture(
                "restricted_transition_receipt_artifact.json",
            ))
            .expect("receipt fixture should load"),
        )
        .expect("receipt artifact should parse");
        let bundle = ReplayBundle {
            artifacts: vec![artifact],
        };
        let rendered = serde_json::to_string(&bundle).expect("bundle should serialize");
        let response =
            verify_chain(&rendered).expect("verify_chain should succeed with trust bundle");
        let report: ReplayVerificationReport =
            serde_json::from_str(&response).expect("report should deserialize");
        assert!(report.verified);
        std::env::remove_var("SEEDCORE_VERIFY_TRUST_BUNDLE");
    }

    #[test]
    fn verify_chain_reports_bad_trust_bundle_path() {
        let payload = r#"{"bundle":{"artifacts":[]},"trust_bundle_path":"./does-not-exist.json"}"#;
        let response = verify_chain(payload);
        assert!(response.is_err());
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
