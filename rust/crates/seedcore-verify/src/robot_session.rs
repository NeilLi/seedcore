//! Offline, host-signed controller-simulation evidence. Never hardware acceptance.
use seedcore_kernel_types::{ExecutionToken, Timestamp, TrustBundle};
use seedcore_proof_core::{hash_artifact, verify_signed_artifact, SignedArtifact};
use seedcore_token_core::{verify_token, TokenVerificationReport};
use serde_json::{json, Value};
use std::path::Path;

fn token_denied(error: &str) -> TokenVerificationReport {
    TokenVerificationReport {
        verified: false,
        error_code: Some(error.into()),
        details: vec![],
    }
}

pub(super) fn verify_trusted_token(
    token: &ExecutionToken,
    bundle: &TrustBundle,
    now: Timestamp,
) -> TokenVerificationReport {
    let Some(key) = token.signature.key_ref.as_deref() else {
        return token_denied("missing_key_ref");
    };
    let Some(entry) = bundle.trusted_keys.get(key) else {
        return token_denied("key_not_found");
    };
    if bundle.revoked_keys.iter().any(|k| k == key) {
        return token_denied("revoked_signer_key");
    }
    if token.signature.signing_scheme != "ed25519" || entry.key_algorithm != "ed25519" {
        return token_denied("unsupported_signing_scheme");
    }
    if token.issued_at > now || token.valid_until <= token.issued_at {
        return token_denied("invalid_validity_window");
    }
    if let Some(endpoint) = &entry.endpoint_id {
        if token.constraints.endpoint_id.as_ref() != Some(endpoint) {
            return token_denied("endpoint_binding_mismatch");
        }
    }
    verify_token(token, &super::TrustBundleResolver::from_bundle(bundle), now)
}

fn str_field<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing_or_invalid:{key}"))
}

fn check(
    receipt: &SignedArtifact<Value>,
    spec: &Value,
    trust: &TrustBundle,
    token_hash: &str,
) -> Result<(), String> {
    let payload = &receipt.artifact;
    let fields = [
        "schema_version",
        "profile",
        "capture_kind",
        "session_id",
        "endpoint_id",
        "boot_nonce",
        "principal_id",
        "policy_sha256",
        "model_sha256",
        "runtime_sha256",
        "spec_sha256",
        "token_id",
        "intent_id",
        "token_sha256",
        "outcome",
        "capture_complete",
        "events",
    ];
    let object = payload.as_object().ok_or("invalid_receipt_payload")?;
    if object.len() != fields.len() || fields.iter().any(|k| !object.contains_key(*k)) {
        return Err("receipt_schema_mismatch".into());
    }
    if str_field(payload, "schema_version")? != "seedcore.fast-spine.receipt.v1"
        || str_field(payload, "profile")? != "simulation_only"
        || str_field(payload, "capture_kind")? != "simulated_controller_state"
        || !str_field(payload, "endpoint_id")?.starts_with("spine_sim://")
        || str_field(spec, "profile")? != "simulation_only"
        || str_field(spec, "schema_version")? != "seedcore.fast-spine.session.v1"
    {
        return Err("unsupported_capture_profile".into());
    }
    for field in [
        "session_id",
        "endpoint_id",
        "boot_nonce",
        "principal_id",
        "policy_sha256",
        "model_sha256",
    ] {
        if str_field(payload, field)? != str_field(spec, field)? {
            return Err(format!("binding_mismatch:{field}"));
        }
    }
    if str_field(payload, "token_sha256")? != token_hash
        || str_field(payload, "spec_sha256")?
            != hash_artifact(spec).map_err(|e| e.to_string())?.value
    {
        return Err("token_or_spec_binding_mismatch".into());
    }
    if payload["capture_complete"] != true {
        return Err("capture_incomplete".into());
    }
    let outcome = str_field(payload, "outcome")?;
    if ![
        "completed",
        "cancelled",
        "revoked",
        "local_stop",
        "clock_rollback",
        "session_deadline",
        "stale_authority",
        "authority_unavailable",
        "stale_command",
        "lost_heartbeat",
        "capture_overflow",
        "watchdog_fault",
    ]
    .contains(&outcome)
    {
        return Err("invalid_outcome".into());
    }
    let key = receipt
        .signature
        .key_ref
        .as_deref()
        .ok_or("missing_key_ref")?;
    let entry = trust.trusted_keys.get(key).ok_or("key_not_found")?;
    if trust.revoked_keys.iter().any(|k| k == key) {
        return Err("revoked_signer_key".into());
    }
    if receipt.signature.signer_type != "service"
        || receipt.signature.signer_id != key
        || receipt.signature.signing_scheme != "ed25519"
        || entry.key_algorithm != "ed25519"
        || receipt.signature.attestation_level != "baseline"
    {
        return Err("invalid_simulation_signer".into());
    }
    if let Some(endpoint) = &entry.endpoint_id {
        if str_field(payload, "endpoint_id")? != endpoint {
            return Err("signer_endpoint_mismatch".into());
        }
    }
    let report = verify_signed_artifact(receipt, &super::TrustBundleResolver::from_bundle(trust));
    if !report.verified {
        return Err(report.error_code.unwrap_or("signature_failed".into()));
    }
    let events = payload["events"].as_array().ok_or("missing_events")?;
    if !(3..=2048).contains(&events.len())
        || events[0]["kind"] != "opened"
        || events.last().unwrap()["kind"] != "closed"
    {
        return Err("missing_start_end_evidence".into());
    }
    if str_field(events.last().unwrap(), "reason")? != outcome {
        return Err("conflicting_outcome".into());
    }
    let lower = spec["lower_rad"].as_array().ok_or("missing_lower_bounds")?;
    let upper = spec["upper_rad"].as_array().ok_or("missing_upper_bounds")?;
    if !(1..=3).contains(&lower.len()) || lower.len() != upper.len() {
        return Err("invalid_joint_dimensions".into());
    }
    let mut previous = 0;
    for (index, event) in events.iter().enumerate() {
        if event["sequence"].as_u64() != Some(index as u64) {
            return Err("sequence_gap_or_replay".into());
        }
        let time = event["t_ms"].as_u64().ok_or("invalid_capture_time")?;
        if time < previous || time > 6000 {
            return Err("invalid_capture_time".into());
        }
        previous = time;
        let positions = event["positions_urad"]
            .as_array()
            .ok_or("missing_observations")?;
        if positions.len() != lower.len() {
            return Err("observation_dimension_mismatch".into());
        }
        for (i, value) in positions.iter().enumerate() {
            let q = value.as_i64().ok_or("invalid_integer_observation")? as f64;
            let low = lower[i].as_f64().ok_or("invalid_lower_bound")? * 1e6 - 1.;
            let high = upper[i].as_f64().ok_or("invalid_upper_bound")? * 1e6 + 1.;
            if !(low..=high).contains(&q) {
                return Err("observation_outside_envelope".into());
            }
        }
    }
    if outcome == "completed" {
        let applied = events
            .iter()
            .rev()
            .find(|e| e["kind"] == "applied")
            .ok_or("missing_applied_evidence")?;
        if !events.iter().any(|e| e["kind"] == "queued")
            || events.last().unwrap()["positions_urad"] != applied["positions_urad"]
        {
            return Err("missing_or_conflicting_motion_evidence".into());
        }
    }
    Ok(())
}

pub(super) fn verify_session(
    artifact_path: &Path,
    spec_path: &Path,
    trust_path: &Path,
    token_hash: &str,
) -> Result<Value, String> {
    let receipt: SignedArtifact<Value> = super::read_json_file(artifact_path)?;
    let spec: Value = super::read_json_file(spec_path)?;
    let trust = super::load_trust_bundle(trust_path)?;
    let checked = check(&receipt, &spec, &trust, token_hash);
    let verified = checked.is_ok();
    let disposition = if !verified {
        "quarantine"
    } else if receipt.artifact["outcome"] == "completed" {
        "verified_completed"
    } else {
        "verified_interrupted"
    };
    Ok(
        json!({"verified":verified,"scope":"simulation_only","physical_acceptance":false,
              "disposition":disposition,"error":checked.err()}),
    )
}
