//! Execution-token kernel for SeedCore.
//!
//! This crate will own token claims, minting, verification, TTL checks, and
//! scope enforcement.

pub use seedcore_kernel_types::Placeholder as KernelPlaceholder;

/// Workspace placeholder function.
pub fn placeholder() -> &'static str {
    "seedcore-token-core"
}
