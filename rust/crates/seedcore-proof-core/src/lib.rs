//! Proof integrity kernel for SeedCore.
//!
//! This crate will own canonical serialization, hashing, signing abstractions,
//! artifact verification, and replay-chain verification.

use serde::Serialize;
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
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerificationReport {
    pub verified: bool,
    pub artifact_type: String,
    pub error_code: Option<String>,
    pub details: Vec<String>,
}

/// Deterministic canonicalization helper.
pub fn canonicalize<T: CanonicalArtifact>(
    artifact: &T,
) -> Result<Vec<u8>, CanonicalizationError> {
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

    let Some(key_ref) = artifact.signature.key_ref.as_deref() else {
        return VerificationReport {
            verified: false,
            artifact_type: std::any::type_name::<T>().to_string(),
            error_code: Some(VerificationError::MissingKeyRef.to_string()),
            details: Vec::new(),
        };
    };

    if let Err(error) = resolver.resolve(key_ref) {
        return VerificationReport {
            verified: false,
            artifact_type: std::any::type_name::<T>().to_string(),
            error_code: Some(error.to_string()),
            details: vec![format!("key_ref={key_ref}")],
        };
    }

    match artifact.signature.signing_scheme.as_str() {
        "debug_hash_v1" => {
            if artifact.signature.signature == artifact.artifact_hash.to_string() {
                VerificationReport {
                    verified: true,
                    artifact_type: std::any::type_name::<T>().to_string(),
                    error_code: None,
                    details: vec!["signature_verified".to_string()],
                }
            } else {
                VerificationReport {
                    verified: false,
                    artifact_type: std::any::type_name::<T>().to_string(),
                    error_code: Some("signature_mismatch".to_string()),
                    details: vec!["debug_hash_v1 comparison failed".to_string()],
                }
            }
        }
        _ => VerificationReport {
            verified: false,
            artifact_type: std::any::type_name::<T>().to_string(),
            error_code: Some(VerificationError::UnsupportedSigningScheme.to_string()),
            details: vec![format!("scheme={}", artifact.signature.signing_scheme)],
        },
    }
}

fn canonical_json_bytes<T: Serialize + ?Sized>(
    artifact: &T,
) -> Result<Vec<u8>, CanonicalizationError> {
    let value = serde_json::to_value(artifact)?;
    let normalized = sort_value(value);
    Ok(serde_json::to_vec(&normalized)?)
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
        Value::Array(values) => {
            Value::Array(values.into_iter().map(sort_value).collect())
        }
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;

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
}
