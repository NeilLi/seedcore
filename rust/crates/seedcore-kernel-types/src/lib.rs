//! Shared Rust-native contract types for SeedCore's authority-bearing kernel.
//!
//! This crate is intended to become the source of truth for strict artifact
//! types such as `ActionIntent`, `TransferApprovalEnvelope`, `PolicyDecision`,
//! `ExecutionToken`, `PolicyReceipt`, `TransitionReceipt`, and
//! `EvidenceBundle`.
//!
//! The initial scaffold defines only a minimal placeholder so the workspace can
//! compile while the full API described in the Rust workspace proposal is
//! implemented incrementally.

/// Workspace placeholder type.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Placeholder;
