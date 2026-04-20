from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

_PROOF_PY_MODULE: Any | None = None
_PROOF_PY_MODULE_CHECKED = False


def _verify_cli_timeout_seconds() -> float:
    raw = os.getenv("SEEDCORE_VERIFY_CLI_TIMEOUT_SECONDS", "15").strip()
    try:
        timeout_s = float(raw)
    except ValueError:
        timeout_s = 15.0
    return max(1.0, timeout_s)


def _proof_py_bridge_enabled() -> bool:
    raw = os.getenv("SEEDCORE_PROOF_PY_BRIDGE_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _load_proof_py_module() -> Any | None:
    global _PROOF_PY_MODULE, _PROOF_PY_MODULE_CHECKED
    if _PROOF_PY_MODULE_CHECKED:
        return _PROOF_PY_MODULE
    _PROOF_PY_MODULE_CHECKED = True
    if not _proof_py_bridge_enabled():
        return None
    try:
        _PROOF_PY_MODULE = importlib.import_module("seedcore_proof_py")
    except Exception:
        _PROOF_PY_MODULE = None
    return _PROOF_PY_MODULE


def _reset_proof_py_bridge_cache_for_tests() -> None:
    global _PROOF_PY_MODULE, _PROOF_PY_MODULE_CHECKED
    _PROOF_PY_MODULE = None
    _PROOF_PY_MODULE_CHECKED = False


def _coerce_bridge_mapping(result: Any) -> dict[str, Any] | None:
    if isinstance(result, Mapping):
        return dict(result)
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except Exception:
            return None
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return None


def _call_proof_py_bridge(method: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    module = _load_proof_py_module()
    if module is None:
        return None
    fn = getattr(module, method, None)
    if not callable(fn):
        return None
    payload_dict = dict(payload)
    try:
        result = fn(payload_dict)
    except TypeError:
        # Rust PyO3 bridges often expose string-based JSON signatures.
        try:
            result = fn(json.dumps(payload_dict, ensure_ascii=True))
        except Exception:
            logger.debug("seedcore_proof_py bridge call failed: %s", method, exc_info=True)
            return None
    except Exception:
        logger.debug("seedcore_proof_py bridge call failed: %s", method, exc_info=True)
        return None
    bridged = _coerce_bridge_mapping(result)
    if bridged is None:
        logger.debug("seedcore_proof_py bridge returned invalid payload for %s", method)
        return None
    return bridged


def verify_execution_token_with_rust(
    token: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = _isoformat_utc(now or datetime.now(timezone.utc))
    artifact_path = _write_temp_json(dict(token))
    try:
        output = _run_verify_cli(
            [
                "verify-token",
                "--artifact",
                artifact_path,
                "--now",
                now_value,
            ]
        )
    finally:
        _unlink_quietly(artifact_path)
    if "verified" not in output:
        return {"verified": False, "error_code": "rust_verify_token_failed", "details": [output]}
    return output


def enforce_execution_token_with_rust(
    token: Mapping[str, Any],
    request_context: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = _isoformat_utc(now or datetime.now(timezone.utc))
    token_path = _write_temp_json(dict(token))
    request_path = _write_temp_json(dict(request_context))
    try:
        output = _run_verify_cli(
            [
                "enforce-token",
                "--token",
                token_path,
                "--request",
                request_path,
                "--now",
                now_value,
            ]
        )
    finally:
        _unlink_quietly(token_path)
        _unlink_quietly(request_path)
    if "allowed" not in output:
        return {"allowed": False, "error_code": "rust_enforce_token_failed", "details": [output]}
    return output


def mint_execution_token_with_rust(claims: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(claims)
    bridged = _call_proof_py_bridge("mint_execution_token", payload)
    if bridged is not None:
        if "token_id" in bridged:
            return bridged
        logger.debug("seedcore_proof_py bridge payload invalid for mint_execution_token; falling back to CLI")
    claims_path = _write_temp_json(payload)
    try:
        output = _run_verify_cli(
            [
                "mint-token",
                "--claims",
                claims_path,
            ]
        )
    finally:
        _unlink_quietly(claims_path)
    if "token_id" not in output:
        return {"error": "rust_mint_token_failed", "details": [output]}
    return output


def evaluate_policy_with_rust(frozen_input: Mapping[str, Any]) -> dict[str, Any]:
    input_path = _write_temp_json(dict(frozen_input))
    try:
        output = _run_verify_cli(
            [
                "evaluate-policy",
                "--artifact",
                input_path,
            ]
        )
    finally:
        _unlink_quietly(input_path)
    if "disposition" not in output:
        return {"error": "rust_evaluate_policy_failed", "details": [output]}
    return output


def validate_transfer_approval_with_rust(envelope: Mapping[str, Any]) -> dict[str, Any]:
    envelope_path = _write_temp_json(dict(envelope))
    try:
        output = _run_verify_cli(
            [
                "validate-approval",
                "--artifact",
                envelope_path,
            ]
        )
    finally:
        _unlink_quietly(envelope_path)
    if "valid" not in output:
        return {"valid": False, "error_code": "rust_validate_approval_failed", "details": [output]}
    return output


def approval_binding_hash_with_rust(envelope: Mapping[str, Any]) -> dict[str, Any]:
    envelope_path = _write_temp_json(dict(envelope))
    try:
        output = _run_verify_cli(
            [
                "approval-binding-hash",
                "--artifact",
                envelope_path,
            ]
        )
    finally:
        _unlink_quietly(envelope_path)
    if "valid" not in output:
        return {"valid": False, "error_code": "rust_approval_binding_hash_failed", "details": [output]}
    return output


def summarize_transfer_approval_with_rust(envelope: Mapping[str, Any]) -> dict[str, Any]:
    envelope_path = _write_temp_json(dict(envelope))
    try:
        output = _run_verify_cli(
            [
                "approval-summary",
                "--artifact",
                envelope_path,
            ]
        )
    finally:
        _unlink_quietly(envelope_path)
    if "valid" not in output:
        return {
            "valid": False,
            "status": None,
            "required_roles": [],
            "approved_by": [],
            "co_signed": False,
            "binding_hash": None,
            "error_code": "rust_approval_summary_failed",
            "details": [output],
        }
    return output


def apply_transfer_approval_transition_with_rust(
    envelope: Mapping[str, Any],
    transition: Mapping[str, Any],
    *,
    history: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = _isoformat_utc(now or datetime.now(timezone.utc))
    envelope_path = _write_temp_json(dict(envelope))
    transition_path = _write_temp_json(dict(transition))
    history_payload = dict(history) if isinstance(history, Mapping) else {"events": [], "chain_head": None}
    history_path = _write_temp_json(history_payload)
    try:
        output = _run_verify_cli(
            [
                "apply-approval-transition",
                "--artifact",
                envelope_path,
                "--transition",
                transition_path,
                "--history",
                history_path,
                "--now",
                now_value,
            ]
        )
    finally:
        _unlink_quietly(envelope_path)
        _unlink_quietly(transition_path)
        _unlink_quietly(history_path)
    if "valid" not in output:
        return {
            "valid": False,
            "approval_envelope": None,
            "binding_hash": None,
            "transition_event": None,
            "history": history_payload,
            "error_code": "rust_apply_approval_transition_failed",
            "details": [output],
        }
    return output


def verify_approval_transition_history_with_rust(history: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(history)
    bridged = _call_proof_py_bridge("verify_approval_history", payload)
    if bridged is not None:
        if "valid" in bridged:
            return bridged
        logger.debug("seedcore_proof_py bridge payload invalid for verify_approval_history; falling back to CLI")
    history_path = _write_temp_json(payload)
    try:
        output = _run_verify_cli(
            [
                "verify-approval-history",
                "--artifact",
                history_path,
            ]
        )
    finally:
        _unlink_quietly(history_path)
    if "valid" not in output:
        return {
            "valid": False,
            "chain_head": history.get("chain_head"),
            "event_count": len(history.get("events")) if isinstance(history.get("events"), list) else 0,
            "error_code": "rust_verify_approval_history_failed",
            "details": [output],
        }
    return output


def seal_replay_bundle_with_rust(artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "artifacts": [dict(item) for item in artifacts if isinstance(item, Mapping)],
    }
    artifact_path = _write_temp_json(payload)
    try:
        output = _run_verify_cli(
            [
                "seal-replay-bundle",
                "--artifact",
                artifact_path,
            ]
        )
    finally:
        _unlink_quietly(artifact_path)
    if "artifacts" not in output:
        error = str(output.get("error") or "").strip()
        if error == "rust_verify_timeout":
            error_code = "rust_seal_replay_bundle_timeout"
        elif error == "rust_kernel_unavailable":
            error_code = "rust_seal_replay_bundle_unavailable"
        else:
            error_code = "rust_seal_replay_bundle_failed"
        return {
            "error_code": error_code,
            "details": [output],
            "artifacts": [],
        }
    return output


def materialize_replay_bundle_with_rust(artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "artifacts": [dict(item) for item in artifacts if isinstance(item, Mapping)],
    }
    bridged = _call_proof_py_bridge("materialize_replay_bundle", payload)
    if bridged is not None:
        if "artifacts" in bridged:
            return bridged
        logger.debug("seedcore_proof_py bridge payload invalid for materialize_replay_bundle; falling back to CLI")
    artifact_path = _write_temp_json(payload)
    try:
        output = _run_verify_cli(
            [
                "materialize-replay-bundle",
                "--artifact",
                artifact_path,
            ]
        )
    finally:
        _unlink_quietly(artifact_path)
    if "artifacts" not in output:
        error = str(output.get("error") or "").strip()
        if error == "rust_verify_timeout":
            error_code = "rust_materialize_replay_bundle_timeout"
        elif error == "rust_kernel_unavailable":
            error_code = "rust_materialize_replay_bundle_unavailable"
        else:
            error_code = "rust_materialize_replay_bundle_failed"
        return {
            "error_code": error_code,
            "details": [output],
            "artifacts": [],
        }
    return output


def verify_replay_bundle_with_rust(bundle: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(bundle)
    trust_bundle_path = _verify_trust_bundle_path()
    bridge_payload: dict[str, Any] = payload
    if trust_bundle_path is not None:
        bridge_payload = {
            "bundle": payload,
            "trust_bundle_path": trust_bundle_path,
        }

    bridged = _call_proof_py_bridge("verify_chain", bridge_payload)
    if bridged is not None:
        if "verified" in bridged:
            return bridged
        logger.debug("seedcore_proof_py bridge payload invalid for verify_chain; falling back to CLI")

    bundle_path = _write_temp_json(payload)
    try:
        args = [
            "verify-chain",
            "--bundle",
            bundle_path,
        ]
        if trust_bundle_path is not None:
            args.extend(["--trust-bundle", trust_bundle_path])
        output = _run_verify_cli(args)
    finally:
        _unlink_quietly(bundle_path)
    if "verified" not in output:
        error = str(output.get("error") or "").strip()
        if error == "rust_verify_timeout":
            error_code = "rust_verify_replay_chain_timeout"
        elif error == "rust_kernel_unavailable":
            error_code = "rust_verify_replay_chain_unavailable"
        else:
            error_code = "rust_verify_replay_chain_failed"
        return {
            "verified": False,
            "error_code": error_code,
            "details": [output],
            "artifact_reports": [],
            "chain_checks": [],
        }
    return output


def verify_source_replay_artifacts_with_rust(artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    bundle = materialize_replay_bundle_with_rust(artifacts)
    if not isinstance(bundle.get("artifacts"), list) or not bundle.get("artifacts"):
        error_code = str(bundle.get("error_code") or "").strip().lower()
        if error_code.endswith("_timeout"):
            replay_error_code = "rust_verify_replay_chain_timeout"
        elif error_code.endswith("_unavailable"):
            replay_error_code = "rust_verify_replay_chain_unavailable"
        else:
            replay_error_code = "rust_verify_replay_chain_failed"
        return {
            "verified": False,
            "error_code": replay_error_code,
            "details": list(bundle.get("details") or []),
            "artifact_reports": [],
            "chain_checks": [],
            "materialized_bundle": bundle,
        }
    verified = verify_replay_bundle_with_rust(bundle)
    verified["materialized_bundle"] = bundle
    return verified


def list_verify_error_codes_with_rust() -> dict[str, Any]:
    output = _run_verify_cli(["list-error-codes"])
    if "error_codes" not in output:
        return {"error_codes": {}, "details": [output]}
    return output


def map_token_error_for_hal(error_code: str | None) -> str:
    if error_code in {"token_expired"}:
        return "expired ExecutionToken"
    if error_code in {
        "signature_mismatch",
        "artifact_hash_mismatch",
        "missing_key_ref",
        "key_not_found",
        "unsupported_signing_scheme",
    }:
        return "forged ExecutionToken"
    if error_code in {"endpoint_id_mismatch"}:
        return "ExecutionToken endpoint mismatch"
    if error_code in {"target_zone_mismatch"}:
        return "ExecutionToken target zone mismatch"
    if error_code in {"payload_hash_mismatch"}:
        return "ExecutionToken payload mismatch"
    if error_code in {"resource_state_hash_mismatch"}:
        return "ExecutionToken resource state mismatch"
    if error_code in {"approval_transition_head_mismatch"}:
        return "ExecutionToken approval transition mismatch"
    if error_code in {"context_token_mismatch"}:
        return "ExecutionToken context token mismatch"
    return "invalid ExecutionToken"


def _run_verify_cli(args: list[str]) -> dict[str, Any]:
    repo_root = _repo_root()
    rust_dir = repo_root / "rust"
    binary = _resolve_verify_binary(repo_root)
    timeout_s = _verify_cli_timeout_seconds()

    try:
        completed: subprocess.CompletedProcess[str] | None = None
        if binary is not None:
            completed = subprocess.run(
                [str(binary), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            if completed.returncode != 0:
                completed = subprocess.run(
                    ["cargo", "run", "-q", "-p", "seedcore-verify", "--", *args],
                    cwd=rust_dir,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
        else:
            completed = subprocess.run(
                ["cargo", "run", "-q", "-p", "seedcore-verify", "--", *args],
                cwd=rust_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
    except subprocess.TimeoutExpired:
        return {"error": "rust_verify_timeout", "timeout_seconds": timeout_s}
    except Exception as exc:
        return {"error": "rust_kernel_unavailable", "detail": str(exc)}

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        return {"error": "rust_verify_failed", "detail": stderr}

    try:
        return json.loads(completed.stdout)
    except Exception:
        return {"error": "rust_verify_invalid_json", "raw": completed.stdout}


def _resolve_verify_binary(repo_root: Path) -> Path | None:
    override = os.getenv("SEEDCORE_VERIFY_BIN", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = (repo_root / candidate).resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
    default_candidates = [
        repo_root / "rust" / "target" / "debug" / "seedcore-verify",
        repo_root / "rust" / "target" / "release" / "seedcore-verify",
        Path("/usr/local/bin/seedcore-verify"),
    ]
    for candidate in default_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _verify_trust_bundle_path() -> str | None:
    configured = os.getenv("SEEDCORE_VERIFY_TRUST_BUNDLE", "").strip()
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = (_repo_root() / candidate).resolve()
    return str(candidate)


def _write_temp_json(payload: Mapping[str, Any]) -> str:
    temp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    with temp:
        json.dump(payload, temp, ensure_ascii=True)
    return temp.name


def _unlink_quietly(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        return


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
