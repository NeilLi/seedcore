//! Shared test harness support for the SeedCore Rust kernel workspace.
//!
//! This crate will load deterministic fixtures, assert golden outputs, and
//! provide invalid-artifact builders for proof, approval, policy, and token
//! tests.

/// Workspace placeholder function.
pub fn placeholder() -> &'static str {
    "seedcore-kernel-testkit"
}
