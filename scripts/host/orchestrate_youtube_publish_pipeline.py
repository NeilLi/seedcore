#!/usr/bin/env python3
"""
Run an end-to-end SeedCore pipeline for YouTube publishing:

1. Prepare + submit signed external intent (owner/assistant authority).
2. Route execution via Coordinator -> Agent -> ToolManager.
3. Execute YouTube publish + HAL forensic seal tool calls.
4. Emit a production digital twin artifact bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import requests


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def post_json(base_url: str, path: str, payload: Dict[str, Any], *, timeout: int = 90) -> Tuple[int, Dict[str, Any]]:
    url = f"{base_url.rstrip('/')}{path}"
    response = requests.post(url, json=payload, timeout=timeout)
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return response.status_code, body


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_intent_setup(args: argparse.Namespace) -> Tuple[Path, Path]:
    intent_script = Path(args.intent_script).resolve()
    if not intent_script.exists():
        raise FileNotFoundError(f"Intent helper script not found: {intent_script}")

    bundle_path = Path(args.bundle_out).resolve()
    cmd = [
        sys.executable,
        str(intent_script),
        "--base-url",
        args.seedcore_api,
        "--owner-email",
        args.owner_email,
        "--video-path",
        args.video_path,
        "--title",
        args.title,
        "--visibility",
        args.visibility,
        "--audience",
        args.audience,
        "--thumbnail-mode",
        args.thumbnail_mode,
        "--bundle-out",
        str(bundle_path),
        "--submit",
        "--auto-publish",
    ]
    if args.owner_did:
        cmd.extend(["--owner-did", args.owner_did])
    if args.assistant_did:
        cmd.extend(["--assistant-did", args.assistant_did])
    if args.hmac_secret:
        cmd.extend(["--hmac-secret", args.hmac_secret])

    subprocess.run(cmd, check=True)
    return bundle_path, bundle_path.with_suffix(".results.json")


def ensure_pkg_publish_policy(args: argparse.Namespace) -> None:
    seed_script = Path(args.policy_seed_script).resolve()
    if not seed_script.exists():
        raise FileNotFoundError(f"PKG policy seed script not found: {seed_script}")

    cmd = [
        sys.executable,
        str(seed_script),
        "--seedcore-api",
        args.seedcore_api,
        "--compile-activate",
    ]
    if args.snapshot_id is not None:
        cmd.extend(["--snapshot-id", str(args.snapshot_id)])
    if args.snapshot_version:
        cmd.extend(["--snapshot-version", str(args.snapshot_version)])
    if args.pg_dsn:
        cmd.extend(["--pg-dsn", args.pg_dsn])

    subprocess.run(cmd, check=True)


def ensure_governance_context(
    *,
    seedcore_api: str,
    bundle: Dict[str, Any],
    existing_results: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if isinstance(existing_results, dict):
        submit_result = existing_results.get("submit_signed_intent")
        if isinstance(submit_result, dict):
            body = submit_result.get("body")
            status = int(submit_result.get("status") or 0)
            if status < 400 and isinstance(body, dict) and isinstance(body.get("action_intent"), dict):
                return body

    submission = (
        bundle.get("signed_intent", {}).get("submission")
        if isinstance(bundle.get("signed_intent"), dict)
        else None
    )
    if not isinstance(submission, dict):
        raise ValueError("Intent bundle does not contain signed submission payload.")
    status, body = post_json(seedcore_api, "/api/v1/intents/submit-signed", submission)
    if status >= 400:
        raise RuntimeError(f"Signed intent submission failed: HTTP {status} {body}")
    if not isinstance(body, dict) or not isinstance(body.get("action_intent"), dict):
        raise RuntimeError("Signed intent submission did not return governance context.")
    return body


def build_coordinator_task(
    *,
    governance_context: Dict[str, Any],
    required_specialization: str,
) -> Dict[str, Any]:
    action_intent = governance_context.get("action_intent", {})
    action = action_intent.get("action", {}) if isinstance(action_intent, dict) else {}
    resource = action_intent.get("resource", {}) if isinstance(action_intent, dict) else {}
    parameters = action.get("parameters", {}) if isinstance(action, dict) else {}
    video = parameters.get("video", {}) if isinstance(parameters, dict) else {}
    thumbnail = parameters.get("thumbnail", {}) if isinstance(parameters, dict) else {}

    intent_id = str(action_intent.get("intent_id") or f"intent-youtube-{uuid.uuid4().hex[:12]}")
    policy_hash = (
        str(action.get("security_contract", {}).get("hash"))
        if isinstance(action.get("security_contract"), dict)
        else "sha256:unknown"
    )
    execution_token = governance_context.get("execution_token", {})
    auth_token = (
        str(execution_token.get("token_id"))
        if isinstance(execution_token, dict) and execution_token.get("token_id")
        else f"seedcore-auth-{uuid.uuid4().hex[:10]}"
    )

    source_video_hash = str(video.get("sha256") or resource.get("resource_state_hash") or "").replace("sha256:", "")
    source_video_uri = str(resource.get("resource_uri") or video.get("path") or "")
    forensic_event_id = f"urn:seedcore:event:youtube-production:{intent_id}"

    youtube_tool_args = {
        "video_path": str(video.get("path") or ""),
        "title": str(parameters.get("title") or "SeedCore YouTube Publish"),
        "visibility": str(parameters.get("visibility") or "unlisted"),
        "audience": str(parameters.get("audience") or "kids"),
        "made_for_kids": bool(parameters.get("metadata", {}).get("made_for_kids", True))
        if isinstance(parameters.get("metadata"), dict)
        else True,
        "thumbnail_mode": str(thumbnail.get("mode") or "ai_auto_generate"),
        "account_email": str(parameters.get("youtube_account_email") or ""),
        "description": str(parameters.get("description") or "Published by SeedCore governed pipeline."),
        "tags": list(parameters.get("tags") or []) if isinstance(parameters.get("tags"), list) else [],
        "_timeout_s": 300,
    }

    forensic_tool_args = {
        "event_id": forensic_event_id,
        "platform_state": "youtube_publish_completed",
        "trajectory_hash": f"sha256:{source_video_hash}" if source_video_hash else "sha256:unknown",
        "policy_hash": policy_hash,
        "auth_token": auth_token,
        "from_zone": "creator_staging",
        "to_zone": "youtube_published",
        "media_hash_references": [
            {
                "uri": source_video_uri,
                "hash": f"sha256:{source_video_hash}" if source_video_hash else None,
                "role": "source_video",
            }
        ],
        "_timeout_s": 120,
    }

    return {
        "task_id": str(uuid.uuid4()),
        "type": "action",
        "description": "SeedCore governed YouTube publish with HAL digital twin sealing",
        "domain": "creator",
        "params": {
            "interaction": {"mode": "coordinator_routed"},
            "routing": {
                "required_specialization": required_specialization,
                "tools": ["youtube.publish_video", "forensic.seal"],
                "hints": {"priority": 9},
            },
            "tool_policy": {"allow": ["youtube.publish_video", "forensic.seal"]},
            "tool_calls": [
                {"name": "youtube.publish_video", "args": youtube_tool_args},
                {"name": "forensic.seal", "args": forensic_tool_args},
            ],
            "governance": governance_context,
            "cognitive": {
                "decision_kind": "fast",
                "force_fast": True,
            },
        },
    }


def extract_tool_outputs(envelope: Dict[str, Any]) -> Dict[str, Any]:
    payload = envelope.get("payload", {}) if isinstance(envelope.get("payload"), dict) else {}
    results = payload.get("results", []) if isinstance(payload.get("results"), list) else []

    extracted: Dict[str, Any] = {
        "youtube.publish_video": None,
        "forensic.seal": None,
    }
    for row in results:
        if not isinstance(row, dict):
            continue
        name = str(row.get("tool") or "")
        if name in extracted:
            extracted[name] = row.get("output")
    return extracted


def build_digital_twin_artifact(
    *,
    bundle: Dict[str, Any],
    coordinator_response: Dict[str, Any],
    tool_outputs: Dict[str, Any],
) -> Dict[str, Any]:
    signed_submission = (
        bundle.get("signed_intent", {}).get("submission")
        if isinstance(bundle.get("signed_intent"), dict)
        else {}
    )
    action_intent = (
        signed_submission.get("action_intent")
        if isinstance(signed_submission, dict)
        else {}
    )
    youtube_output = tool_outputs.get("youtube.publish_video")
    forensic_output = tool_outputs.get("forensic.seal")
    forensic_event = (
        forensic_output.get("custody_event")
        if isinstance(forensic_output, dict) and isinstance(forensic_output.get("custody_event"), dict)
        else None
    )
    video_id = (
        str(youtube_output.get("video_id"))
        if isinstance(youtube_output, dict) and youtube_output.get("video_id") is not None
        else None
    )

    production = {
        "digital_twin_id": f"digital-twin:youtube-production:{action_intent.get('intent_id', 'unknown')}",
        "generated_at": iso_utc_now(),
        "channel": "youtube",
        "intent_id": action_intent.get("intent_id"),
        "owner_id": bundle.get("owner_did"),
        "assistant_id": bundle.get("assistant_did"),
        "video_id": video_id,
        "video_url": (
            f"https://www.youtube.com/watch?v={video_id}"
            if video_id
            else None
        ),
        "publish_status": (
            youtube_output.get("status")
            if isinstance(youtube_output, dict)
            else "unknown"
        ),
        "forensic_event_id": (
            forensic_event.get("event_id")
            or forensic_event.get("id")
            if isinstance(forensic_event, dict)
            else None
        ),
        "forensic_capture_id": (
            forensic_event.get("hal_capture_id")
            if isinstance(forensic_event, dict)
            else None
        ),
        "forensic_event": forensic_event,
        "authority_context_hash": (
            coordinator_response.get("meta", {})
            .get("governance", {})
            .get("owner_context_hash")
            if isinstance(coordinator_response.get("meta"), dict)
            else None
        ),
        "source_video": (
            action_intent.get("resource")
            if isinstance(action_intent, dict) and isinstance(action_intent.get("resource"), dict)
            else {}
        ),
    }
    production_fingerprint = f"sha256:{sha256_hex(canonical_json(production))}"

    return {
        "generated_at": iso_utc_now(),
        "pipeline": {
            "name": "seedcore_coordinator_agent_toolmanager_hal_youtube_pipeline",
            "status": "completed" if bool(coordinator_response.get("success")) else "failed",
        },
        "intent_bundle_ref": bundle.get("video_path"),
        "coordinator_response": coordinator_response,
        "tool_outputs": tool_outputs,
        "production_digital_twin": production,
        "production_fingerprint": production_fingerprint,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SeedCore YouTube publish pipeline with HAL digital twin generation")
    parser.add_argument("--seedcore-api", default="http://127.0.0.1:8002", help="SeedCore API base URL (identity/external authority)")
    parser.add_argument("--coordinator-api", default="http://127.0.0.1:8000/pipeline", help="Coordinator service base URL")
    parser.add_argument(
        "--coordinator-timeout-s",
        type=int,
        default=900,
        help="HTTP timeout (seconds) for coordinator /route-and-execute call.",
    )
    parser.add_argument("--owner-email", default="lizi.lining@gmail.com")
    parser.add_argument("--video-path", default="artifacts/demo/Robots_Collecting_Priciest_Honey.mp4")
    parser.add_argument("--title", default="Robots Collecting Priciest Honey")
    parser.add_argument("--visibility", default="unlisted")
    parser.add_argument("--audience", default="kids")
    parser.add_argument("--thumbnail-mode", default="ai_auto_generate")
    parser.add_argument("--bundle-out", default="artifacts/demo/youtube_publish_intent_lizi.bundle.json")
    parser.add_argument("--digital-twin-out", default="artifacts/demo/youtube_publish_digital_twin_lizi.json")
    parser.add_argument("--required-specialization", default="generalist")
    parser.add_argument("--owner-did", default="")
    parser.add_argument("--assistant-did", default="")
    parser.add_argument("--hmac-secret", default="")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--snapshot-id", type=int, default=None)
    parser.add_argument("--snapshot-version", default="")
    parser.add_argument("--policy-seed-script", default="scripts/host/seed_publish_content_pkg_policy.py")
    parser.add_argument(
        "--skip-policy-seed",
        action="store_true",
        help="Skip PKG policy seed/compile/activate bootstrap before orchestration.",
    )
    parser.add_argument(
        "--intent-script",
        default="scripts/host/submit_youtube_publish_intent.py",
        help="Path to intent helper script",
    )
    parser.add_argument(
        "--skip-intent-setup",
        action="store_true",
        help="Skip running intent setup script and reuse existing bundle/results files.",
    )
    args = parser.parse_args()

    bundle_path = Path(args.bundle_out).resolve()
    results_path = bundle_path.with_suffix(".results.json")

    if not args.skip_policy_seed:
        ensure_pkg_publish_policy(args)

    if not args.skip_intent_setup:
        bundle_path, results_path = run_intent_setup(args)

    bundle = load_json(bundle_path)
    setup_results = load_json(results_path) if results_path.exists() else None
    governance_context = ensure_governance_context(
        seedcore_api=args.seedcore_api,
        bundle=bundle,
        existing_results=setup_results,
    )

    task_payload = build_coordinator_task(
        governance_context=governance_context,
        required_specialization=args.required_specialization,
    )
    status, coordinator_response = post_json(
        args.coordinator_api,
        "/route-and-execute",
        task_payload,
        timeout=int(args.coordinator_timeout_s),
    )
    if status >= 400:
        raise RuntimeError(f"Coordinator route-and-execute failed: HTTP {status} {coordinator_response}")

    tool_outputs = extract_tool_outputs(coordinator_response)
    twin_bundle = build_digital_twin_artifact(
        bundle=bundle,
        coordinator_response=coordinator_response,
        tool_outputs=tool_outputs,
    )
    out_path = Path(args.digital_twin_out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(twin_bundle, indent=2), encoding="utf-8")

    print(f"Coordinator task success: {bool(coordinator_response.get('success'))}")
    youtube_output = tool_outputs.get("youtube.publish_video")
    if isinstance(youtube_output, dict):
        print(f"YouTube video URL: {youtube_output.get('video_url')}")
    forensic_output = tool_outputs.get("forensic.seal")
    if isinstance(forensic_output, dict):
        custody_event = forensic_output.get("custody_event")
        if isinstance(custody_event, dict):
            custody_event_ref = (
                custody_event.get("event_id")
                or custody_event.get("id")
                or custody_event.get("hal_capture_id")
            )
            print(f"Forensic custody event: {custody_event_ref}")
    print(f"Wrote digital twin bundle: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
