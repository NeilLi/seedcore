//! Proof integrity kernel for SeedCore.
//!
//! This crate will own canonical serialization, hashing, signing abstractions,
//! artifact verification, and replay-chain verification.

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

pub use seedcore_kernel_types::{
    ArtifactHash, Placeholder as KernelPlaceholder, ReplayArtifact, ReplayArtifactPayload,
    ReplayBundle, SignatureEnvelope, TrustBundle, TrustBundleKey, TrustProof,
};

/// Error raised when an artifact cannot be canonicalized deterministically.
#[derive(Debug, Error)]
pub enum CanonicalizationError {
    #[error("artifact_serialization_failed")]
    Serialization(#[from] serde_json::Error),
}

/// Error raised when signing fails.
#[derive(Debug, Error)]
pub enum SigningError {
    #[error("signer_rejected_hash")]
    SignerRejected,
}

/// Error raised during key resolution or signature verification.
#[derive(Debug, Error)]
pub enum VerificationError {
    #[error("missing_key_ref")]
    MissingKeyRef,
    #[error("key_not_found")]
    KeyNotFound,
    #[error("unsupported_signing_scheme")]
    UnsupportedSigningScheme,
    #[error("invalid_key_material")]
    InvalidKeyMaterial,
}

/// Top-level proof-core error.
#[derive(Debug, Error)]
pub enum ProofError {
    #[error(transparent)]
    Canonicalization(#[from] CanonicalizationError),
    #[error(transparent)]
    Signing(#[from] SigningError),
}

/// Deterministically serializable artifact.
pub trait CanonicalArtifact: Serialize {
    fn canonical_bytes(&self) -> Result<Vec<u8>, CanonicalizationError> {
        canonical_json_bytes(self)
    }
}

impl<T> CanonicalArtifact for T where T: Serialize {}

/// Minimal signer abstraction for the proof kernel.
pub trait Signer {
    fn sign_hash(&self, hash: &ArtifactHash) -> Result<SignatureEnvelope, SigningError>;
}

/// Minimal key material returned by a resolver.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyMaterial {
    pub key_ref: String,
    pub public_material: String,
    pub metadata: BTreeMap<String, String>,
}

/// Resolves verification material from a key reference.
pub trait KeyResolver {
    fn resolve(&self, key_ref: &str) -> Result<KeyMaterial, VerificationError>;
}

/// Signed artifact wrapper that binds the artifact, its hash, and signature.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedArtifact<T> {
    pub artifact: T,
    pub artifact_hash: ArtifactHash,
    pub signature: SignatureEnvelope,
}

/// Machine-readable verification result for a single artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VerificationReport {
    pub verified: bool,
    pub artifact_type: String,
    pub error_code: Option<String>,
    pub details: Vec<String>,
    pub signature_valid: bool,
    pub artifact_hash_valid: bool,
    pub trust_anchor_valid: bool,
    pub attestation_valid: bool,
    pub revocation_valid: bool,
    pub replay_status: String,
    pub transparency_status: String,
}

/// Machine-readable report for replay-chain verification.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplayVerificationReport {
    pub verified: bool,
    pub error_code: Option<String>,
    pub artifact_reports: Vec<VerificationReport>,
    pub chain_checks: Vec<String>,
}

/// Deterministic canonicalization helper.
pub fn canonicalize<T: CanonicalArtifact>(artifact: &T) -> Result<Vec<u8>, CanonicalizationError> {
    artifact.canonical_bytes()
}

/// Deterministic SHA-256 hashing helper.
pub fn hash_artifact<T: CanonicalArtifact>(
    artifact: &T,
) -> Result<ArtifactHash, CanonicalizationError> {
    let bytes = canonicalize(artifact)?;
    let digest = Sha256::digest(bytes);
    Ok(ArtifactHash::sha256_hex(hex::encode(digest)))
}

/// Signs an artifact by first hashing its canonical form.
pub fn sign_artifact<T: CanonicalArtifact>(
    artifact: T,
    signer: &dyn Signer,
) -> Result<SignedArtifact<T>, ProofError> {
    let artifact_hash = hash_artifact(&artifact)?;
    let signature = signer.sign_hash(&artifact_hash)?;
    Ok(SignedArtifact {
        artifact,
        artifact_hash,
        signature,
    })
}

/// Verifies the hash and scaffold-level signature semantics for an artifact.
///
/// Current behavior:
/// - recomputes the canonical artifact hash
/// - requires a `key_ref`
/// - resolves key material through the supplied resolver
/// - supports the scaffold signing scheme `debug_hash_v1`, where the signature
///   must equal the artifact hash string
pub fn verify_signed_artifact<T: CanonicalArtifact>(
    artifact: &SignedArtifact<T>,
    resolver: &dyn KeyResolver,
) -> VerificationReport {
    let computed_hash = match hash_artifact(&artifact.artifact) {
        Ok(hash) => hash,
        Err(error) => {
            return VerificationReport {
                verified: false,
                artifact_type: std::any::type_name::<T>().to_string(),
                error_code: Some("canonicalization_failed".to_string()),
                details: vec![error.to_string()],
                signature_valid: false,
                artifact_hash_valid: false,
                trust_anchor_valid: false,
                attestation_valid: false,
                revocation_valid: false,
                replay_status: "not_proven_offline".to_string(),
                transparency_status: "not_configured".to_string(),
            };
        }
    };

    if computed_hash != artifact.artifact_hash {
        return VerificationReport {
            verified: false,
            artifact_type: std::any::type_name::<T>().to_string(),
            error_code: Some("artifact_hash_mismatch".to_string()),
            details: vec![
                format!("expected={}", artifact.artifact_hash),
                format!("computed={}", computed_hash),
            ],
            signature_valid: false,
            artifact_hash_valid: false,
            trust_anchor_valid: false,
            attestation_valid: false,
            revocation_valid: false,
            replay_status: "not_proven_offline".to_string(),
            transparency_status: "not_configured".to_string(),
        };
    }

    verify_signature_envelope(
        &artifact.signature,
        &artifact.artifact_hash,
        std::any::type_name::<T>().to_string(),
        resolver,
    )
}

/// Verifies a replay bundle by validating each artifact hash/signature and
/// asserting previous-hash linkage across the bundle sequence.
pub fn verify_replay_chain(
    bundle: &ReplayBundle,
    resolver: &dyn KeyResolver,
) -> ReplayVerificationReport {
    if bundle.artifacts.is_empty() {
        return ReplayVerificationReport {
            verified: false,
            error_code: Some("empty_replay_bundle".to_string()),
            artifact_reports: Vec::new(),
            chain_checks: Vec::new(),
        };
    }

    let mut verified = true;
    let mut error_code = None;
    let mut artifact_reports = Vec::with_capacity(bundle.artifacts.len());
    let mut chain_checks = Vec::new();

    for (index, artifact) in bundle.artifacts.iter().enumerate() {
        let report = verify_replay_artifact_item(artifact, resolver);
        if !report.verified {
            verified = false;
            error_code.get_or_insert_with(|| {
                report
                    .error_code
                    .clone()
                    .unwrap_or_else(|| "replay_artifact_verification_failed".to_string())
            });
        }
        artifact_reports.push(report);

        if index == 0 {
            if artifact.previous_artifact_hash.is_some() {
                verified = false;
                error_code.get_or_insert_with(|| "replay_chain_mismatch".to_string());
                chain_checks.push("head_previous_hash_must_be_null".to_string());
            } else {
                chain_checks.push("head_previous_hash_ok".to_string());
            }
            continue;
        }

        let expected_previous = &bundle.artifacts[index - 1].artifact_hash;
        if artifact.previous_artifact_hash.as_ref() != Some(expected_previous) {
            verified = false;
            error_code.get_or_insert_with(|| "replay_chain_mismatch".to_string());
            chain_checks.push(format!("chain_link_mismatch:{index}"));
        } else {
            chain_checks.push(format!("chain_link_ok:{index}"));
        }
    }

    ReplayVerificationReport {
        verified,
        error_code,
        artifact_reports,
        chain_checks,
    }
}

/// Verifies one replay/receipt artifact in isolation.
pub fn verify_receipt_artifact(
    artifact: &ReplayArtifact,
    resolver: &dyn KeyResolver,
) -> VerificationReport {
    verify_replay_artifact_item(artifact, resolver)
}

/// Verifies a detached signature envelope over an already-computed artifact hash.
pub fn verify_detached_signature(
    signature: &SignatureEnvelope,
    artifact_hash: &ArtifactHash,
    artifact_type: impl Into<String>,
    resolver: &dyn KeyResolver,
) -> VerificationReport {
    verify_signature_envelope(signature, artifact_hash, artifact_type.into(), resolver)
}

fn canonical_json_bytes<T: Serialize + ?Sized>(
    artifact: &T,
) -> Result<Vec<u8>, CanonicalizationError> {
    let value = serde_json::to_value(artifact)?;
    let normalized = sort_value(value);
    Ok(serde_json::to_vec(&normalized)?)
}

fn verify_replay_artifact_item(
    artifact: &ReplayArtifact,
    resolver: &dyn KeyResolver,
) -> VerificationReport {
    let computed_hash = match hash_artifact(&artifact.payload) {
        Ok(hash) => hash,
        Err(error) => {
            return VerificationReport {
                verified: false,
                artifact_type: artifact.payload.artifact_type().to_string(),
                error_code: Some("canonicalization_failed".to_string()),
                details: vec![error.to_string()],
                signature_valid: false,
                artifact_hash_valid: false,
                trust_anchor_valid: false,
                attestation_valid: false,
                revocation_valid: false,
                replay_status: "not_proven_offline".to_string(),
                transparency_status: "not_configured".to_string(),
            };
        }
    };

    if computed_hash != artifact.artifact_hash {
        return VerificationReport {
            verified: false,
            artifact_type: artifact.payload.artifact_type().to_string(),
            error_code: Some("artifact_hash_mismatch".to_string()),
            details: vec![
                format!("expected={}", artifact.artifact_hash),
                format!("computed={}", computed_hash),
            ],
            signature_valid: false,
            artifact_hash_valid: false,
            trust_anchor_valid: false,
            attestation_valid: false,
            revocation_valid: false,
            replay_status: "not_proven_offline".to_string(),
            transparency_status: "not_configured".to_string(),
        };
    }

    verify_signature_envelope(
        &artifact.signature,
        &artifact.artifact_hash,
        artifact.payload.artifact_type().to_string(),
        resolver,
    )
}

fn verify_signature_envelope(
    signature: &SignatureEnvelope,
    artifact_hash: &ArtifactHash,
    artifact_type: String,
    resolver: &dyn KeyResolver,
) -> VerificationReport {
    let Some(key_ref) = signature.key_ref.as_deref() else {
        return VerificationReport {
            verified: false,
            artifact_type,
            error_code: Some(VerificationError::MissingKeyRef.to_string()),
            details: Vec::new(),
            signature_valid: false,
            artifact_hash_valid: true,
            trust_anchor_valid: false,
            attestation_valid: false,
            revocation_valid: false,
            replay_status: "not_proven_offline".to_string(),
            transparency_status: "not_configured".to_string(),
        };
    };

    if let Err(error) = resolver.resolve(key_ref) {
        return VerificationReport {
            verified: false,
            artifact_type,
            error_code: Some(error.to_string()),
            details: vec![format!("key_ref={key_ref}")],
            signature_valid: false,
            artifact_hash_valid: true,
            trust_anchor_valid: false,
            attestation_valid: false,
            revocation_valid: false,
            replay_status: "not_proven_offline".to_string(),
            transparency_status: "not_configured".to_string(),
        };
    }

    match signature.signing_scheme.as_str() {
        "debug_hash_v1" => {
            if signature.signature == artifact_hash.to_string() {
                VerificationReport {
                    verified: true,
                    artifact_type,
                    error_code: None,
                    details: vec!["signature_verified".to_string()],
                    signature_valid: true,
                    artifact_hash_valid: true,
                    trust_anchor_valid: true,
                    attestation_valid: true,
                    revocation_valid: true,
                    replay_status: "not_proven_offline".to_string(),
                    transparency_status: "not_configured".to_string(),
                }
            } else {
                VerificationReport {
                    verified: false,
                    artifact_type,
                    error_code: Some("signature_mismatch".to_string()),
                    details: vec!["debug_hash_v1 comparison failed".to_string()],
                    signature_valid: false,
                    artifact_hash_valid: true,
                    trust_anchor_valid: true,
                    attestation_valid: false,
                    revocation_valid: false,
                    replay_status: "not_proven_offline".to_string(),
                    transparency_status: "not_configured".to_string(),
                }
            }
        }
        "hmac_sha256" => verify_hmac_signature(
            signature,
            artifact_hash,
            artifact_type,
            resolver,
            key_ref,
        ),
        "ed25519" => verify_ed25519_signature(
            signature,
            artifact_hash,
            artifact_type,
            resolver,
            key_ref,
        ),
        "ecdsa_p256_sha256" => verify_p256_signature(
            signature,
            artifact_hash,
            artifact_type,
            resolver,
            key_ref,
        ),
        _ => VerificationReport {
            verified: false,
            artifact_type,
            error_code: Some(VerificationError::UnsupportedSigningScheme.to_string()),
            details: vec![format!("scheme={}", signature.signing_scheme)],
            signature_valid: false,
            artifact_hash_valid: true,
            trust_anchor_valid: false,
            attestation_valid: false,
            revocation_valid: false,
            replay_status: "not_proven_offline".to_string(),
            transparency_status: "not_configured".to_string(),
        },
    }
}

fn verify_hmac_signature(
    signature: &SignatureEnvelope,
    artifact_hash: &ArtifactHash,
    artifact_type: String,
    resolver: &dyn KeyResolver,
    key_ref: &str,
) -> VerificationReport {
    let key_material = match resolver.resolve(key_ref) {
        Ok(value) => value,
        Err(error) => {
            return VerificationReport {
                verified: false,
                artifact_type,
                error_code: Some(error.to_string()),
                details: vec![format!("key_ref={key_ref}")],
                signature_valid: false,
                artifact_hash_valid: true,
                trust_anchor_valid: false,
                attestation_valid: false,
                revocation_valid: false,
                replay_status: "not_proven_offline".to_string(),
                transparency_status: "not_configured".to_string(),
            }
        }
    };
    let Some(secret) = key_material.metadata.get("hmac_secret") else {
        return VerificationReport {
            verified: false,
            artifact_type,
            error_code: Some("missing_hmac_secret".to_string()),
            details: vec![format!("key_ref={key_ref}")],
            signature_valid: false,
            artifact_hash_valid: true,
            trust_anchor_valid: false,
            attestation_valid: false,
            revocation_valid: false,
            replay_status: "not_proven_offline".to_string(),
            transparency_status: "not_configured".to_string(),
        };
    };
    let expected = hmac_sha256_hex(secret, &artifact_hash.to_string());
    if expected == signature.signature {
        success_report(artifact_type)
    } else {
        signature_mismatch_report(artifact_type, "hmac_sha256 comparison failed".to_string())
    }
}

fn verify_ed25519_signature(
    signature: &SignatureEnvelope,
    artifact_hash: &ArtifactHash,
    artifact_type: String,
    resolver: &dyn KeyResolver,
    key_ref: &str,
) -> VerificationReport {
    let key_material = match resolver.resolve(key_ref) {
        Ok(value) => value,
        Err(error) => {
            return resolver_error_report(artifact_type, error.to_string(), key_ref);
        }
    };
    let signature_bytes = match base64::engine::general_purpose::STANDARD.decode(&signature.signature) {
        Ok(bytes) => bytes,
        Err(_) => return signature_mismatch_report(artifact_type, "ed25519_signature_decode_failed".to_string()),
    };
    let public_key_pem = match public_material_to_pem(&key_material.public_material, "ed25519") {
        Ok(value) => value,
        Err(error) => return invalid_key_material_report(artifact_type, error),
    };
    match verify_with_openssl(
        &public_key_pem,
        &signature_bytes,
        artifact_hash.to_string().as_bytes(),
        "ed25519",
    ) {
        Ok(true) => {
        success_report(artifact_type)
        }
        Ok(false) => signature_mismatch_report(artifact_type, "ed25519 signature verification failed".to_string()),
        Err(error) => invalid_key_material_report(artifact_type, error),
    }
}

fn verify_p256_signature(
    signature: &SignatureEnvelope,
    artifact_hash: &ArtifactHash,
    artifact_type: String,
    resolver: &dyn KeyResolver,
    key_ref: &str,
) -> VerificationReport {
    let key_material = match resolver.resolve(key_ref) {
        Ok(value) => value,
        Err(error) => {
            return resolver_error_report(artifact_type, error.to_string(), key_ref);
        }
    };
    let signature_bytes = match base64::engine::general_purpose::STANDARD.decode(&signature.signature) {
        Ok(bytes) => bytes,
        Err(_) => return signature_mismatch_report(artifact_type, "p256_signature_decode_failed".to_string()),
    };
    let public_key_pem = match public_material_to_pem(&key_material.public_material, "p256") {
        Ok(value) => value,
        Err(error) => return invalid_key_material_report(artifact_type, error),
    };
    match verify_with_openssl(
        &public_key_pem,
        &signature_bytes,
        artifact_hash.to_string().as_bytes(),
        "p256",
    ) {
        Ok(true) => success_report(artifact_type),
        Ok(false) => signature_mismatch_report(artifact_type, "ecdsa_p256 signature verification failed".to_string()),
        Err(error) => invalid_key_material_report(artifact_type, error),
    }
}

fn success_report(artifact_type: String) -> VerificationReport {
    VerificationReport {
        verified: true,
        artifact_type,
        error_code: None,
        details: vec!["signature_verified".to_string()],
        signature_valid: true,
        artifact_hash_valid: true,
        trust_anchor_valid: true,
        attestation_valid: true,
        revocation_valid: true,
        replay_status: "not_proven_offline".to_string(),
        transparency_status: "not_configured".to_string(),
    }
}

fn signature_mismatch_report(artifact_type: String, detail: String) -> VerificationReport {
    VerificationReport {
        verified: false,
        artifact_type,
        error_code: Some("signature_mismatch".to_string()),
        details: vec![detail],
        signature_valid: false,
        artifact_hash_valid: true,
        trust_anchor_valid: true,
        attestation_valid: false,
        revocation_valid: false,
        replay_status: "not_proven_offline".to_string(),
        transparency_status: "not_configured".to_string(),
    }
}

fn invalid_key_material_report(artifact_type: String, detail: String) -> VerificationReport {
    VerificationReport {
        verified: false,
        artifact_type,
        error_code: Some(VerificationError::InvalidKeyMaterial.to_string()),
        details: vec![detail],
        signature_valid: false,
        artifact_hash_valid: true,
        trust_anchor_valid: false,
        attestation_valid: false,
        revocation_valid: false,
        replay_status: "not_proven_offline".to_string(),
        transparency_status: "not_configured".to_string(),
    }
}

fn resolver_error_report(artifact_type: String, error: String, key_ref: &str) -> VerificationReport {
    VerificationReport {
        verified: false,
        artifact_type,
        error_code: Some(error),
        details: vec![format!("key_ref={key_ref}")],
        signature_valid: false,
        artifact_hash_valid: true,
        trust_anchor_valid: false,
        attestation_valid: false,
        revocation_valid: false,
        replay_status: "not_proven_offline".to_string(),
        transparency_status: "not_configured".to_string(),
    }
}

fn hmac_sha256_hex(secret: &str, message: &str) -> String {
    let block_size = 64usize;
    let mut key = secret.as_bytes().to_vec();
    if key.len() > block_size {
        key = Sha256::digest(&key).to_vec();
    }
    key.resize(block_size, 0);
    let mut o_key_pad = vec![0x5c; block_size];
    let mut i_key_pad = vec![0x36; block_size];
    for (idx, value) in key.iter().enumerate() {
        o_key_pad[idx] ^= value;
        i_key_pad[idx] ^= value;
    }
    let mut inner = Sha256::new();
    inner.update(&i_key_pad);
    inner.update(message.as_bytes());
    let inner_hash = inner.finalize();
    let mut outer = Sha256::new();
    outer.update(&o_key_pad);
    outer.update(inner_hash);
    hex::encode(outer.finalize())
}

fn public_material_to_pem(public_material: &str, scheme: &str) -> Result<String, String> {
    if public_material.contains("BEGIN PUBLIC KEY") {
        return Ok(public_material.to_string());
    }
    let raw = base64::engine::general_purpose::STANDARD
        .decode(public_material)
        .map_err(|_| "public_key_decode_failed".to_string())?;
    let der = match scheme {
        "p256" => {
            let mut prefix = hex::decode("3059301306072A8648CE3D020106082A8648CE3D030107034200")
                .map_err(|_| "p256_prefix_invalid".to_string())?;
            prefix.extend(raw);
            prefix
        }
        "ed25519" => {
            let mut prefix =
                hex::decode("302a300506032b6570032100").map_err(|_| "ed25519_prefix_invalid".to_string())?;
            prefix.extend(raw);
            prefix
        }
        _ => return Err("unsupported_public_key_scheme".to_string()),
    };
    Ok(bytes_to_pem("PUBLIC KEY", &der))
}

fn bytes_to_pem(label: &str, der: &[u8]) -> String {
    let encoded = base64::engine::general_purpose::STANDARD.encode(der);
    let mut body = String::new();
    for chunk in encoded.as_bytes().chunks(64) {
        body.push_str(std::str::from_utf8(chunk).unwrap_or_default());
        body.push('\n');
    }
    format!("-----BEGIN {label}-----\n{body}-----END {label}-----\n")
}

fn verify_with_openssl(
    public_key_pem: &str,
    signature: &[u8],
    message: &[u8],
    scheme: &str,
) -> Result<bool, String> {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "clock_error".to_string())?
        .as_nanos();
    let dir = std::env::temp_dir();
    let key_path = dir.join(format!("seedcore_verify_key_{stamp}.pem"));
    let sig_path = dir.join(format!("seedcore_verify_sig_{stamp}.bin"));
    let msg_path = dir.join(format!("seedcore_verify_msg_{stamp}.bin"));
    fs::write(&key_path, public_key_pem).map_err(|error| format!("key_write_failed:{error}"))?;
    fs::write(&sig_path, signature).map_err(|error| format!("sig_write_failed:{error}"))?;
    fs::write(&msg_path, message).map_err(|error| format!("msg_write_failed:{error}"))?;
    let output = match scheme {
        "p256" => Command::new("openssl")
            .args([
                "dgst",
                "-sha256",
                "-verify",
                key_path.to_string_lossy().as_ref(),
                "-signature",
                sig_path.to_string_lossy().as_ref(),
                msg_path.to_string_lossy().as_ref(),
            ])
            .output()
            .map_err(|error| format!("openssl_unavailable:{error}"))?,
        "ed25519" => Command::new("openssl")
            .args([
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                key_path.to_string_lossy().as_ref(),
                "-rawin",
                "-in",
                msg_path.to_string_lossy().as_ref(),
                "-sigfile",
                sig_path.to_string_lossy().as_ref(),
            ])
            .output()
            .map_err(|error| format!("openssl_unavailable:{error}"))?,
        _ => return Err("unsupported_signature_scheme".to_string()),
    };
    cleanup_temp_paths(&[key_path, sig_path, msg_path]);
    Ok(output.status.success())
}

fn cleanup_temp_paths(paths: &[PathBuf]) {
    for path in paths {
        let _ = fs::remove_file(path);
    }
}

fn sort_value(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut ordered = Map::new();
            for (key, value) in map.into_iter().collect::<BTreeMap<_, _>>() {
                ordered.insert(key, sort_value(value));
            }
            Value::Object(ordered)
        }
        Value::Array(values) => Value::Array(values.into_iter().map(sort_value).collect()),
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use seedcore_kernel_types::{
        Disposition, ExplanationPayload, PolicyReceipt, ReplayArtifactPayload, Timestamp,
        TransitionReceipt,
    };
    use serde::Serialize;
    use std::str::FromStr;

    #[derive(Debug, Clone, PartialEq, Eq, Serialize)]
    struct DemoArtifact {
        name: String,
        values: BTreeMap<String, String>,
    }

    struct DebugSigner;

    impl Signer for DebugSigner {
        fn sign_hash(&self, hash: &ArtifactHash) -> Result<SignatureEnvelope, SigningError> {
            Ok(SignatureEnvelope {
                signer_type: "service".to_string(),
                signer_id: "seedcore-test".to_string(),
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

    fn demo_artifact() -> DemoArtifact {
        let mut values = BTreeMap::new();
        values.insert("b".to_string(), "2".to_string());
        values.insert("a".to_string(), "1".to_string());
        DemoArtifact {
            name: "demo".to_string(),
            values,
        }
    }

    fn artifact_signer() -> SignatureEnvelope {
        SignatureEnvelope {
            signer_type: "service".to_string(),
            signer_id: "seedcore-verify".to_string(),
            signing_scheme: "debug_hash_v1".to_string(),
            key_ref: Some("test-key".to_string()),
            attestation_level: "baseline".to_string(),
            signature: "sha256:placeholder".to_string(),
        }
    }

    fn sample_policy_receipt() -> PolicyReceipt {
        PolicyReceipt {
            policy_receipt_id: "policy-receipt:intent-transfer-001".to_string(),
            policy_decision_id: "decision:intent-transfer-001".to_string(),
            intent_id: "intent-transfer-001".to_string(),
            policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
            disposition: Disposition::Allow,
            explanation: ExplanationPayload::empty(Disposition::Allow),
            governed_receipt_hash: ArtifactHash::sha256_hex("governed-receipt-hash"),
            signer: artifact_signer(),
            timestamp: Timestamp::from_str("2026-04-02T08:00:10Z").unwrap(),
            trust_proof: None,
        }
    }

    fn sample_transition_receipt() -> TransitionReceipt {
        TransitionReceipt {
            transition_receipt_id: "transition-receipt:intent-transfer-001".to_string(),
            intent_id: "intent-transfer-001".to_string(),
            execution_token_id: "token:intent-transfer-001".to_string(),
            endpoint_id: "hal://robot_sim/1".to_string(),
            workflow_type: Some("custody_transfer".to_string()),
            hardware_uuid: "hw-sim-001".to_string(),
            actuator_result_hash: ArtifactHash::sha256_hex("actuator-result"),
            from_zone: Some("vault_a".to_string()),
            to_zone: Some("handoff_bay_3".to_string()),
            executed_at: Timestamp::from_str("2026-04-02T08:00:20Z").unwrap(),
            receipt_nonce: "nonce-transfer-001".to_string(),
            payload_hash: ArtifactHash::sha256_hex("payload-transfer-001"),
            signer: artifact_signer(),
            trust_proof: None,
        }
    }

    #[test]
    fn canonicalize_sorts_object_keys() {
        let bytes = canonicalize(&demo_artifact()).expect("artifact should canonicalize");
        let rendered = String::from_utf8(bytes).expect("canonical JSON should be UTF-8");
        assert_eq!(rendered, r#"{"name":"demo","values":{"a":"1","b":"2"}}"#);
    }

    #[test]
    fn hash_artifact_returns_sha256_prefixed_value() {
        let hash = hash_artifact(&demo_artifact()).expect("artifact should hash");
        assert_eq!(hash.algorithm, "sha256");
        assert_eq!(hash.value.len(), 64);
    }

    #[test]
    fn sign_and_verify_artifact_with_debug_scheme() {
        let signed = sign_artifact(demo_artifact(), &DebugSigner).expect("signing should succeed");
        let report = verify_signed_artifact(&signed, &StaticResolver);
        assert!(report.verified);
        assert_eq!(report.error_code, None);
    }

    #[test]
    fn verify_fails_on_hash_mismatch() {
        let mut signed =
            sign_artifact(demo_artifact(), &DebugSigner).expect("signing should succeed");
        signed.artifact_hash = ArtifactHash::sha256_hex("deadbeef");
        let report = verify_signed_artifact(&signed, &StaticResolver);
        assert!(!report.verified);
        assert_eq!(report.error_code.as_deref(), Some("artifact_hash_mismatch"));
    }

    #[test]
    fn verify_replay_chain_accepts_valid_linked_artifacts() {
        let artifact_one = ReplayArtifactPayload::PolicyReceipt(sample_policy_receipt());
        let artifact_one_hash = hash_artifact(&artifact_one).expect("hash should compute");
        let artifact_two = ReplayArtifactPayload::TransitionReceipt(sample_transition_receipt());
        let artifact_two_hash = hash_artifact(&artifact_two).expect("hash should compute");

        let bundle = ReplayBundle {
            artifacts: vec![
                ReplayArtifact {
                    artifact_id: "policy-receipt:intent-transfer-001".to_string(),
                    payload: artifact_one,
                    artifact_hash: artifact_one_hash.clone(),
                    signature: DebugSigner.sign_hash(&artifact_one_hash).unwrap(),
                    previous_artifact_hash: None,
                },
                ReplayArtifact {
                    artifact_id: "transition-receipt:intent-transfer-001".to_string(),
                    payload: artifact_two,
                    artifact_hash: artifact_two_hash.clone(),
                    signature: DebugSigner.sign_hash(&artifact_two_hash).unwrap(),
                    previous_artifact_hash: Some(artifact_one_hash),
                },
            ],
        };

        let report = verify_replay_chain(&bundle, &StaticResolver);
        assert!(report.verified);
        assert_eq!(report.error_code, None);
        assert_eq!(report.artifact_reports.len(), 2);
        assert_eq!(
            report.chain_checks,
            vec!["head_previous_hash_ok", "chain_link_ok:1"]
        );
    }

    #[test]
    fn verify_replay_chain_rejects_broken_links() {
        let artifact_one = ReplayArtifactPayload::PolicyReceipt(sample_policy_receipt());
        let artifact_one_hash = hash_artifact(&artifact_one).expect("hash should compute");
        let artifact_two = ReplayArtifactPayload::TransitionReceipt(sample_transition_receipt());
        let artifact_two_hash = hash_artifact(&artifact_two).expect("hash should compute");

        let bundle = ReplayBundle {
            artifacts: vec![
                ReplayArtifact {
                    artifact_id: "a".to_string(),
                    payload: artifact_one,
                    artifact_hash: artifact_one_hash.clone(),
                    signature: DebugSigner.sign_hash(&artifact_one_hash).unwrap(),
                    previous_artifact_hash: Some(ArtifactHash::sha256_hex("wrong")),
                },
                ReplayArtifact {
                    artifact_id: "b".to_string(),
                    payload: artifact_two,
                    artifact_hash: artifact_two_hash.clone(),
                    signature: DebugSigner.sign_hash(&artifact_two_hash).unwrap(),
                    previous_artifact_hash: None,
                },
            ],
        };

        let report = verify_replay_chain(&bundle, &StaticResolver);
        assert!(!report.verified);
        assert_eq!(report.error_code.as_deref(), Some("replay_chain_mismatch"));
    }
}
