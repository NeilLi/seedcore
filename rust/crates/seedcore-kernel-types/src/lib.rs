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

/// Key-binding evidence for a trust-bearing signer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct KeyBindingProof {
    pub binding_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key_handle: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key_label: Option<String>,
    #[serde(default)]
    pub certificate_chain: Vec<String>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

/// Attestation summary bound to a trust-bearing signer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct AttestationProof {
    pub attestation_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ak_key_ref: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quote: Option<String>,
    #[serde(default)]
    pub endorsement_chain: Vec<String>,
    #[serde(default)]
    pub summary: BTreeMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub issued_at: Option<String>,
}

/// Replay-protection proof carried by attested transition receipts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ReplayProof {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub receipt_nonce: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub receipt_counter: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub previous_receipt_hash: Option<String>,
}

/// External transparency anchoring metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TransparencyProof {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub log_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entry_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub integrated_time: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub proof_hash: Option<String>,
    #[serde(default)]
    pub details: BTreeMap<String, String>,
}

/// Shared trust-bearing proof envelope.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TrustProof {
    pub signer_profile: String,
    pub trust_anchor_type: String,
    pub key_algorithm: String,
    pub key_ref: String,
    pub public_key_fingerprint: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key_binding: Option<KeyBindingProof>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attestation: Option<AttestationProof>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replay: Option<ReplayProof>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub revocation_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transparency: Option<TransparencyProof>,
}

/// Trusted verification key entry loaded by `seedcore-verify`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TrustBundleKey {
    pub key_ref: String,
    pub key_algorithm: String,
    pub public_key: String,
    pub trust_anchor_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signer_profile: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub endpoint_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub revocation_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attestation_root: Option<String>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

/// Transparency configuration distributed with a trust bundle.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TrustBundleTransparencyConfig {
    pub enabled: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub log_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub public_key: Option<String>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

/// Standalone trust bundle used by the offline verifier.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TrustBundle {
    pub version: String,
    #[serde(default)]
    pub trusted_keys: BTreeMap<String, TrustBundleKey>,
    #[serde(default)]
    pub endpoint_bindings: BTreeMap<String, String>,
    #[serde(default)]
    pub node_bindings: BTreeMap<String, String>,
    #[serde(default)]
    pub accepted_trust_anchor_types: Vec<String>,
    #[serde(default)]
    pub attestation_roots: BTreeMap<String, String>,
    #[serde(default)]
    pub revoked_keys: Vec<String>,
    #[serde(default)]
    pub revoked_nodes: Vec<String>,
    #[serde(default)]
    pub revocation_cutoffs: BTreeMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transparency: Option<TrustBundleTransparencyConfig>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
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

/// Append-only approval transition event bound to an approval envelope
/// lifecycle change.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApprovalTransitionEvent {
    pub event_id: String,
    pub event_hash: String,
    pub previous_event_hash: Option<String>,
    pub occurred_at: Timestamp,
    pub transition_type: String,
    pub envelope_id: String,
    pub previous_status: String,
    pub next_status: String,
    pub previous_binding_hash: Option<String>,
    pub next_binding_hash: Option<String>,
    pub envelope_version: u32,
}

/// Canonical append-only transition chain for approval lifecycle events.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ApprovalTransitionHistory {
    #[serde(default)]
    pub events: Vec<ApprovalTransitionEvent>,
    pub chain_head: Option<String>,
}

/// Principal context bound to an action intent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentPrincipal {
    pub principal_ref: String,
    pub organization_ref: Option<String>,
    #[serde(default)]
    pub role_refs: Vec<String>,
}

/// Action context bound to an action intent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentAction {
    pub action_type: String,
    pub target_zone: Option<String>,
    pub endpoint_id: Option<String>,
}

/// Resource context bound to an action intent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentResource {
    pub asset_ref: String,
    pub lot_id: Option<String>,
}

/// Environment context bound to an action intent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct IntentEnvironment {
    pub source_registration_id: Option<String>,
    pub registration_decision_id: Option<String>,
    #[serde(default)]
    pub attributes: BTreeMap<String, String>,
}

/// Canonical action-intent artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActionIntent {
    pub intent_id: String,
    pub timestamp: Timestamp,
    pub valid_until: Timestamp,
    pub principal: IntentPrincipal,
    pub action: IntentAction,
    pub resource: IntentResource,
    pub environment: IntentEnvironment,
}

/// Shared governed decision artifact fields.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GovernedDecisionArtifact {
    pub decision_id: String,
    pub action_intent_ref: String,
    pub policy_snapshot_ref: String,
    pub disposition: Disposition,
    pub asset_ref: String,
}

/// Execution-token scope and runtime-binding constraints.
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

/// Canonical execution-token artifact.
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

/// Canonical policy-decision artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyDecision {
    pub policy_decision_id: String,
    pub allowed: bool,
    pub disposition: Disposition,
    pub reason: Option<String>,
    pub policy_snapshot_ref: String,
    pub explanation: ExplanationPayload,
    pub governed_decision_artifact: GovernedDecisionArtifact,
    pub execution_token: Option<ExecutionToken>,
}

/// Canonical policy receipt artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyReceipt {
    pub policy_receipt_id: String,
    pub policy_decision_id: String,
    pub intent_id: String,
    pub policy_snapshot_ref: String,
    pub disposition: Disposition,
    pub explanation: ExplanationPayload,
    pub governed_receipt_hash: ArtifactHash,
    pub signer: SignatureEnvelope,
    pub timestamp: Timestamp,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trust_proof: Option<TrustProof>,
}

/// Canonical transition receipt artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransitionReceipt {
    pub transition_receipt_id: String,
    pub intent_id: String,
    pub execution_token_id: String,
    pub endpoint_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workflow_type: Option<String>,
    pub hardware_uuid: String,
    pub actuator_result_hash: ArtifactHash,
    pub from_zone: Option<String>,
    pub to_zone: Option<String>,
    pub executed_at: Timestamp,
    pub receipt_nonce: String,
    pub payload_hash: ArtifactHash,
    pub signer: SignatureEnvelope,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trust_proof: Option<TrustProof>,
}

/// Telemetry reference bound into an evidence bundle.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TelemetryRef {
    pub telemetry_id: String,
    pub captured_at: Timestamp,
    pub hash: ArtifactHash,
}

/// Media reference bound into an evidence bundle.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MediaRef {
    pub media_id: String,
    pub media_type: String,
    pub hash: ArtifactHash,
}

/// Canonical evidence bundle artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceBundle {
    pub evidence_bundle_id: String,
    pub intent_id: String,
    pub execution_token_id: Option<String>,
    pub policy_receipt_id: Option<String>,
    #[serde(default)]
    pub transition_receipt_ids: Vec<String>,
    #[serde(default)]
    pub telemetry_refs: Vec<TelemetryRef>,
    #[serde(default)]
    pub media_refs: Vec<MediaRef>,
    pub signer: SignatureEnvelope,
    pub created_at: Timestamp,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trust_proof: Option<TrustProof>,
}

/// Typed replay artifact payload variants for offline chain verification.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "artifact_type", content = "artifact", rename_all = "snake_case")]
pub enum ReplayArtifactPayload {
    ActionIntent(ActionIntent),
    TransferApprovalEnvelope(TransferApprovalEnvelope),
    PolicyDecision(PolicyDecision),
    ExecutionToken(ExecutionToken),
    PolicyReceipt(PolicyReceipt),
    TransitionReceipt(TransitionReceipt),
    EvidenceBundle(EvidenceBundle),
    ApprovalTransitionHistory(ApprovalTransitionHistory),
}

impl ReplayArtifactPayload {
    pub const fn artifact_type(&self) -> &'static str {
        match self {
            Self::ActionIntent(_) => "action_intent",
            Self::TransferApprovalEnvelope(_) => "transfer_approval_envelope",
            Self::PolicyDecision(_) => "policy_decision",
            Self::ExecutionToken(_) => "execution_token",
            Self::PolicyReceipt(_) => "policy_receipt",
            Self::TransitionReceipt(_) => "transition_receipt",
            Self::EvidenceBundle(_) => "evidence_bundle",
            Self::ApprovalTransitionHistory(_) => "approval_transition_history",
        }
    }
}

/// One typed artifact in a deterministic replay chain.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplayArtifact {
    pub artifact_id: String,
    #[serde(flatten)]
    pub payload: ReplayArtifactPayload,
    pub artifact_hash: ArtifactHash,
    pub signature: SignatureEnvelope,
    pub previous_artifact_hash: Option<ArtifactHash>,
}

/// Deterministic replay bundle for offline verification.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ReplayBundle {
    #[serde(default)]
    pub artifacts: Vec<ReplayArtifact>,
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

    #[test]
    fn action_intent_round_trips() {
        let intent = ActionIntent {
            intent_id: "intent-transfer-001".to_string(),
            timestamp: Timestamp::from_str("2026-04-02T08:00:00Z").unwrap(),
            valid_until: Timestamp::from_str("2026-04-02T08:01:00Z").unwrap(),
            principal: IntentPrincipal {
                principal_ref: "principal:facility_mgr_001".to_string(),
                organization_ref: Some("org:north_warehouse".to_string()),
                role_refs: vec!["FACILITY_MANAGER".to_string()],
            },
            action: IntentAction {
                action_type: "TRANSFER_CUSTODY".to_string(),
                target_zone: Some("handoff_bay_3".to_string()),
                endpoint_id: Some("hal://robot_sim/1".to_string()),
            },
            resource: IntentResource {
                asset_ref: "asset:lot-8841".to_string(),
                lot_id: Some("lot-8841".to_string()),
            },
            environment: IntentEnvironment::default(),
        };

        let value = serde_json::to_value(&intent).expect("action intent should serialize");
        let parsed: ActionIntent =
            serde_json::from_value(value).expect("action intent should deserialize");
        assert_eq!(parsed, intent);
    }

    #[test]
    fn approval_transition_history_round_trips() {
        let history = ApprovalTransitionHistory {
            events: vec![ApprovalTransitionEvent {
                event_id: "approval-transition-event:sha256:event-001".to_string(),
                event_hash: "sha256:event-001".to_string(),
                previous_event_hash: None,
                occurred_at: Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
                transition_type: "add_approval".to_string(),
                envelope_id: "approval-transfer-001".to_string(),
                previous_status: "PARTIALLY_APPROVED".to_string(),
                next_status: "APPROVED".to_string(),
                previous_binding_hash: None,
                next_binding_hash: Some("sha256:binding-001".to_string()),
                envelope_version: 2,
            }],
            chain_head: Some("sha256:event-001".to_string()),
        };

        let value = serde_json::to_value(&history).expect("history should serialize");
        let parsed: ApprovalTransitionHistory =
            serde_json::from_value(value).expect("history should deserialize");
        assert_eq!(parsed, history);
    }

    #[test]
    fn policy_decision_allowed_matches_disposition() {
        let decision = PolicyDecision {
            policy_decision_id: "decision:intent-transfer-001".to_string(),
            allowed: true,
            disposition: Disposition::Allow,
            reason: None,
            policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
            explanation: ExplanationPayload::empty(Disposition::Allow),
            governed_decision_artifact: GovernedDecisionArtifact {
                decision_id: "decision:intent-transfer-001".to_string(),
                action_intent_ref: "intent-transfer-001".to_string(),
                policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
                disposition: Disposition::Allow,
                asset_ref: "asset:lot-8841".to_string(),
            },
            execution_token: None,
        };
        assert!(decision.allowed);
        assert_eq!(decision.disposition, Disposition::Allow);
    }

    #[test]
    fn replay_artifact_payload_type_labels_are_stable() {
        let payload = ReplayArtifactPayload::ApprovalTransitionHistory(ApprovalTransitionHistory {
            events: Vec::new(),
            chain_head: None,
        });
        assert_eq!(payload.artifact_type(), "approval_transition_history");
    }
}
