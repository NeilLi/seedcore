//! Proof integrity kernel for SeedCore.
//!
//! This crate will own canonical serialization, hashing, signing abstractions,
//! artifact verification, and replay-chain verification.

pub use seedcore_kernel_types::Placeholder as KernelPlaceholder;

/// Workspace placeholder function.
pub fn placeholder() -> &'static str {
    "seedcore-proof-core"
}
