from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


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
    claims_path = _write_temp_json(dict(claims))
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
    return "invalid ExecutionToken"


def _run_verify_cli(args: list[str]) -> dict[str, Any]:
    repo_root = _repo_root()
    rust_dir = repo_root / "rust"
    binary = _resolve_verify_binary(repo_root)

    try:
        if binary is not None:
            completed = subprocess.run(
                [str(binary), *args],
                check=False,
                capture_output=True,
                text=True,
            )
        else:
            completed = subprocess.run(
                ["cargo", "run", "-q", "-p", "seedcore-verify", "--", *args],
                cwd=rust_dir,
                check=False,
                capture_output=True,
                text=True,
            )
    except Exception as exc:
        return {"error": f"rust_kernel_unavailable:{exc}"}

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        return {"error": f"rust_verify_failed:{stderr}"}

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
        Path("/usr/local/bin/seedcore-verify"),
        repo_root / "rust" / "target" / "release" / "seedcore-verify",
        repo_root / "rust" / "target" / "debug" / "seedcore-verify",
    ]
    for candidate in default_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


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
