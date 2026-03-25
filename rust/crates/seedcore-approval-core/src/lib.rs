//! Approval lifecycle kernel for SeedCore.
//!
//! This crate will own `TransferApprovalEnvelope` validation, lifecycle
//! transitions, revocation, expiry, supersession, and approval binding-hash
//! semantics.

use seedcore_kernel_types::{
    ApprovalStatus, ArtifactHash, RevocationRecord, RoleApproval, Timestamp,
    TransferApprovalEnvelope, TransferContext,
};
use seedcore_proof_core::hash_artifact;
use serde::Serialize;
use thiserror::Error;

/// Future lifecycle transition input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ApprovalTransition {
    AddApproval(RoleApproval),
    Revoke(RevocationRecord),
    Expire(Timestamp),
    Supersede { successor_envelope_id: String },
}

/// Approval-core validation and hashing errors.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum ApprovalError {
    #[error("missing_field:{0}")]
    MissingField(&'static str),
    #[error("empty_required_approvals")]
    EmptyRequiredApprovals,
    #[error("duplicate_role:{0}")]
    DuplicateRole(String),
    #[error("invalid_approval_status:{0}")]
    InvalidApprovalStatus(String),
    #[error("expires_at_not_after_created_at")]
    InvalidWindow,
    #[error("terminal_envelope_requires_terminal_status")]
    InvalidTerminalState,
    #[error("binding_hash_failed:{0}")]
    BindingHashFailed(String),
}

/// Validates the approval envelope's core invariants.
pub fn validate_envelope(envelope: &TransferApprovalEnvelope) -> Result<(), ApprovalError> {
    require_non_empty(&envelope.approval_envelope_id, "approval_envelope_id")?;
    require_non_empty(&envelope.workflow_type, "workflow_type")?;
    require_non_empty(&envelope.asset_ref, "asset_ref")?;
    require_non_empty(&envelope.from_custodian_ref, "from_custodian_ref")?;
    require_non_empty(&envelope.to_custodian_ref, "to_custodian_ref")?;
    require_non_empty(&envelope.policy_snapshot_ref, "policy_snapshot_ref")?;

    if envelope.required_approvals.is_empty() {
        return Err(ApprovalError::EmptyRequiredApprovals);
    }

    let mut seen_roles = std::collections::BTreeSet::new();
    for approval in &envelope.required_approvals {
        require_non_empty(&approval.role, "required_approvals.role")?;
        require_non_empty(&approval.principal_ref, "required_approvals.principal_ref")?;
        require_non_empty(&approval.approval_ref, "required_approvals.approval_ref")?;

        if !seen_roles.insert(approval.role.clone()) {
            return Err(ApprovalError::DuplicateRole(approval.role.clone()));
        }

        match approval.status {
            ApprovalStatus::Approved => {
                if approval.approved_at.is_none() {
                    return Err(ApprovalError::InvalidApprovalStatus(approval.role.clone()));
                }
            }
            ApprovalStatus::Pending | ApprovalStatus::PartiallyApproved => {}
            other => {
                return Err(ApprovalError::InvalidApprovalStatus(format!(
                    "{}:{}",
                    approval.role,
                    serde_status_label(other)
                )));
            }
        }
    }

    if envelope.expires_at <= envelope.created_at {
        return Err(ApprovalError::InvalidWindow);
    }

    if envelope.status.is_terminal() && envelope.approval_binding_hash.is_none() {
        return Err(ApprovalError::InvalidTerminalState);
    }

    Ok(())
}

/// Computes a deterministic approval binding hash, excluding the binding hash
/// field itself from the canonicalized payload.
pub fn approval_binding_hash(
    envelope: &TransferApprovalEnvelope,
) -> Result<ArtifactHash, ApprovalError> {
    validate_envelope(envelope)?;
    let binding_view = BindingHashEnvelopeView::from(envelope);
    hash_artifact(&binding_view)
        .map_err(|error| ApprovalError::BindingHashFailed(error.to_string()))
}

fn require_non_empty(value: &str, field_name: &'static str) -> Result<(), ApprovalError> {
    if value.trim().is_empty() {
        return Err(ApprovalError::MissingField(field_name));
    }
    Ok(())
}

fn serde_status_label(status: ApprovalStatus) -> &'static str {
    match status {
        ApprovalStatus::Pending => "PENDING",
        ApprovalStatus::PartiallyApproved => "PARTIALLY_APPROVED",
        ApprovalStatus::Approved => "APPROVED",
        ApprovalStatus::Expired => "EXPIRED",
        ApprovalStatus::Revoked => "REVOKED",
        ApprovalStatus::Superseded => "SUPERSEDED",
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct BindingHashEnvelopeView {
    approval_envelope_id: String,
    workflow_type: String,
    status: ApprovalStatus,
    asset_ref: String,
    lot_id: Option<String>,
    from_custodian_ref: String,
    to_custodian_ref: String,
    transfer_context: TransferContext,
    required_approvals: Vec<RoleApproval>,
    policy_snapshot_ref: String,
    expires_at: Timestamp,
    created_at: Timestamp,
    version: u32,
}

impl From<&TransferApprovalEnvelope> for BindingHashEnvelopeView {
    fn from(value: &TransferApprovalEnvelope) -> Self {
        Self {
            approval_envelope_id: value.approval_envelope_id.clone(),
            workflow_type: value.workflow_type.clone(),
            status: value.status,
            asset_ref: value.asset_ref.clone(),
            lot_id: value.lot_id.clone(),
            from_custodian_ref: value.from_custodian_ref.clone(),
            to_custodian_ref: value.to_custodian_ref.clone(),
            transfer_context: value.transfer_context.clone(),
            required_approvals: value.required_approvals.clone(),
            policy_snapshot_ref: value.policy_snapshot_ref.clone(),
            expires_at: value.expires_at.clone(),
            created_at: value.created_at.clone(),
            version: value.version,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;

    fn sample_envelope() -> TransferApprovalEnvelope {
        TransferApprovalEnvelope {
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
            required_approvals: vec![
                RoleApproval {
                    role: "FACILITY_MANAGER".to_string(),
                    principal_ref: "principal:facility_mgr_001".to_string(),
                    status: ApprovalStatus::Approved,
                    approved_at: Some(Timestamp::from_str("2026-04-02T08:00:05Z").unwrap()),
                    approval_ref: "approval:facility_mgr_001".to_string(),
                },
                RoleApproval {
                    role: "QUALITY_INSPECTOR".to_string(),
                    principal_ref: "principal:quality_insp_017".to_string(),
                    status: ApprovalStatus::Approved,
                    approved_at: Some(Timestamp::from_str("2026-04-02T08:00:12Z").unwrap()),
                    approval_ref: "approval:quality_insp_017".to_string(),
                },
            ],
            approval_binding_hash: Some(ArtifactHash::sha256_hex("placeholder")),
            policy_snapshot_ref: "snapshot:pkg-prod-2026-04-02".to_string(),
            expires_at: Timestamp::from_str("2026-04-02T08:05:00Z").unwrap(),
            created_at: Timestamp::from_str("2026-04-02T08:00:00Z").unwrap(),
            version: 1,
        }
    }

    #[test]
    fn validate_envelope_accepts_valid_approved_envelope() {
        let envelope = sample_envelope();
        assert_eq!(validate_envelope(&envelope), Ok(()));
    }

    #[test]
    fn validate_envelope_rejects_duplicate_roles() {
        let mut envelope = sample_envelope();
        envelope.required_approvals[1].role = "FACILITY_MANAGER".to_string();
        let error = validate_envelope(&envelope).expect_err("duplicate roles should fail");
        assert_eq!(error, ApprovalError::DuplicateRole("FACILITY_MANAGER".to_string()));
    }

    #[test]
    fn validate_envelope_rejects_approved_without_timestamp() {
        let mut envelope = sample_envelope();
        envelope.required_approvals[0].approved_at = None;
        let error = validate_envelope(&envelope).expect_err("approved entry should need timestamp");
        assert_eq!(
            error,
            ApprovalError::InvalidApprovalStatus("FACILITY_MANAGER".to_string())
        );
    }

    #[test]
    fn approval_binding_hash_is_deterministic_and_ignores_existing_hash_field() {
        let mut envelope = sample_envelope();
        let first = approval_binding_hash(&envelope).expect("hash should compute");
        envelope.approval_binding_hash = Some(ArtifactHash::sha256_hex("different-existing-hash"));
        let second = approval_binding_hash(&envelope).expect("hash should remain stable");
        assert_eq!(first, second);
        assert_eq!(first.algorithm, "sha256");
        assert_eq!(first.value.len(), 64);
    }
}
