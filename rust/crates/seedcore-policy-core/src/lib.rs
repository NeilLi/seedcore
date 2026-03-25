//! Deterministic policy decision kernel for SeedCore.
//!
//! This crate will own frozen decision input evaluation, disposition
//! computation, explanation payload construction, and governed decision
//! artifacts for Restricted Custody Transfer and follow-on workflows.

pub use seedcore_kernel_types::Placeholder as KernelPlaceholder;

/// Workspace placeholder function.
pub fn placeholder() -> &'static str {
    "seedcore-policy-core"
}
