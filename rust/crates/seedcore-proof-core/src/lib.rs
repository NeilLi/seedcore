//! Proof integrity kernel for SeedCore.
//!
//! This crate will own canonical serialization, hashing, signing abstractions,
//! artifact verification, and replay-chain verification.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use thiserror::Error;

pub use seedcore_kernel_types::{
    ArtifactHash, Placeholder as KernelPlaceholder, SignatureEnvelope,
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
#[derive(Debug, Clone, PartialEq, Eq)]
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
}

/// Replay artifact item used for offline chain verification.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReplayArtifact {
    pub artifact_id: String,
    pub artifact_type: String,
    pub artifact: Value,
    pub artifact_hash: ArtifactHash,
    pub signature: SignatureEnvelope,
    pub previous_artifact_hash: Option<ArtifactHash>,
}

/// Replay bundle used for deterministic offline verification.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct ReplayBundle {
    pub artifacts: Vec<ReplayArtifact>,
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
    let computed_hash = match hash_artifact(&artifact.artifact) {
        Ok(hash) => hash,
        Err(error) => {
            return VerificationReport {
                verified: false,
                artifact_type: artifact.artifact_type.clone(),
                error_code: Some("canonicalization_failed".to_string()),
                details: vec![error.to_string()],
            };
        }
    };

    if computed_hash != artifact.artifact_hash {
        return VerificationReport {
            verified: false,
            artifact_type: artifact.artifact_type.clone(),
            error_code: Some("artifact_hash_mismatch".to_string()),
            details: vec![
                format!("expected={}", artifact.artifact_hash),
                format!("computed={}", computed_hash),
            ],
        };
    }

    verify_signature_envelope(
        &artifact.signature,
        &artifact.artifact_hash,
        artifact.artifact_type.clone(),
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
        };
    };

    if let Err(error) = resolver.resolve(key_ref) {
        return VerificationReport {
            verified: false,
            artifact_type,
            error_code: Some(error.to_string()),
            details: vec![format!("key_ref={key_ref}")],
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
                }
            } else {
                VerificationReport {
                    verified: false,
                    artifact_type,
                    error_code: Some("signature_mismatch".to_string()),
                    details: vec!["debug_hash_v1 comparison failed".to_string()],
                }
            }
        }
        _ => VerificationReport {
            verified: false,
            artifact_type,
            error_code: Some(VerificationError::UnsupportedSigningScheme.to_string()),
            details: vec![format!("scheme={}", signature.signing_scheme)],
        },
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
    use serde::Serialize;
    use serde_json::json;

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
        let artifact_one = json!({
            "policy_receipt_id": "policy-receipt:intent-transfer-001",
            "disposition": "allow",
        });
        let artifact_one_hash = hash_artifact(&artifact_one).expect("hash should compute");
        let artifact_two = json!({
            "transition_receipt_id": "transition-receipt:intent-transfer-001",
            "decision_ref": "policy-receipt:intent-transfer-001",
        });
        let artifact_two_hash = hash_artifact(&artifact_two).expect("hash should compute");

        let bundle = ReplayBundle {
            artifacts: vec![
                ReplayArtifact {
                    artifact_id: "policy-receipt:intent-transfer-001".to_string(),
                    artifact_type: "policy_receipt".to_string(),
                    artifact: artifact_one,
                    artifact_hash: artifact_one_hash.clone(),
                    signature: DebugSigner.sign_hash(&artifact_one_hash).unwrap(),
                    previous_artifact_hash: None,
                },
                ReplayArtifact {
                    artifact_id: "transition-receipt:intent-transfer-001".to_string(),
                    artifact_type: "transition_receipt".to_string(),
                    artifact: artifact_two,
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
        let artifact_one = json!({
            "policy_receipt_id": "policy-receipt:intent-transfer-001",
            "disposition": "allow",
        });
        let artifact_one_hash = hash_artifact(&artifact_one).expect("hash should compute");
        let artifact_two = json!({
            "transition_receipt_id": "transition-receipt:intent-transfer-001",
            "decision_ref": "policy-receipt:intent-transfer-001",
        });
        let artifact_two_hash = hash_artifact(&artifact_two).expect("hash should compute");

        let bundle = ReplayBundle {
            artifacts: vec![
                ReplayArtifact {
                    artifact_id: "a".to_string(),
                    artifact_type: "policy_receipt".to_string(),
                    artifact: artifact_one,
                    artifact_hash: artifact_one_hash.clone(),
                    signature: DebugSigner.sign_hash(&artifact_one_hash).unwrap(),
                    previous_artifact_hash: Some(ArtifactHash::sha256_hex("wrong")),
                },
                ReplayArtifact {
                    artifact_id: "b".to_string(),
                    artifact_type: "transition_receipt".to_string(),
                    artifact: artifact_two,
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
