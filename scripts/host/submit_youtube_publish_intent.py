#!/usr/bin/env python3
"""
Generate and optionally submit a YouTube publish intent through SeedCore's
external authority surface.

Flow:
1. Register owner + assistant DIDs (HMAC signing scheme).
2. Upsert creator profile and trust preferences.
3. Grant delegation owner -> assistant.
4. Run owner-context preflight.
5. Build + sign ActionIntent.
6. Submit signed intent to /api/v1/intents/submit-signed.

By default this script only writes a bundle JSON file under artifacts/demo/.
Pass --submit to call the API.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from seedcore.models.action_intent import ActionIntent
except Exception:  # pragma: no cover - fallback for minimal environments
    ActionIntent = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "seedcore-user"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_external_intent_signing_payload(action_intent: dict[str, Any], *, nonce: str, signed_at: str) -> dict[str, Any]:
    canonical_action_intent: dict[str, Any]
    if ActionIntent is not None:
        canonical_action_intent = ActionIntent.model_validate(action_intent).model_dump(mode="json")
    else:
        canonical_action_intent = action_intent
    return {
        "action_intent": canonical_action_intent,
        "nonce": nonce,
        "signed_at": signed_at,
    }


def post_json(base_url: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.post(url, json=payload, timeout=30)
    body: dict[str, Any]
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    return resp.status_code, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/submit YouTube publish intent via SeedCore")
    parser.add_argument("--base-url", default=os.getenv("SEEDCORE_API", "http://127.0.0.1:8002"))
    parser.add_argument("--owner-email", default="lizi.lining@gmail.com")
    parser.add_argument(
        "--video-path",
        default="artifacts/demo/Robots_Collecting_Priciest_Honey.mp4",
        help="Path to local video file",
    )
    parser.add_argument("--title", default="Robots Collecting Priciest Honey")
    parser.add_argument("--visibility", default="unlisted")
    parser.add_argument("--audience", default="kids")
    parser.add_argument("--thumbnail-mode", default="ai_auto_generate")
    parser.add_argument(
        "--auto-publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether the intent should request automatic publishing after checks pass.",
    )
    parser.add_argument("--owner-did", default="")
    parser.add_argument("--assistant-did", default="")
    parser.add_argument("--hmac-secret", default=os.getenv("SEEDCORE_YOUTUBE_INTENT_HMAC_SECRET", "change-me"))
    parser.add_argument(
        "--bundle-out",
        default="artifacts/demo/youtube_publish_intent_lizi.bundle.json",
        help="Where to write generated bundle",
    )
    parser.add_argument("--submit", action="store_true", help="Also call SeedCore API endpoints")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    signed_at = iso_utc(now)
    valid_until = iso_utc(now + timedelta(minutes=10))
    request_suffix = now.strftime("%Y%m%dT%H%M%SZ")

    email_slug = slugify(args.owner_email.replace("@", "-at-"))
    owner_did = args.owner_did.strip() or f"did:seedcore:owner:{email_slug}"
    assistant_did = args.assistant_did.strip() or f"did:seedcore:assistant:youtube-publisher:{email_slug}"

    video_path = Path(args.video_path).resolve()
    if video_path.exists():
        video_hash = file_sha256(video_path)
        resource_uri = video_path.as_uri()
    else:
        video_hash = sha256_hex(str(video_path))
        resource_uri = f"file://{video_path}"

    intent_id = f"intent-youtube-publish-{request_suffix.lower()}"
    nonce = f"nonce-youtube-publish-{request_suffix.lower()}"
    key_ref = f"hmac:{email_slug}:v1"

    action_parameters = {
        "channel": "youtube",
        "youtube_account_email": args.owner_email,
        "publish_mode": "upload_video",
        "title": args.title,
        "visibility": args.visibility,
        "audience": args.audience,
        "thumbnail": {
            "mode": args.thumbnail_mode,
            "style_hint": "kid_friendly_bright",
            "auto_generate": True,
        },
        "video": {
            "path": str(video_path),
            "sha256": video_hash,
            "content_type": "video/mp4",
        },
        "metadata": {
            "made_for_kids": args.audience.lower() == "kids",
            "auto_publish": bool(args.auto_publish),
        },
    }

    action_intent = {
        "intent_id": intent_id,
        "timestamp": signed_at,
        "valid_until": valid_until,
        "principal": {
            "agent_id": assistant_did,
            "role_profile": "CREATOR_PUBLISHER",
            "session_token": f"session-youtube-publish-{request_suffix.lower()}",
            "actor_token": None,
        },
        "action": {
            "type": "PUBLISH_CONTENT",
            "parameters": action_parameters,
            "security_contract": {
                "hash": f"sha256:{sha256_hex(canonical_json(action_parameters))}",
                "version": "creator-policy@v1",
            },
        },
        "resource": {
            "asset_id": f"media:{video_path.stem.lower().replace('_', '-')}",
            "resource_uri": resource_uri,
            "resource_state_hash": f"sha256:{video_hash}",
            "target_zone": "creator_publish_queue",
            "provenance_hash": f"sha256:{video_hash}",
            "category_envelope": {
                "channel": "youtube",
                "content_type": "video",
                "account_email": args.owner_email,
            },
        },
        "environment": {
            "origin_network": "youtube",
            "break_glass_token": None,
            "break_glass_reason": None,
        },
    }

    signing_payload = build_external_intent_signing_payload(
        action_intent,
        nonce=nonce,
        signed_at=signed_at,
    )
    payload_hash = sha256_hex(canonical_json(signing_payload))
    signature = hmac.new(args.hmac_secret.encode("utf-8"), payload_hash.encode("utf-8"), hashlib.sha256).hexdigest()

    owner_did_payload = {
        "did": owner_did,
        "display_name": "Lizi Lining Creator",
        "signing_scheme": "hmac_sha256",
        "key_ref": f"owner:{key_ref}",
        "metadata": {"source": "submit_youtube_publish_intent.py"},
        "status": "ACTIVE",
    }
    assistant_did_payload = {
        "did": assistant_did,
        "display_name": "Lizi YouTube Publisher Assistant",
        "signing_scheme": "hmac_sha256",
        "key_ref": key_ref,
        "metadata": {"source": "submit_youtube_publish_intent.py"},
        "status": "ACTIVE",
    }
    creator_profile_payload = {
        "owner_id": owner_did,
        "version": "v1",
        "status": "ACTIVE",
        "display_name": "Lizi Lining",
        "brand_handles": {"youtube": args.owner_email},
        "publish_prefs": {
            "allowed_channels": ["youtube"],
            "youtube_default_visibility": args.visibility,
            "youtube_default_audience": args.audience,
            "youtube_thumbnail_mode": args.thumbnail_mode,
            "auto_generate_thumbnail": True,
        },
        "metadata": {"source": "submit_youtube_publish_intent.py"},
    }
    trust_preferences_payload = {
        "owner_id": owner_did,
        "trust_version": "v1",
        "status": "ACTIVE",
        "max_risk_score": 0.7,
        "required_provenance_level": "verified",
        "required_evidence_modalities": ["video_hash", "thumbnail_hash"],
        "updated_by": "submit_youtube_publish_intent.py",
        "metadata": {"use_case": "youtube_publish"},
    }
    delegation_payload = {
        "owner_id": owner_did,
        "assistant_id": assistant_did,
        "authority_level": "signer",
        "scope": ["publish:youtube", "content:upload", "thumbnail:generate"],
        "constraints": {
            "allowed_zones": ["creator_publish_queue"],
            "required_modality": ["video_hash", "thumbnail_hash"],
        },
        "requires_step_up": True,
    }
    owner_context_preflight_payload = {
        "owner_id": owner_did,
        "assistant_id": assistant_did,
        "delegation_id": None,
        "merchant_ref": "platform:youtube",
        "declared_value_usd": 0,
        "required_modalities": ["video_hash", "thumbnail_hash"],
        "available_modalities": ["video_hash", "thumbnail_hash"],
        "observed_provenance_level": "verified",
        "risk_score": 0.2,
    }
    signed_submission_payload = {
        "owner_id": owner_did,
        "action_intent": action_intent,
        "signature": signature,
        "signer_did": assistant_did,
        "signing_scheme": "hmac_sha256",
        "key_ref": key_ref,
        "nonce": nonce,
        "signed_at": signed_at,
    }

    bundle = {
        "generated_at": signed_at,
        "base_url": args.base_url,
        "video_path": str(video_path),
        "owner_email": args.owner_email,
        "owner_did": owner_did,
        "assistant_did": assistant_did,
        "setup_requests": {
            "owner_did_upsert": owner_did_payload,
            "assistant_did_upsert": assistant_did_payload,
            "creator_profile_upsert": creator_profile_payload,
            "trust_preferences_upsert": trust_preferences_payload,
            "delegation_grant": delegation_payload,
            "owner_context_preflight": owner_context_preflight_payload,
        },
        "signed_intent": {
            "signing_payload": signing_payload,
            "payload_hash": payload_hash,
            "submission": signed_submission_payload,
        },
        "notes": [
            "Set SEEDCORE_EXTERNAL_INTENT_HMAC_SECRETS_JSON in the SeedCore API process to include the assistant DID or key_ref secret.",
            "Example: {\"%s\":\"%s\",\"%s\":\"%s\"}" % (assistant_did, args.hmac_secret, key_ref, args.hmac_secret),
            "This script writes a bundle by default; use --submit to call the API.",
        ],
    }

    bundle_out = Path(args.bundle_out).resolve()
    bundle_out.parent.mkdir(parents=True, exist_ok=True)
    bundle_out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Wrote bundle: {bundle_out}")

    if not args.submit:
        print("Dry mode complete. Use --submit after SeedCore API is running.")
        return 0

    sequence = [
        ("/api/v1/identities/dids", owner_did_payload, "owner_did_upsert"),
        ("/api/v1/identities/dids", assistant_did_payload, "assistant_did_upsert"),
        ("/api/v1/creator-profiles", creator_profile_payload, "creator_profile_upsert"),
        ("/api/v1/trust-preferences", trust_preferences_payload, "trust_preferences_upsert"),
        ("/api/v1/delegations", delegation_payload, "delegation_grant"),
    ]

    results: dict[str, Any] = {}
    delegation_id: str | None = None
    for path, payload, key in sequence:
        status, body = post_json(args.base_url, path, payload)
        results[key] = {"status": status, "body": body}
        print(f"{key}: HTTP {status}")
        if status >= 400:
            print(json.dumps(body, indent=2))
            print("Stopping due to failed setup request.")
            return 1
        if key == "delegation_grant":
            delegation_id = str(body.get("delegation_id") or "")

    if delegation_id:
        owner_context_preflight_payload["delegation_id"] = delegation_id
    preflight_status, preflight_body = post_json(
        args.base_url,
        "/api/v1/owner-context/preflight",
        owner_context_preflight_payload,
    )
    results["owner_context_preflight"] = {"status": preflight_status, "body": preflight_body}
    print(f"owner_context_preflight: HTTP {preflight_status}")

    submit_status, submit_body = post_json(
        args.base_url,
        "/api/v1/intents/submit-signed",
        signed_submission_payload,
    )
    results["submit_signed_intent"] = {"status": submit_status, "body": submit_body}
    print(f"submit_signed_intent: HTTP {submit_status}")
    if submit_status >= 400:
        print(json.dumps(submit_body, indent=2))
        print("Signed intent submission failed.")
        return 1

    results_out = bundle_out.with_suffix(".results.json")
    results_out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote results: {results_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
