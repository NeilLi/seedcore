//! Execution-token kernel for SeedCore.
//!
//! This crate will own token claims, minting, verification, TTL checks, and
//! scope enforcement.

use seedcore_kernel_types::{ArtifactHash, SignatureEnvelope, Timestamp};
use seedcore_proof_core::{
    sign_artifact, verify_signed_artifact, KeyResolver, SignedArtifact, Signer,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Token scope and runtime-binding constraints.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TokenConstraints {
    pub action_type: String,
    pub target_zone: Option<String>,
    pub asset_id: Option<String>,
    pub principal_agent_id: Option<String>,
    pub source_registration_id: Option<String>,
    pub registration_decision_id: Option<String>,
    pub endpoint_id: Option<String>,
}

/// Claims required to mint an execution token.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionTokenClaims {
    pub token_id: String,
    pub intent_id: String,
    pub issued_at: Timestamp,
    pub valid_until: Timestamp,
    pub contract_version: String,
    pub constraints: TokenConstraints,
}

/// Signed execution token artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionToken {
    pub token_id: String,
    pub intent_id: String,
    pub issued_at: Timestamp,
    pub valid_until: Timestamp,
    pub contract_version: String,
    pub constraints: TokenConstraints,
    pub artifact_hash: ArtifactHash,
    pub signature: SignatureEnvelope,
}

/// Runtime request context evaluated against token constraints.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ExecutionRequestContext {
    pub action_type: String,
    pub target_zone: Option<String>,
    pub asset_id: Option<String>,
    pub principal_agent_id: Option<String>,
    pub source_registration_id: Option<String>,
    pub registration_decision_id: Option<String>,
    pub endpoint_id: Option<String>,
}

/// Verification result for a token artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TokenVerificationReport {
    pub verified: bool,
    pub error_code: Option<String>,
    pub details: Vec<String>,
}

/// Constraint enforcement result for a token against an execution request.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TokenEnforcementReport {
    pub allowed: bool,
    pub error_code: Option<String>,
    pub details: Vec<String>,
}

/// Token-core minting, verification, and enforcement errors.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum TokenError {
    #[error("missing_field:{0}")]
    MissingField(&'static str),
    #[error("invalid_validity_window")]
    InvalidValidityWindow,
    #[error("proof_error:{0}")]
    ProofError(String),
}

/// Mints a signed execution token from strict claims.
pub fn mint_token(
    claims: ExecutionTokenClaims,
    signer: &dyn Signer,
) -> Result<ExecutionToken, TokenError> {
    validate_claims(&claims)?;
    let signed = sign_artifact(claims, signer)
        .map_err(|error| TokenError::ProofError(error.to_string()))?;
    Ok(ExecutionToken::from_signed(signed))
}

/// Verifies the signed token artifact and its validity window.
pub fn verify_token(
    token: &ExecutionToken,
    resolver: &dyn KeyResolver,
    now: Timestamp,
) -> TokenVerificationReport {
    let signed = token.clone().into_signed();
    let report = verify_signed_artifact(&signed, resolver);
    if !report.verified {
        return TokenVerificationReport {
            verified: false,
            error_code: report.error_code,
            details: report.details,
        };
    }
    if token.valid_until <= now {
        return TokenVerificationReport {
            verified: false,
            error_code: Some("token_expired".to_string()),
            details: vec![format!("valid_until={}", token.valid_until)],
        };
    }
    TokenVerificationReport {
        verified: true,
        error_code: None,
        details: vec!["token_verified".to_string()],
    }
}

/// Enforces token constraints against a runtime execution request.
pub fn enforce_constraints(
    token: &ExecutionToken,
    request: &ExecutionRequestContext,
    now: Timestamp,
) -> TokenEnforcementReport {
    let verification = verify_window_only(token, now);
    if let Some(error_code) = verification {
        return TokenEnforcementReport {
            allowed: false,
            error_code: Some(error_code),
            details: Vec::new(),
        };
    }

    if token.constraints.action_type != request.action_type {
        return deny("action_type_mismatch");
    }
    if mismatch(token.constraints.target_zone.as_deref(), request.target_zone.as_deref()) {
        return deny("target_zone_mismatch");
    }
    if mismatch(token.constraints.asset_id.as_deref(), request.asset_id.as_deref()) {
        return deny("asset_id_mismatch");
    }
    if mismatch(
        token.constraints.principal_agent_id.as_deref(),
        request.principal_agent_id.as_deref(),
    ) {
        return deny("principal_agent_id_mismatch");
    }
    if mismatch(
        token.constraints.source_registration_id.as_deref(),
        request.source_registration_id.as_deref(),
    ) {
        return deny("source_registration_id_mismatch");
    }
    if mismatch(
        token.constraints.registration_decision_id.as_deref(),
        request.registration_decision_id.as_deref(),
    ) {
        return deny("registration_decision_id_mismatch");
    }
    if mismatch(token.constraints.endpoint_id.as_deref(), request.endpoint_id.as_deref()) {
        return deny("endpoint_id_mismatch");
    }

    TokenEnforcementReport {
        allowed: true,
        error_code: None,
        details: vec!["constraints_satisfied".to_string()],
    }
}

fn validate_claims(claims: &ExecutionTokenClaims) -> Result<(), TokenError> {
    require_non_empty(&claims.token_id, "token_id")?;
    require_non_empty(&claims.intent_id, "intent_id")?;
    require_non_empty(&claims.contract_version, "contract_version")?;
    require_non_empty(&claims.constraints.action_type, "constraints.action_type")?;
    if claims.valid_until <= claims.issued_at {
        return Err(TokenError::InvalidValidityWindow);
    }
    Ok(())
}

fn verify_window_only(token: &ExecutionToken, now: Timestamp) -> Option<String> {
    if token.valid_until <= now {
        Some("token_expired".to_string())
    } else {
        None
    }
}

fn require_non_empty(value: &str, field_name: &'static str) -> Result<(), TokenError> {
    if value.trim().is_empty() {
        Err(TokenError::MissingField(field_name))
    } else {
        Ok(())
    }
}

fn mismatch(expected: Option<&str>, actual: Option<&str>) -> bool {
    match expected {
        Some(expected) => actual != Some(expected),
        None => false,
    }
}

fn deny(code: &str) -> TokenEnforcementReport {
    TokenEnforcementReport {
        allowed: false,
        error_code: Some(code.to_string()),
        details: Vec::new(),
    }
}

impl ExecutionToken {
    fn from_signed(signed: SignedArtifact<ExecutionTokenClaims>) -> Self {
        Self {
            token_id: signed.artifact.token_id,
            intent_id: signed.artifact.intent_id,
            issued_at: signed.artifact.issued_at,
            valid_until: signed.artifact.valid_until,
            contract_version: signed.artifact.contract_version,
            constraints: signed.artifact.constraints,
            artifact_hash: signed.artifact_hash,
            signature: signed.signature,
        }
    }

    fn into_signed(self) -> SignedArtifact<ExecutionTokenClaims> {
        SignedArtifact {
            artifact: ExecutionTokenClaims {
                token_id: self.token_id,
                intent_id: self.intent_id,
                issued_at: self.issued_at,
                valid_until: self.valid_until,
                contract_version: self.contract_version,
                constraints: self.constraints,
            },
            artifact_hash: self.artifact_hash,
            signature: self.signature,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use seedcore_proof_core::{KeyMaterial, VerificationError};
    use std::collections::BTreeMap;
    use std::str::FromStr;

    struct DebugSigner;

    impl Signer for DebugSigner {
        fn sign_hash(
            &self,
            hash: &ArtifactHash,
        ) -> Result<SignatureEnvelope, seedcore_proof_core::SigningError> {
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

    fn sample_claims() -> ExecutionTokenClaims {
        ExecutionTokenClaims {
            token_id: "token-transfer-001".to_string(),
            intent_id: "intent-transfer-001".to_string(),
            issued_at: Timestamp::from_str("2026-04-02T08:00:15Z").unwrap(),
            valid_until: Timestamp::from_str("2026-04-02T08:01:15Z").unwrap(),
            contract_version: "transfer-v1".to_string(),
            constraints: TokenConstraints {
                action_type: "TRANSFER_CUSTODY".to_string(),
                target_zone: Some("handoff_bay_3".to_string()),
                asset_id: Some("asset:lot-8841".to_string()),
                principal_agent_id: Some("agent:custody_runtime_01".to_string()),
                source_registration_id: Some("registration:approved-001".to_string()),
                registration_decision_id: Some("decision:registration-001".to_string()),
                endpoint_id: Some("hal://robot_sim/1".to_string()),
            },
        }
    }

    fn sample_request() -> ExecutionRequestContext {
        ExecutionRequestContext {
            action_type: "TRANSFER_CUSTODY".to_string(),
            target_zone: Some("handoff_bay_3".to_string()),
            asset_id: Some("asset:lot-8841".to_string()),
            principal_agent_id: Some("agent:custody_runtime_01".to_string()),
            source_registration_id: Some("registration:approved-001".to_string()),
            registration_decision_id: Some("decision:registration-001".to_string()),
            endpoint_id: Some("hal://robot_sim/1".to_string()),
        }
    }

    #[test]
    fn mint_and_verify_token_with_debug_signature() {
        let token = mint_token(sample_claims(), &DebugSigner).expect("token should mint");
        let report = verify_token(
            &token,
            &StaticResolver,
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        );
        assert!(report.verified);
    }

    #[test]
    fn verify_token_rejects_expired_token() {
        let token = mint_token(sample_claims(), &DebugSigner).expect("token should mint");
        let report = verify_token(
            &token,
            &StaticResolver,
            Timestamp::from_str("2026-04-02T08:02:00Z").unwrap(),
        );
        assert!(!report.verified);
        assert_eq!(report.error_code.as_deref(), Some("token_expired"));
    }

    #[test]
    fn enforce_constraints_accepts_matching_request() {
        let token = mint_token(sample_claims(), &DebugSigner).expect("token should mint");
        let report = enforce_constraints(
            &token,
            &sample_request(),
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        );
        assert!(report.allowed);
    }

    #[test]
    fn enforce_constraints_rejects_endpoint_mismatch() {
        let token = mint_token(sample_claims(), &DebugSigner).expect("token should mint");
        let mut request = sample_request();
        request.endpoint_id = Some("hal://robot_sim/2".to_string());
        let report = enforce_constraints(
            &token,
            &request,
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        );
        assert!(!report.allowed);
        assert_eq!(report.error_code.as_deref(), Some("endpoint_id_mismatch"));
    }
}
