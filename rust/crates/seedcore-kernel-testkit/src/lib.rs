//! Shared test harness support for the SeedCore Rust kernel workspace.
//!
//! This crate will load deterministic fixtures, assert golden outputs, and
//! provide invalid-artifact builders for proof, approval, policy, and token
//! tests.

use seedcore_kernel_types::TransferApprovalEnvelope;
use seedcore_policy_core::{
    AuthorityGraphSummary, BreakGlassContext, FrozenAssetState, PolicyEvaluation,
    TelemetrySummary,
};
use seedcore_token_core::ExecutionToken;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Minimal action-intent fields required by the fixture harness.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActionIntentFixture {
    pub action_intent_ref: String,
    pub action_type: String,
    pub principal_agent_id: Option<String>,
    pub source_registration_id: Option<String>,
    pub registration_decision_id: Option<String>,
    pub endpoint_id: Option<String>,
}

/// Explicit expected execution-token assertion policy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExpectedExecutionToken {
    NotProvided,
    ExpectedNull,
    ExpectedSome(ExecutionToken),
}

/// Loaded transfer scenario fixture bundle.
#[derive(Debug, Clone, PartialEq)]
pub struct TransferScenarioFixture {
    pub dir: PathBuf,
    pub action_intent: ActionIntentFixture,
    pub approval_envelope: TransferApprovalEnvelope,
    pub asset_state: FrozenAssetState,
    pub telemetry_summary: TelemetrySummary,
    pub authority_graph_summary: AuthorityGraphSummary,
    pub break_glass: Option<BreakGlassContext>,
    pub expected_policy_evaluation: Option<PolicyEvaluation>,
    pub expected_execution_token: ExpectedExecutionToken,
    pub expected_verification_report: Option<Value>,
}

/// Fixture loading and parsing errors.
#[derive(Debug, Error)]
pub enum FixtureError {
    #[error("read_failed:{path}:{source}")]
    ReadFailed {
        path: String,
        source: std::io::Error,
    },
    #[error("json_parse_failed:{path}:{source}")]
    JsonParseFailed {
        path: String,
        source: serde_json::Error,
    },
}

/// Loads one transfer fixture directory into a canonical scenario bundle.
pub fn load_transfer_fixture(dir: impl AsRef<Path>) -> Result<TransferScenarioFixture, FixtureError> {
    let dir = dir.as_ref().to_path_buf();
    Ok(TransferScenarioFixture {
        action_intent: read_json_file(dir.join("input.action_intent.json"))?,
        approval_envelope: read_json_file(dir.join("input.approval_envelope.json"))?,
        asset_state: read_json_file(dir.join("input.asset_state.json"))?,
        telemetry_summary: read_json_file(dir.join("input.telemetry_summary.json"))?,
        authority_graph_summary: read_json_file(dir.join("input.authority_graph_summary.json"))?,
        break_glass: read_optional_json_file(dir.join("input.break_glass.json"))?,
        expected_policy_evaluation: read_optional_json_file(dir.join("expected.policy_evaluation.json"))?,
        expected_execution_token: read_expected_execution_token(dir.join("expected.execution_token.json"))?,
        expected_verification_report: read_optional_json_file(dir.join("expected.verification_report.json"))?,
        dir,
    })
}

fn read_expected_execution_token(path: impl AsRef<Path>) -> Result<ExpectedExecutionToken, FixtureError> {
    let path = path.as_ref();
    if !path.exists() {
        return Ok(ExpectedExecutionToken::NotProvided);
    }

    let value: Value = read_json_file(path)?;
    if value.is_null() {
        return Ok(ExpectedExecutionToken::ExpectedNull);
    }
    let token = serde_json::from_value::<ExecutionToken>(value).map_err(|source| {
        FixtureError::JsonParseFailed {
            path: path.display().to_string(),
            source,
        }
    })?;
    Ok(ExpectedExecutionToken::ExpectedSome(token))
}

fn read_json_file<T: for<'de> Deserialize<'de>>(path: impl AsRef<Path>) -> Result<T, FixtureError> {
    let path = path.as_ref();
    let contents = fs::read_to_string(path).map_err(|source| FixtureError::ReadFailed {
        path: path.display().to_string(),
        source,
    })?;
    serde_json::from_str(&contents).map_err(|source| FixtureError::JsonParseFailed {
        path: path.display().to_string(),
        source,
    })
}

fn read_optional_json_file<T: for<'de> Deserialize<'de>>(
    path: impl AsRef<Path>,
) -> Result<Option<T>, FixtureError> {
    let path = path.as_ref();
    if !path.exists() {
        return Ok(None);
    }
    read_json_file(path).map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_dir(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/transfers")
            .join(name)
    }

    #[test]
    fn loads_allow_case_with_expected_token_object() {
        let fixture = load_transfer_fixture(fixture_dir("allow_case"))
            .expect("allow_case should load");
        assert!(fixture.expected_policy_evaluation.is_some());
        assert!(matches!(
            fixture.expected_execution_token,
            ExpectedExecutionToken::ExpectedSome(_)
        ));
    }

    #[test]
    fn loads_deny_case_with_expected_token_null() {
        let fixture = load_transfer_fixture(fixture_dir("deny_missing_approval"))
            .expect("deny_missing_approval should load");
        assert!(matches!(
            fixture.expected_execution_token,
            ExpectedExecutionToken::ExpectedNull
        ));
    }
}
