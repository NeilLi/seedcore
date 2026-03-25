//! Approval lifecycle kernel for SeedCore.
//!
//! This crate will own `TransferApprovalEnvelope` validation, lifecycle
//! transitions, revocation, expiry, supersession, and approval binding-hash
//! semantics.

pub use seedcore_kernel_types::Placeholder as KernelPlaceholder;

/// Workspace placeholder function.
pub fn placeholder() -> &'static str {
    "seedcore-approval-core"
}
