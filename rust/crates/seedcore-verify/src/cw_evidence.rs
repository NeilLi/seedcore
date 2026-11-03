//! Independent, read-only CW-G02 verification. No Python or simulator calls.
use super::cw_json::{self, MAX_ARTIFACT, MAX_BUNDLE};
use base64::{engine::general_purpose::STANDARD, Engine};
use chrono::{DateTime, Datelike, Utc};
use seedcore_kernel_types::{ArtifactHash, SignatureEnvelope, TrustBundle};
use seedcore_proof_core::verify_detached_signature;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::path::Path;

type Result<T> = std::result::Result<T, String>;
const PROFILE: &str = "seedcore.cw-g01.native-admission.v1";
const MODEL: &str = "2478a5c6f22e4d46f9f0c130ea2505b16394d699564ffb3007658fa26300fab5";
const SCOPE: &str = "local_simulation_only";
const ARTIFACTS: &[&str] = &[
    "token",
    "candidate",
    "source",
    "parameters",
    "review",
    "executor",
    "capture",
];
const CLAIMS: &[&str] = &[
    "token_id",
    "intent_id",
    "issued_at",
    "valid_until",
    "contract_version",
    "constraints",
    "execution_preconditions",
];
const CONSTRAINTS: &[&str] = &[
    "action_type",
    "target_zone",
    "asset_id",
    "principal_agent_id",
    "source_registration_id",
    "registration_decision_id",
    "endpoint_id",
    "plan_dag_hash",
    "payload_hash",
];
const PRECONDITIONS: &[&str] = &[
    "resource_state_hash",
    "approval_transition_head",
    "context_token",
    "plan_dag_hash",
    "payload_hash",
    "endpoint_id",
];
const SIGNATURE: &[&str] = &[
    "signer_type",
    "signer_id",
    "signing_scheme",
    "key_ref",
    "attestation_level",
    "signature",
];
const BINDING: &[&str] = &[
    "revisionDigest",
    "assemblyDigest",
    "catalogDigest",
    "drcDigest",
    "modelDigest",
    "authorityEpoch",
];

fn require(ok: bool, error: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(error.into())
    }
}
fn object(v: &Value, fields: &[&str]) -> Result<()> {
    let map = v.as_object().ok_or("object_required")?;
    require(
        map.len() == fields.len() && fields.iter().all(|k| map.contains_key(*k)),
        "closed_schema_mismatch",
    )
}
fn text(v: &Value) -> Result<&str> {
    v.as_str().ok_or_else(|| "string_required".into())
}
fn array(v: &Value) -> Result<&[Value]> {
    v.as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| "array_required".into())
}
fn number(v: &Value) -> Result<f64> {
    let n = v.as_f64().ok_or("number_required")?;
    require(n.is_finite(), "nonfinite_number")?;
    Ok(n)
}
fn integer(v: &Value) -> Result<u64> {
    v.as_u64().ok_or_else(|| "unsigned_integer_required".into())
}
fn range(v: &Value, low: f64, high: f64, positive: bool) -> Result<()> {
    let n = number(v)?;
    require(
        n >= low && n <= high && (!positive || n > 0.),
        "numeric_range_mismatch",
    )
}
fn is_digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn digest_field(v: &Value) -> Result<()> {
    require(is_digest(text(v)?), "invalid_digest")
}
fn is_name(s: &str, extra: &[u8], max: usize) -> bool {
    !s.is_empty()
        && s.len() <= max
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || extra.contains(&b))
}
fn name(v: &Value) -> Result<()> {
    require(is_name(text(v)?, b"_.:-", 128), "invalid_name")
}
fn endpoint(v: &Value) -> Result<()> {
    let suffix = text(v)?
        .strip_prefix("cw_sim://")
        .ok_or("wrong_endpoint_scope")?;
    require(
        is_name(suffix, b"._/-", 128) && suffix.as_bytes()[0].is_ascii_alphanumeric(),
        "invalid_endpoint",
    )
}
fn prefixed_digest(v: &Value) -> Result<()> {
    require(
        text(v)?
            .strip_prefix("sha256:")
            .map(is_digest)
            .unwrap_or(false),
        "invalid_prefixed_digest",
    )
}
fn without(v: &Value, keys: &[&str]) -> Result<Value> {
    let mut map = v.as_object().ok_or("object_required")?.clone();
    for k in keys {
        map.remove(*k);
    }
    Ok(Value::Object(map))
}
fn equal(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => x.as_f64() == y.as_f64(),
        (Value::Array(x), Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(a, b)| equal(a, b))
        }
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len()
                && x.iter()
                    .all(|(k, v)| y.get(k).map(|b| equal(v, b)).unwrap_or(false))
        }
        _ => a == b,
    }
}

fn binding(v: &Value) -> Result<()> {
    object(v, BINDING)?;
    for field in &BINDING[..5] {
        digest_field(&v[*field])?;
    }
    require(
        integer(&v["authorityEpoch"])? <= 9_007_199_254_740_991,
        "invalid_epoch",
    )
}
fn context(v: &Value) -> Result<()> {
    object(
        v,
        &[
            "schemaVersion",
            "requestId",
            "instanceId",
            "endpointId",
            "admittedAt",
            "candidateDigest",
            "binding",
            "sourceDigest",
            "executorDigest",
            "reviewDigest",
            "tokenDigest",
            "payloadHash",
            "tokenKeyRef",
            "receiptKeyRef",
        ],
    )?;
    require(
        v["schemaVersion"] == "seedcore.cw-g02.expected.v1",
        "expected_context_schema_mismatch",
    )?;
    require(
        is_name(text(&v["requestId"])?, b"_-", 64),
        "invalid_request_id",
    )?;
    let instance = text(&v["instanceId"])?;
    require(
        instance.len() == 32
            && instance
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "invalid_instance_id",
    )?;
    endpoint(&v["endpointId"])?;
    text(&v["admittedAt"])?;
    binding(&v["binding"])?;
    for field in [
        "candidateDigest",
        "sourceDigest",
        "executorDigest",
        "reviewDigest",
        "tokenDigest",
    ] {
        digest_field(&v[field])?;
    }
    prefixed_digest(&v["payloadHash"])?;
    name(&v["tokenKeyRef"])?;
    name(&v["receiptKeyRef"])
}
fn candidate(v: &Value) -> Result<()> {
    object(
        v,
        &[
            "schemaVersion",
            "scope",
            "physicalAcceptance",
            "executionAuthority",
            "endpointId",
            "binding",
            "runtime",
            "behavior",
            "candidateDigest",
        ],
    )?;
    require(
        v["schemaVersion"] == "seedcore.cw-g01.candidate.v1"
            && v["scope"] == "offline_simulation_only"
            && v["physicalAcceptance"] == false
            && v["executionAuthority"] == "none",
        "candidate_scope_mismatch",
    )?;
    endpoint(&v["endpointId"])?;
    require(
        !text(&v["endpointId"])?
            .split('/')
            .any(|p| p == "." || p == ".."),
        "invalid_endpoint_path",
    )?;
    binding(&v["binding"])?;
    digest_field(&v["candidateDigest"])?;
    let r = &v["runtime"];
    object(
        r,
        &[
            "profile",
            "engineVersion",
            "wasmSha256",
            "timestepSeconds",
            "actuatorMode",
            "positionKp",
        ],
    )?;
    require(
        r["profile"] == "seedcore.cw-s02.mujoco-wasm-st.v1"
            && r["engineVersion"] == "3.15.0"
            && r["wasmSha256"]
                == "d59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d"
            && number(&r["timestepSeconds"])? == 0.002
            && r["actuatorMode"] == "position"
            && number(&r["positionKp"])? == 1.,
        "candidate_runtime_mismatch",
    )?;
    let b = &v["behavior"];
    object(
        b,
        &[
            "compiler",
            "gestureDigest",
            "totalTicks",
            "durationSeconds",
            "joints",
        ],
    )?;
    require(
        b["compiler"] == "seedcore.cw-s04.hermite.v1",
        "compiler_mismatch",
    )?;
    digest_field(&b["gestureDigest"])?;
    let ticks = integer(&b["totalTicks"])?;
    require(
        (1..=120).contains(&ticks) && number(&b["durationSeconds"])? == ticks as f64 * 0.002,
        "behavior_duration_mismatch",
    )?;
    let joints = array(&b["joints"])?;
    require((1..=3).contains(&joints.len()), "joint_count_mismatch")?;
    let mut ids = BTreeSet::new();
    for j in joints {
        object(
            j,
            &[
                "jointId",
                "lowerRad",
                "upperRad",
                "maxVelocityRadS",
                "maxAccelerationRadS2",
                "requestedMaxVelocityRadS",
                "requestedMaxAccelerationRadS2",
            ],
        )?;
        let id = text(&j["jointId"])?;
        require(
            is_name(id, b"_.-", 80) && ids.insert(id),
            "invalid_or_duplicate_joint_id",
        )?;
        range(&j["lowerRad"], -10., 10., false)?;
        range(&j["upperRad"], -10., 10., false)?;
        range(&j["maxVelocityRadS"], 0., 100., false)?;
        range(&j["maxAccelerationRadS2"], 0., 1000., false)?;
        range(&j["requestedMaxVelocityRadS"], 0., 100., true)?;
        range(&j["requestedMaxAccelerationRadS2"], 0., 1000., true)?;
        require(
            number(&j["lowerRad"])? <= number(&j["upperRad"])?
                && number(&j["maxVelocityRadS"])? <= number(&j["requestedMaxVelocityRadS"])?
                && number(&j["maxAccelerationRadS2"])?
                    <= number(&j["requestedMaxAccelerationRadS2"])?,
            "curve_bounds_mismatch",
        )?;
    }
    require(
        cw_json::hash(&without(v, &["candidateDigest"])?)? == text(&v["candidateDigest"])?,
        "candidate_digest_mismatch",
    )
}
fn review(v: &Value) -> Result<()> {
    object(
        v,
        &[
            "reviewId",
            "candidateDigest",
            "endpointId",
            "assetId",
            "sourceRegistrationId",
            "registrationDecisionId",
            "resourceStateHash",
            "policySnapshot",
            "securityContractHash",
            "scope",
            "reviewedAt",
            "validUntil",
            "revoked",
            "endpointMaxDurationSeconds",
            "operatorMaxDurationSeconds",
            "endpointLimits",
            "operatorLimits",
        ],
    )?;
    for field in [
        "reviewId",
        "assetId",
        "sourceRegistrationId",
        "registrationDecisionId",
        "policySnapshot",
    ] {
        name(&v[field])?;
    }
    digest_field(&v["candidateDigest"])?;
    endpoint(&v["endpointId"])?;
    prefixed_digest(&v["resourceStateHash"])?;
    prefixed_digest(&v["securityContractHash"])?;
    require(
        v["scope"] == "offline_simulation_only" && v["revoked"].is_boolean(),
        "review_scope_mismatch",
    )?;
    text(&v["reviewedAt"])?;
    text(&v["validUntil"])?;
    for field in ["endpointMaxDurationSeconds", "operatorMaxDurationSeconds"] {
        range(&v[field], 0., 1000., true)?;
    }
    for field in ["endpointLimits", "operatorLimits"] {
        let limits = array(&v[field])?;
        require(
            (1..=3).contains(&limits.len()),
            "review_joint_count_mismatch",
        )?;
        for limit in limits {
            object(
                limit,
                &[
                    "jointId",
                    "lowerRad",
                    "upperRad",
                    "maxVelocityRadS",
                    "maxAccelerationRadS2",
                ],
            )?;
            require(
                is_name(text(&limit["jointId"])?, b"_.-", 80),
                "invalid_joint_id",
            )?;
            range(&limit["lowerRad"], -1000., 1000., false)?;
            range(&limit["upperRad"], -1000., 1000., false)?;
            range(&limit["maxVelocityRadS"], 0., 1000., true)?;
            range(&limit["maxAccelerationRadS2"], 0., 1000., true)?;
            require(
                number(&limit["lowerRad"])? < number(&limit["upperRad"])?,
                "empty_joint_limits",
            )?;
        }
    }
    Ok(())
}

/// CW timestamps use explicit RFC 3339 zones and microsecond-or-coarser precision.
/// This matches the service clock precision and avoids chrono/Python truncation differences.
fn time(v: &Value) -> Result<i64> {
    let s = text(v)?;
    let b = s.as_bytes();
    require(b.len() >= 20, "invalid_timestamp")?;
    require(
        [4, 7].iter().all(|i| b[*i] == b'-')
            && [13, 16].iter().all(|i| b[*i] == b':')
            && [b'T', b't'].contains(&b[10])
            && (0..19)
                .filter(|i| ![4, 7, 10, 13, 16].contains(i))
                .all(|i| b[i].is_ascii_digit()),
        "invalid_timestamp",
    )?;
    let zone = if [b'Z', b'z'].contains(b.last().unwrap()) {
        b.len() - 1
    } else {
        let z = b.len() - 6;
        require(
            [b'+', b'-'].contains(&b[z])
                && b[z + 3] == b':'
                && [z + 1, z + 2, z + 4, z + 5]
                    .iter()
                    .all(|i| b[*i].is_ascii_digit()),
            "invalid_timestamp_zone",
        )?;
        z
    };
    require(
        zone >= 19
            && (zone == 19
                || (b[19] == b'.'
                    && (21..=26).contains(&zone)
                    && b[20..zone].iter().all(u8::is_ascii_digit))),
        "invalid_timestamp_precision",
    )?;
    require(
        &b[17..19] < b"60" && &b[..4] != b"0000",
        "unsupported_timestamp_value",
    )?;
    let parsed = DateTime::parse_from_rfc3339(&s.replace('t', "T").replace('z', "Z"))
        .map_err(|_| "invalid_timestamp")?
        .with_timezone(&Utc);
    require(
        (1..=9999).contains(&parsed.year()),
        "invalid_timestamp_year",
    )?;
    Ok(parsed.timestamp_micros())
}

fn signature(
    payload: &Value,
    hash: &Value,
    sig: &Value,
    trust: &Value,
    key: &str,
    purpose: &str,
    endpoint: &str,
) -> Result<()> {
    object(sig, SIGNATURE)?;
    require(
        sig["signer_type"] == "service"
            && sig["signer_id"] == key
            && sig["signing_scheme"] == "ed25519"
            && sig["key_ref"] == key
            && sig["attestation_level"] == "baseline",
        "signature_identity_mismatch",
    )?;
    require(
        !array(&trust["revoked_keys"])?.iter().any(|v| v == key),
        "revoked_signer_key",
    )?;
    let entry = &trust["trusted_keys"][key];
    object(
        entry,
        &[
            "key_ref",
            "key_algorithm",
            "public_key",
            "trust_anchor_type",
            "endpoint_id",
        ],
    )?;
    require(
        entry["key_ref"] == key
            && entry["key_algorithm"] == "ed25519"
            && entry["trust_anchor_type"] == purpose
            && entry["endpoint_id"] == endpoint,
        "trust_purpose_endpoint_mismatch",
    )?;
    let key_bytes = STANDARD
        .decode(text(&entry["public_key"])?)
        .map_err(|_| "invalid_public_key_encoding")?;
    let sig_bytes = STANDARD
        .decode(text(&sig["signature"])?)
        .map_err(|_| "invalid_signature_encoding")?;
    require(
        key_bytes.len() == 32 && sig_bytes.len() == 64,
        "invalid_key_signature_length",
    )?;
    let computed = cw_json::hash(payload)?;
    require(
        equal(hash, &json!({"algorithm":"sha256","value":computed})),
        "signed_artifact_hash_mismatch",
    )?;
    let envelope: SignatureEnvelope =
        serde_json::from_value(sig.clone()).map_err(|e| e.to_string())?;
    // Match the CW contract's selected-key checks. Unrelated trust entries are
    // still covered by the report's full snapshot digest, but are not adopted.
    let mut selected = trust.clone();
    selected["trusted_keys"] = json!({});
    selected["trusted_keys"][key] = entry.clone();
    let bundle: TrustBundle = serde_json::from_value(selected).map_err(|e| e.to_string())?;
    let resolver = super::TrustBundleResolver::from_bundle(&bundle);
    // Reuse crypto verification over the CW-computed hash; never rehash with
    // proof-core's different legacy canonicalization.
    let result = verify_detached_signature(
        &envelope,
        &ArtifactHash::sha256_hex(computed),
        "cw_simulation_evidence",
        &resolver,
    );
    require(result.verified, "ed25519_signature_rejected")
}

fn manifest(m: &Value, expected: &Value) -> Result<()> {
    object(
        m,
        &[
            "schemaVersion",
            "profile",
            "scope",
            "physicalAcceptance",
            "executionAuthority",
            "context",
            "startedAt",
            "endedAt",
            "stepCheckedAt",
            "terminalState",
            "reason",
            "executedSubsteps",
            "totalSubsteps",
            "artifactDigests",
        ],
    )?;
    require(
        m["schemaVersion"] == "seedcore.cw-g02.receipt.v1"
            && m["profile"] == PROFILE
            && m["scope"] == SCOPE
            && m["physicalAcceptance"] == false
            && m["executionAuthority"] == "none",
        "receipt_scope_mismatch",
    )?;
    context(&m["context"])?;
    require(
        equal(&m["context"], expected),
        "independently_expected_context_mismatch",
    )?;
    text(&m["startedAt"])?;
    text(&m["endedAt"])?;
    require(
        ["completed", "stopped", "fenced"]
            .iter()
            .any(|v| m["terminalState"] == *v)
            && (m["reason"].is_null() || m["reason"].is_string()),
        "terminal_schema_mismatch",
    )?;
    require(
        (1..=120).contains(&integer(&m["executedSubsteps"])?)
            && number(&m["totalSubsteps"])? == 120.,
        "terminal_count_mismatch",
    )?;
    let checks = array(&m["stepCheckedAt"])?;
    require(
        (1..=120).contains(&checks.len()) && checks.iter().all(Value::is_string),
        "invalid_step_checks",
    )?;
    object(&m["artifactDigests"], ARTIFACTS)?;
    for field in ARTIFACTS {
        digest_field(&m["artifactDigests"][*field])?;
    }
    Ok(())
}

fn vector(v: &Value, count: usize) -> Result<()> {
    let items = array(v)?;
    require(items.len() == count, "vector_dimension_mismatch")?;
    for item in items {
        number(item)?;
    }
    Ok(())
}

fn check_artifacts(a: &Value, m: &Value, c: &Value, trust: &Value) -> Result<()> {
    let token = &a["token"];
    let candidate_value = &a["candidate"];
    let source = &a["source"];
    let params = &a["parameters"];
    let r = &a["review"];
    let executor = &a["executor"];
    let capture = &a["capture"];
    candidate(candidate_value)?;
    require(
        candidate_value["candidateDigest"] == c["candidateDigest"]
            && equal(&candidate_value["binding"], &c["binding"])
            && candidate_value["endpointId"] == c["endpointId"]
            && candidate_value["binding"]["modelDigest"] == MODEL
            && integer(&candidate_value["behavior"]["totalTicks"])? == 120,
        "candidate_binding_mismatch",
    )?;
    for (key, field) in [
        ("token", "tokenDigest"),
        ("review", "reviewDigest"),
        ("executor", "executorDigest"),
    ] {
        require(
            cw_json::hash(&a[key])? == text(&c[field])?,
            "artifact_binding_mismatch",
        )?;
    }
    review(r)?;
    let resource = format!(
        "sha256:{}",
        cw_json::hash(
            &json!({"sourceDigest":c["sourceDigest"],"executorDigest":c["executorDigest"]})
        )?
    );
    require(
        r["candidateDigest"] == c["candidateDigest"]
            && r["endpointId"] == c["endpointId"]
            && r["revoked"] == false
            && r["resourceStateHash"] == resource,
        "review_binding_mismatch",
    )?;
    require(
        executor["profile"] == PROFILE
            && executor["engineVersion"] == "3.15.0"
            && number(&executor["timestepSeconds"])? == 0.002
            && number(&executor["maxTicks"])? == 120.
            && number(&executor["maxSubstepsPerBatch"])? == 8.
            && number(&executor["maxStallMs"])? == 250.
            && number(&executor["maxWallDurationSeconds"])? == 1.,
        "executor_clock_profile_mismatch",
    )?;
    let mut token_fields = CLAIMS.to_vec();
    token_fields.extend(["artifact_hash", "signature"]);
    object(token, &token_fields)?;
    object(&token["constraints"], CONSTRAINTS)?;
    object(&token["execution_preconditions"], PRECONDITIONS)?;
    let claims = without(token, &["artifact_hash", "signature"])?;
    signature(
        &claims,
        &token["artifact_hash"],
        &token["signature"],
        trust,
        text(&c["tokenKeyRef"])?,
        "service",
        text(&c["endpointId"])?,
    )?;
    let t = &token["constraints"];
    let pre = &token["execution_preconditions"];
    require(
        token["intent_id"] == c["requestId"]
            && t["action_type"] == "MOVE"
            && t["endpoint_id"] == c["endpointId"]
            && pre["endpoint_id"] == c["endpointId"]
            && t["asset_id"] == r["assetId"]
            && t["source_registration_id"] == r["sourceRegistrationId"]
            && t["registration_decision_id"] == r["registrationDecisionId"]
            && pre["resource_state_hash"] == r["resourceStateHash"]
            && token["contract_version"] == r["policySnapshot"],
        "token_action_review_binding_mismatch",
    )?;
    let payload_hash = format!(
        "sha256:{}",
        cw_json::hash(&without(params, &["payload_hash"])?)?
    );
    require(
        params["payload_hash"] == payload_hash
            && t["payload_hash"] == payload_hash
            && pre["payload_hash"] == payload_hash
            && c["payloadHash"] == payload_hash,
        "payload_hash_mismatch",
    )?;
    let build = &params["cw_build"];
    require(
        equal(&build["candidate"], candidate_value)
            && build["reviewDigest"] == c["reviewDigest"]
            && equal(&build["executor"], executor)
            && build["scope"] == "offline_simulation_only"
            && build["physicalAcceptance"] == false
            && build["executionAuthority"] == "none",
        "prepared_payload_binding_mismatch",
    )?;

    let issued = time(&token["issued_at"])?;
    let expires = time(&token["valid_until"])?;
    let admitted = time(&c["admittedAt"])?;
    let start = time(&m["startedAt"])?;
    let end = time(&m["endedAt"])?;
    let reviewed = time(&r["reviewedAt"])?;
    let review_until = time(&r["validUntil"])?;
    require(
        issued <= admitted
            && admitted <= start
            && start < expires
            && (1..=5_000_000).contains(&(expires - issued))
            && reviewed <= admitted
            && start < review_until
            && end >= start,
        "invalid_authority_time_window",
    )?;
    let ticks = integer(&m["executedSubsteps"])? as usize;
    let checks = array(&m["stepCheckedAt"])?;
    require(checks.len() == ticks, "step_authority_coverage_mismatch")?;
    let mut previous = start;
    for (index, checked) in checks.iter().enumerate() {
        let at = time(checked)?;
        require(
            previous <= at
                && at <= end
                && at < expires.min(review_until).min(start + 1_000_000)
                && at - start >= (index as i64 + 1) * 2000 - 1,
            "step_authority_clock_mismatch",
        )?;
        previous = at;
    }

    object(
        source,
        &[
            "schemaVersion",
            "scope",
            "physicalAcceptance",
            "executionAuthority",
            "candidate",
            "model",
            "gesture",
            "frames",
        ],
    )?;
    require(
        source["schemaVersion"] == "seedcore.cw-g01.endpoint-source.v1"
            && source["scope"] == "offline_simulation_only"
            && source["physicalAcceptance"] == false
            && source["executionAuthority"] == "none"
            && source["model"]["modelDigest"] == MODEL
            && array(&source["frames"])?.len() == 120,
        "source_profile_mismatch",
    )?;
    require(
        cw_json::hash(&without(&source["model"], &["modelDigest"])?)? == MODEL,
        "compiled_model_hash_mismatch",
    )?;
    object(
        capture,
        &[
            "schemaVersion",
            "summary",
            "samples",
            "scope",
            "physicalAcceptance",
            "signed",
            "sourceDigest",
            "executorDigest",
            "timestepSeconds",
            "captureDigest",
        ],
    )?;
    require(
        capture["schemaVersion"] == "seedcore.cw-g01.capture.v1"
            && capture["scope"] == SCOPE
            && capture["physicalAcceptance"] == false
            && capture["signed"] == false
            && number(&capture["timestepSeconds"])? == 0.002
            && capture["sourceDigest"] == c["sourceDigest"]
            && capture["executorDigest"] == c["executorDigest"]
            && cw_json::hash(&without(capture, &["captureDigest"])?)?
                == text(&capture["captureDigest"])?,
        "capture_scope_integrity_mismatch",
    )?;
    let summary = &capture["summary"];
    binding(&summary["binding"])?;
    object(
        summary,
        &[
            "id",
            "state",
            "reason",
            "executedSubsteps",
            "totalSubsteps",
            "profile",
            "scope",
            "physicalAcceptance",
            "executionAuthority",
            "mutationPathsGuarded",
            "clearedExternalMutations",
            "tokenId",
            "validUntil",
            "candidateDigest",
            "binding",
            "endpointId",
            "modelDigest",
            "payloadHash",
            "tokenVerification",
        ],
    )?;
    require(
        summary["id"] == c["requestId"]
            && summary["candidateDigest"] == c["candidateDigest"]
            && equal(&summary["binding"], &candidate_value["binding"])
            && summary["endpointId"] == c["endpointId"]
            && summary["modelDigest"] == MODEL
            && summary["tokenId"] == token["token_id"]
            && summary["payloadHash"] == c["payloadHash"]
            && summary["validUntil"] == token["valid_until"]
            && summary["profile"] == PROFILE
            && summary["scope"] == SCOPE
            && summary["physicalAcceptance"] == false
            && summary["executionAuthority"] == "simulation_endpoint_only"
            && summary["tokenVerification"] == "rust_signature_and_constraints"
            && summary["mutationPathsGuarded"]
                == json!([
                    "ctrl",
                    "qfrc_applied",
                    "xfrc_applied",
                    "qpos_qvel_act_state",
                    "opt_timestep",
                    "policy_model_switch"
                ])
            && integer(&summary["executedSubsteps"])? == ticks as u64
            && integer(&summary["totalSubsteps"])? == 120
            && summary["state"] == m["terminalState"]
            && summary["reason"] == m["reason"],
        "capture_receipt_summary_mismatch",
    )?;
    integer(&summary["clearedExternalMutations"])?;
    let complete = m["terminalState"] == "completed";
    require(
        (complete && m["reason"].is_null() && ticks == 120)
            || (m["terminalState"] == "stopped"
                && (m["reason"] == "operator_stop" || m["reason"] == "service_shutdown")
                && ticks < 120),
        "unsupported_terminal_outcome",
    )?;
    if complete {
        require(
            end < expires.min(review_until).min(start + 1_000_000),
            "completion_outside_authority_window",
        )?;
    }
    let samples = array(&capture["samples"])?;
    require(samples.len() == ticks, "capture_coverage_mismatch")?;
    let bodies = array(&source["model"]["manifest"]["bodies"])?;
    require(
        array(&source["model"]["manifest"]["joints"])?.len() == 2,
        "unsupported_joint_inventory",
    )?;
    let limits = array(&build["intersectedLimits"])?;
    require(limits.len() == 2, "joint_limit_inventory_mismatch")?;
    for (i, sample) in samples.iter().enumerate() {
        object(
            sample,
            &[
                "tick",
                "simTimeSeconds",
                "qpos",
                "qvel",
                "ctrl",
                "qfrcActuator",
                "xpos",
                "bodies",
                "virtualLed",
            ],
        )?;
        require(
            integer(&sample["tick"])? == i as u64 + 1
                && (number(&sample["simTimeSeconds"])? - (i + 1) as f64 * 0.002).abs() <= 1e-12,
            "sample_gap_order_clock_mismatch",
        )?;
        for name in ["qpos", "qvel", "ctrl", "qfrcActuator"] {
            vector(&sample[name], 2)?;
        }
        for (limit, q) in limits.iter().zip(array(&sample["qpos"])?) {
            require(
                number(&limit["lowerRad"])? <= number(q)?
                    && number(q)? <= number(&limit["upperRad"])?,
                "observed_state_outside_limits",
            )?;
        }
        vector(&sample["xpos"], 3 * (bodies.len() + 1))?;
        let frame = &source["frames"][i];
        require(
            integer(&frame["tick"])? == (i + 1) as u64
                && equal(&sample["ctrl"], &frame["targetRad"])
                && sample["virtualLed"] == frame["virtualLed"],
            "sample_control_cue_mismatch",
        )?;
        let observed = array(&sample["bodies"])?;
        require(
            observed.len() == bodies.len(),
            "sample_body_inventory_mismatch",
        )?;
        for (o, body) in observed.iter().zip(bodies) {
            object(o, &["nodeId", "position_m", "quaternion_wxyz"])?;
            require(
                o["nodeId"] == body["nodeId"],
                "sample_body_identity_mismatch",
            )?;
            vector(&o["position_m"], 3)?;
            vector(&o["quaternion_wxyz"], 4)?;
            let norm: f64 = array(&o["quaternion_wxyz"])?
                .iter()
                .map(|q| q.as_f64().unwrap().powi(2))
                .sum();
            require((norm - 1.).abs() < 1e-9, "invalid_pose_quaternion")?;
        }
    }
    Ok(())
}

fn check(raw: &[u8], expected: &Value, trust: &Value, report: &mut Value) -> Result<()> {
    context(expected)?;
    report["expectedContextDigest"] = cw_json::hash(expected)?.into();
    report["trustSnapshotDigest"] = cw_json::hash(trust)?.into();
    object(trust, &["version", "trusted_keys", "revoked_keys"])?;
    require(
        trust["version"] == "seedcore.cw-g02.simulation-trust.v1"
            && trust["trusted_keys"].is_object()
            && array(&trust["revoked_keys"])?.iter().all(Value::is_string),
        "trust_snapshot_mismatch",
    )?;
    let bundle = cw_json::parse(raw)?;
    object(&bundle, &["schemaVersion", "receipt", "artifacts"])?;
    require(
        bundle["schemaVersion"] == "seedcore.cw-g02.bundle.v1",
        "bundle_schema_mismatch",
    )?;
    let receipt = &bundle["receipt"];
    object(receipt, &["artifact", "artifact_hash", "signature"])?;
    let m = &receipt["artifact"];
    manifest(m, expected)?;
    signature(
        m,
        &receipt["artifact_hash"],
        &receipt["signature"],
        trust,
        text(&expected["receiptKeyRef"])?,
        "host_simulation",
        text(&expected["endpointId"])?,
    )?;
    object(&bundle["artifacts"], ARTIFACTS)?;
    let mut artifacts = json!({});
    for name in ARTIFACTS {
        let encoded = text(&bundle["artifacts"][*name])?;
        require(
            encoded.len() <= 4 * ((MAX_ARTIFACT + 2) / 3),
            "oversized_artifact_encoding",
        )?;
        let bytes = STANDARD
            .decode(encoded)
            .map_err(|_| "invalid_artifact_base64")?;
        require(
            !bytes.is_empty()
                && bytes.len() <= MAX_ARTIFACT
                && cw_json::raw_hash(&bytes) == text(&m["artifactDigests"][*name])?,
            "original_artifact_hash_mismatch",
        )?;
        let parsed = cw_json::parse(&bytes)?;
        cw_json::canonical(&parsed)?;
        artifacts[*name] = parsed;
    }
    report["sourceRefs"] = m["artifactDigests"].clone();
    require(
        m["artifactDigests"]["source"] == expected["sourceDigest"],
        "original_source_hash_mismatch",
    )?;
    check_artifacts(&artifacts, m, expected, trust)?;
    report["verified"] = true.into();
    report["disposition"] = if m["terminalState"] == "completed" {
        "verified_completed"
    } else {
        "verified_interrupted"
    }
    .into();
    Ok(())
}

pub fn verify_paths(bundle: &Path, expected: &Path, trust: &Path) -> Value {
    let mut report = json!({"schemaVersion":"seedcore.cw-g02.verification.v1", "verified":false,
        "disposition":"quarantine", "scope":SCOPE, "physicalAcceptance":false, "executionAuthority":"none",
        "bundleSha256":null, "expectedContextDigest":null, "trustSnapshotDigest":null, "sourceRefs":{}, "error":null});
    let result = (|| {
        let raw = cw_json::read(bundle, MAX_BUNDLE)?;
        report["bundleSha256"] = cw_json::raw_hash(&raw).into();
        let expected = cw_json::parse(&cw_json::read(expected, 32768)?)?;
        let trust = cw_json::parse(&cw_json::read(trust, 32768)?)?;
        check(&raw, &expected, &trust, &mut report)
    })();
    if let Err(error) = result {
        report["error"] = error.chars().take(500).collect::<String>().into();
    }
    report
}
