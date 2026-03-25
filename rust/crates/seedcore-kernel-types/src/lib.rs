//! Shared Rust-native contract types for SeedCore's authority-bearing kernel.
//!
//! This crate is intended to become the source of truth for strict artifact
//! types such as `ActionIntent`, `TransferApprovalEnvelope`, `PolicyDecision`,
//! `ExecutionToken`, `PolicyReceipt`, `TransitionReceipt`, and
//! `EvidenceBundle`.
//!
//! This module starts with the smallest shared primitives that the rest of the
//! kernel crates can depend on safely: core disposition and proof value types,
//! plus the minimum explanation payload.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};
use std::str::FromStr;
use thiserror::Error;

/// Shared workspace placeholder retained while the broader kernel contracts are
/// introduced incrementally.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Placeholder;

/// The deterministic runtime disposition owned by the kernel.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    Allow,
    Deny,
    Quarantine,
    Escalate,
}

impl Disposition {
    /// Returns the stable string form used across receipts, fixtures, and UI
    /// projections.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Deny => "deny",
            Self::Quarantine => "quarantine",
            Self::Escalate => "escalate",
        }
    }
}

impl Display for Disposition {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Timestamp parsing and formatting error.
#[derive(Debug, Error)]
pub enum TimestampError {
    #[error("invalid_rfc3339_timestamp")]
    InvalidRfc3339(#[from] chrono::ParseError),
}

/// Stable UTC timestamp wrapper for kernel contracts.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Timestamp(DateTime<Utc>);

impl Timestamp {
    pub fn new(value: DateTime<Utc>) -> Self {
        Self(value)
    }

    pub fn into_inner(self) -> DateTime<Utc> {
        self.0
    }

    pub fn as_inner(&self) -> &DateTime<Utc> {
        &self.0
    }
}

impl Display for Timestamp {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0.to_rfc3339())
    }
}

impl From<DateTime<Utc>> for Timestamp {
    fn from(value: DateTime<Utc>) -> Self {
        Self::new(value)
    }
}

impl FromStr for Timestamp {
    type Err = TimestampError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let parsed = DateTime::parse_from_rfc3339(s)?.with_timezone(&Utc);
        Ok(Self(parsed))
    }
}

/// Algorithm-tagged artifact hash value.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArtifactHash {
    pub algorithm: String,
    pub value: String,
}

impl ArtifactHash {
    pub fn new(algorithm: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            algorithm: algorithm.into(),
            value: value.into(),
        }
    }

    pub fn sha256_hex(value: impl Into<String>) -> Self {
        Self::new("sha256", value)
    }
}

impl Display for ArtifactHash {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}:{}", self.algorithm, self.value)
    }
}

/// Signature envelope carried by proof-bearing artifacts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignatureEnvelope {
    pub signer_type: String,
    pub signer_id: String,
    pub signing_scheme: String,
    pub key_ref: Option<String>,
    pub attestation_level: String,
    pub signature: String,
}

/// Deterministic obligation entry included in the explanation payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Obligation {
    pub obligation_type: String,
    pub reference: Option<String>,
    #[serde(default)]
    pub details: BTreeMap<String, String>,
}

/// Minimum cross-surface explanation payload required by the execution spine.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExplanationPayload {
    pub disposition: Disposition,
    #[serde(default)]
    pub matched_policy_refs: Vec<String>,
    #[serde(default)]
    pub authority_path_summary: Vec<String>,
    #[serde(default)]
    pub missing_prerequisites: Vec<String>,
    #[serde(default)]
    pub trust_gaps: Vec<String>,
    #[serde(default)]
    pub minted_artifacts: Vec<String>,
    #[serde(default)]
    pub obligations: Vec<Obligation>,
}

impl ExplanationPayload {
    pub fn empty(disposition: Disposition) -> Self {
        Self {
            disposition,
            matched_policy_refs: Vec::new(),
            authority_path_summary: Vec::new(),
            missing_prerequisites: Vec::new(),
            trust_gaps: Vec::new(),
            minted_artifacts: Vec::new(),
            obligations: Vec::new(),
        }
    }
}

/// Approval lifecycle state for `TransferApprovalEnvelope`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ApprovalStatus {
    Pending,
    PartiallyApproved,
    Approved,
    Expired,
    Revoked,
    Superseded,
}

impl ApprovalStatus {
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Expired | Self::Revoked | Self::Superseded)
    }
}

/// Role-bound approval record used by governed approval envelopes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RoleApproval {
    pub role: String,
    pub principal_ref: String,
    pub status: ApprovalStatus,
    pub approved_at: Option<Timestamp>,
    pub approval_ref: String,
}

/// Transfer-specific contextual fields bound into the approval envelope.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransferContext {
    pub from_zone: Option<String>,
    pub to_zone: Option<String>,
    pub facility_ref: Option<String>,
    pub custody_point_ref: Option<String>,
}

/// Revocation metadata for approval lifecycle transitions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RevocationRecord {
    pub revoked_by: String,
    pub revoked_at: Timestamp,
    pub reason: String,
}

/// Governed dual-approval envelope for Restricted Custody Transfer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransferApprovalEnvelope {
    pub approval_envelope_id: String,
    pub workflow_type: String,
    pub status: ApprovalStatus,
    pub asset_ref: String,
    pub lot_id: Option<String>,
    pub from_custodian_ref: String,
    pub to_custodian_ref: String,
    pub transfer_context: TransferContext,
    pub required_approvals: Vec<RoleApproval>,
    pub approval_binding_hash: Option<ArtifactHash>,
    pub policy_snapshot_ref: String,
    pub expires_at: Timestamp,
    pub created_at: Timestamp,
    pub version: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disposition_uses_stable_strings() {
        assert_eq!(Disposition::Allow.as_str(), "allow");
        assert_eq!(Disposition::Quarantine.to_string(), "quarantine");
    }

    #[test]
    fn timestamp_round_trips_rfc3339() {
        let ts = Timestamp::from_str("2026-04-02T08:00:05Z").expect("timestamp should parse");
        assert_eq!(ts.to_string(), "2026-04-02T08:00:05+00:00");
    }

    #[test]
    fn artifact_hash_formats_with_algorithm_prefix() {
        let hash = ArtifactHash::sha256_hex("abc123");
        assert_eq!(hash.to_string(), "sha256:abc123");
    }

    #[test]
    fn explanation_payload_empty_sets_all_lists_empty() {
        let payload = ExplanationPayload::empty(Disposition::Escalate);
        assert_eq!(payload.disposition, Disposition::Escalate);
        assert!(payload.matched_policy_refs.is_empty());
        assert!(payload.obligations.is_empty());
    }

    #[test]
    fn approval_status_terminal_matches_expected_values() {
        assert!(ApprovalStatus::Expired.is_terminal());
        assert!(ApprovalStatus::Revoked.is_terminal());
        assert!(!ApprovalStatus::Approved.is_terminal());
    }

    #[test]
    fn transfer_approval_envelope_serializes_status_in_screaming_snake_case() {
        let envelope = TransferApprovalEnvelope {
            approval_envelope_id: "approval-transfer-001".to_string(),
            workflow_type: "custody_transfer".to_string(),
            status: ApprovalStatus::Approved,
            asset_ref: "asset:lot-8841".to_string(),
            lot_id: Some("lot-8841".to_string()),
            from_custodian_ref: "principal:facility_mgr_001".to_string(),
            to_custodian_ref: "principal:outbound_mgr_002".to_string(),
            transfer_context: TransferContext {
                from_zone: Some("vault_a".to_string()),
                to_zone: Some("handoff_bay_3".to_string()),
                facility_ref: Some("facility:north_warehouse".to_string()),
                custody_point_ref: Some("custody_point:handoff_bay_3".to_string()),
            },
            required_approvals: vec![RoleApproval {
                role: "FACILITY_MANAGER".to_string(),
                principal_ref: "principal:facility_mgr_001".to_string(),
                status: ApprovalStatus::Approved,
                approved_at: Some(Timestamp::from_str("2026-04-02T08:00:05Z").unwrap()),
                approval_ref: "approval:facility_mgr_001".to_string(),
            }],
            approval_binding_hash: Some(ArtifactHash::sha256_hex("placeholder")),
            policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
            expires_at: Timestamp::from_str("2026-04-02T08:05:00Z").unwrap(),
            created_at: Timestamp::from_str("2026-04-02T08:00:00Z").unwrap(),
            version: 1,
        };

        let value = serde_json::to_value(envelope).expect("envelope should serialize");
        assert_eq!(
            value.get("status").and_then(|item| item.as_str()),
            Some("APPROVED")
        );
    }
}
