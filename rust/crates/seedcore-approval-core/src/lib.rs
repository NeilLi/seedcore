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
    #[error("binding_hash_failed:{0}")]
    BindingHashFailed(String),
    #[error("unknown_role:{0}")]
    UnknownRole(String),
    #[error("approval_principal_mismatch:{role}")]
    PrincipalMismatch { role: String },
    #[error("role_already_approved:{0}")]
    RoleAlreadyApproved(String),
    #[error("transition_from_terminal_status")]
    TransitionFromTerminal,
    #[error("envelope_expired")]
    EnvelopeExpired,
    #[error("invalid_expire_transition")]
    InvalidExpireTransition,
    #[error("invalid_successor_envelope_id")]
    InvalidSuccessorEnvelopeId,
    #[error("version_overflow")]
    VersionOverflow,
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

/// Applies one deterministic approval lifecycle transition and returns the next
/// immutable envelope state.
pub fn apply_transition(
    envelope: &TransferApprovalEnvelope,
    transition: ApprovalTransition,
    now: Timestamp,
) -> Result<TransferApprovalEnvelope, ApprovalError> {
    validate_envelope(envelope)?;

    let mut next = envelope.clone();
    match transition {
        ApprovalTransition::AddApproval(approval) => {
            apply_add_approval(&mut next, approval, now)?;
        }
        ApprovalTransition::Revoke(revocation) => {
            apply_revoke(&mut next, revocation)?;
        }
        ApprovalTransition::Expire(expired_at) => {
            apply_expire(&mut next, expired_at, now)?;
        }
        ApprovalTransition::Supersede {
            successor_envelope_id,
        } => {
            apply_supersede(&mut next, successor_envelope_id)?;
        }
    }

    next.version = envelope
        .version
        .checked_add(1)
        .ok_or(ApprovalError::VersionOverflow)?;
    next.approval_binding_hash = Some(approval_binding_hash(&next)?);
    validate_envelope(&next)?;
    Ok(next)
}

fn apply_add_approval(
    envelope: &mut TransferApprovalEnvelope,
    approval: RoleApproval,
    now: Timestamp,
) -> Result<(), ApprovalError> {
    guard_non_terminal(envelope.status)?;
    if now >= envelope.expires_at {
        return Err(ApprovalError::EnvelopeExpired);
    }

    let role = approval.role.clone();
    let candidate = envelope
        .required_approvals
        .iter_mut()
        .find(|entry| entry.role == role)
        .ok_or_else(|| ApprovalError::UnknownRole(approval.role.clone()))?;

    if approval.status != ApprovalStatus::Approved {
        return Err(ApprovalError::InvalidApprovalStatus(approval.role));
    }
    if candidate.principal_ref != approval.principal_ref {
        return Err(ApprovalError::PrincipalMismatch {
            role: candidate.role.clone(),
        });
    }
    if candidate.status == ApprovalStatus::Approved {
        return Err(ApprovalError::RoleAlreadyApproved(candidate.role.clone()));
    }

    candidate.status = ApprovalStatus::Approved;
    candidate.approved_at = approval.approved_at.or(Some(now));
    if !approval.approval_ref.trim().is_empty() {
        candidate.approval_ref = approval.approval_ref;
    }

    envelope.status = recompute_envelope_status(&envelope.required_approvals);
    Ok(())
}

fn apply_revoke(
    envelope: &mut TransferApprovalEnvelope,
    revocation: RevocationRecord,
) -> Result<(), ApprovalError> {
    guard_non_terminal(envelope.status)?;
    require_non_empty(&revocation.revoked_by, "revoked_by")?;
    require_non_empty(&revocation.reason, "reason")?;
    envelope.status = ApprovalStatus::Revoked;
    Ok(())
}

fn apply_expire(
    envelope: &mut TransferApprovalEnvelope,
    expired_at: Timestamp,
    now: Timestamp,
) -> Result<(), ApprovalError> {
    guard_non_terminal(envelope.status)?;
    if expired_at < envelope.created_at {
        return Err(ApprovalError::InvalidExpireTransition);
    }
    if now < envelope.expires_at && expired_at < envelope.expires_at {
        return Err(ApprovalError::InvalidExpireTransition);
    }
    envelope.status = ApprovalStatus::Expired;
    Ok(())
}

fn apply_supersede(
    envelope: &mut TransferApprovalEnvelope,
    successor_envelope_id: String,
) -> Result<(), ApprovalError> {
    guard_non_terminal(envelope.status)?;
    if successor_envelope_id.trim().is_empty()
        || successor_envelope_id == envelope.approval_envelope_id
    {
        return Err(ApprovalError::InvalidSuccessorEnvelopeId);
    }
    envelope.status = ApprovalStatus::Superseded;
    Ok(())
}

fn guard_non_terminal(status: ApprovalStatus) -> Result<(), ApprovalError> {
    if status.is_terminal() {
        Err(ApprovalError::TransitionFromTerminal)
    } else {
        Ok(())
    }
}

fn recompute_envelope_status(approvals: &[RoleApproval]) -> ApprovalStatus {
    let approved_count = approvals
        .iter()
        .filter(|approval| approval.status == ApprovalStatus::Approved)
        .count();
    if approved_count == 0 {
        ApprovalStatus::Pending
    } else if approved_count == approvals.len() {
        ApprovalStatus::Approved
    } else {
        ApprovalStatus::PartiallyApproved
    }
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
        assert_eq!(
            error,
            ApprovalError::DuplicateRole("FACILITY_MANAGER".to_string())
        );
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

    fn sample_pending_envelope() -> TransferApprovalEnvelope {
        let mut envelope = sample_envelope();
        envelope.status = ApprovalStatus::Pending;
        envelope.required_approvals[0].status = ApprovalStatus::Pending;
        envelope.required_approvals[0].approved_at = None;
        envelope.required_approvals[1].status = ApprovalStatus::Pending;
        envelope.required_approvals[1].approved_at = None;
        envelope.approval_binding_hash = None;
        envelope
    }

    #[test]
    fn apply_transition_add_approval_advances_status_and_sets_binding_hash() {
        let envelope = sample_pending_envelope();
        let now = Timestamp::from_str("2026-04-02T08:00:10Z").unwrap();
        let partially = apply_transition(
            &envelope,
            ApprovalTransition::AddApproval(RoleApproval {
                role: "FACILITY_MANAGER".to_string(),
                principal_ref: "principal:facility_mgr_001".to_string(),
                status: ApprovalStatus::Approved,
                approved_at: None,
                approval_ref: "approval:facility_mgr_001".to_string(),
            }),
            now.clone(),
        )
        .expect("first transition should succeed");
        assert_eq!(partially.status, ApprovalStatus::PartiallyApproved);
        assert!(partially.approval_binding_hash.is_some());

        let approved = apply_transition(
            &partially,
            ApprovalTransition::AddApproval(RoleApproval {
                role: "QUALITY_INSPECTOR".to_string(),
                principal_ref: "principal:quality_insp_017".to_string(),
                status: ApprovalStatus::Approved,
                approved_at: None,
                approval_ref: "approval:quality_insp_017".to_string(),
            }),
            Timestamp::from_str("2026-04-02T08:00:12Z").unwrap(),
        )
        .expect("second transition should succeed");
        assert_eq!(approved.status, ApprovalStatus::Approved);
        assert!(approved.approval_binding_hash.is_some());
    }

    #[test]
    fn apply_transition_rejects_unknown_approval_role() {
        let envelope = sample_pending_envelope();
        let error = apply_transition(
            &envelope,
            ApprovalTransition::AddApproval(RoleApproval {
                role: "UNKNOWN_ROLE".to_string(),
                principal_ref: "principal:any".to_string(),
                status: ApprovalStatus::Approved,
                approved_at: None,
                approval_ref: "approval:any".to_string(),
            }),
            Timestamp::from_str("2026-04-02T08:00:10Z").unwrap(),
        )
        .expect_err("unknown role should fail");
        assert_eq!(
            error,
            ApprovalError::UnknownRole("UNKNOWN_ROLE".to_string())
        );
    }

    #[test]
    fn apply_transition_revoke_moves_envelope_to_terminal_status() {
        let envelope = sample_pending_envelope();
        let revoked = apply_transition(
            &envelope,
            ApprovalTransition::Revoke(RevocationRecord {
                revoked_by: "principal:security_officer_009".to_string(),
                revoked_at: Timestamp::from_str("2026-04-02T08:00:20Z").unwrap(),
                reason: "tamper_flag".to_string(),
            }),
            Timestamp::from_str("2026-04-02T08:00:20Z").unwrap(),
        )
        .expect("revoke should succeed");
        assert_eq!(revoked.status, ApprovalStatus::Revoked);
        assert!(revoked.approval_binding_hash.is_some());
    }

    #[test]
    fn apply_transition_expire_rejects_before_expiry_window() {
        let envelope = sample_pending_envelope();
        let error = apply_transition(
            &envelope,
            ApprovalTransition::Expire(Timestamp::from_str("2026-04-02T08:01:00Z").unwrap()),
            Timestamp::from_str("2026-04-02T08:01:00Z").unwrap(),
        )
        .expect_err("premature expire should fail");
        assert_eq!(error, ApprovalError::InvalidExpireTransition);
    }

    #[test]
    fn apply_transition_supersede_sets_terminal_status() {
        let envelope = sample_pending_envelope();
        let superseded = apply_transition(
            &envelope,
            ApprovalTransition::Supersede {
                successor_envelope_id: "approval-transfer-002".to_string(),
            },
            Timestamp::from_str("2026-04-02T08:00:30Z").unwrap(),
        )
        .expect("supersede should succeed");
        assert_eq!(superseded.status, ApprovalStatus::Superseded);
        assert!(superseded.approval_binding_hash.is_some());
    }
}
