"""Versioned host-signed simulation receipts; hardware acceptance is impossible."""

from __future__ import annotations

import base64
from cryptography.hazmat.primitives import serialization

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .contracts import MAX_EVENTS, SessionSpec, digest

FIELDS = {
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
}
OUTCOMES = {
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
}


def simulation_trust_bundle(keys: dict[str, Ed25519PublicKey], *, endpoint_id: str):
    if not endpoint_id.startswith("spine_sim://"):
        raise ValueError("simulation trust cannot bind a hardware endpoint")
    return {
        "version": "seedcore.fast-spine.simulation-trust.v1",
        "trusted_keys": {
            name: {
                "key_ref": name,
                "key_algorithm": "ed25519",
                "public_key": base64.b64encode(
                    key.public_bytes(
                        serialization.Encoding.Raw, serialization.PublicFormat.Raw
                    )
                ).decode("ascii"),
                "trust_anchor_type": "host_simulation",
                "endpoint_id": endpoint_id,
            }
            for name, key in keys.items()
        },
        "revoked_keys": [],
    }


def seal_receipt(
    payload: dict, key: Ed25519PrivateKey, *, key_ref="simulation-receipt-host"
):
    sha = digest(payload)
    return {
        "artifact": payload,
        "artifact_hash": {"algorithm": "sha256", "value": sha},
        "signature": {
            "signer_type": "service",
            "signer_id": key_ref,
            "signing_scheme": "ed25519",
            "key_ref": key_ref,
            "attestation_level": "baseline",
            "signature": base64.b64encode(key.sign(sha.encode("ascii"))).decode(
                "ascii"
            ),
        },
    }


def verify_receipt(
    receipt: dict,
    trusted_keys: dict[str, Ed25519PublicKey],
    *,
    spec: SessionSpec,
    token_sha256: str,
):
    """A caller supplies independently expected action bindings and trusted keys."""
    try:
        if set(receipt) != {"artifact", "artifact_hash", "signature"}:
            raise ValueError("invalid signed receipt shape")
        payload, signature = receipt["artifact"], receipt["signature"]
        if (
            set(payload) != FIELDS
            or payload["schema_version"] != "seedcore.fast-spine.receipt.v1"
        ):
            raise ValueError("receipt schema mismatch")
        if (
            payload["profile"] != "simulation_only"
            or payload["capture_kind"] != "simulated_controller_state"
        ):
            raise ValueError("unsupported/physical capture claim")
        if not payload["endpoint_id"].startswith("spine_sim://"):
            raise ValueError("wrong evidence endpoint profile")
        if (
            payload["session_id"],
            payload["endpoint_id"],
            payload["boot_nonce"],
            payload["token_sha256"],
            payload["spec_sha256"],
            payload["principal_id"],
            payload["policy_sha256"],
            payload["model_sha256"],
        ) != (
            spec.session_id,
            spec.endpoint_id,
            spec.boot_nonce,
            token_sha256,
            spec.sha256,
            spec.principal_id,
            spec.policy_sha256,
            spec.model_sha256,
        ):
            raise ValueError("receipt action/session binding mismatch")
        if (
            payload["capture_complete"] is not True
            or payload["outcome"] not in OUTCOMES
        ):
            raise ValueError("incomplete/invalid outcome evidence")
        sha = digest(payload)
        if receipt["artifact_hash"] != {"algorithm": "sha256", "value": sha}:
            raise ValueError("receipt hash mismatch")
        if (
            signature["signer_type"],
            signature["signer_id"],
            signature["signing_scheme"],
            signature["attestation_level"],
        ) != ("service", signature["key_ref"], "ed25519", "baseline"):
            raise ValueError("invalid receipt signer identity")
        trusted_keys[signature["key_ref"]].verify(
            base64.b64decode(signature["signature"], validate=True), sha.encode("ascii")
        )
        events = payload["events"]
        if (
            not 3 <= len(events) <= MAX_EVENTS
            or events[0]["kind"] != "opened"
            or events[-1]["kind"] != "closed"
        ):
            raise ValueError("missing start/end observations")
        if events[-1].get("reason") != payload["outcome"]:
            raise ValueError("conflicting outcome")
        if payload["outcome"] == "completed":
            applied = [e for e in events if e["kind"] == "applied"]
            if not applied or not any(e["kind"] == "queued" for e in events):
                raise ValueError("no applied motion evidence for completion")
            if events[-1]["positions_urad"] != applied[-1]["positions_urad"]:
                raise ValueError("final state disagrees with applied motion")
        previous = -1
        dimensions = len(events[0]["positions_urad"])
        if dimensions != len(spec.initial_rad):
            raise ValueError("invalid observed joint count")
        for index, event in enumerate(events):
            if type(event["sequence"]) is not int or event["sequence"] != index:
                raise ValueError("evidence sequence gap/replay")
            if type(event["t_ms"]) is not int or not previous <= event["t_ms"] <= 6000:
                raise ValueError("invalid/rolled-back capture clock")
            previous = event["t_ms"]
            positions = event["positions_urad"]
            if len(positions) != dimensions or any(
                type(q) is not int or abs(q) > 10_000_000 for q in positions
            ):
                raise ValueError("invalid simulated observations")
            if any(
                not low * 1_000_000 - 1 <= q <= high * 1_000_000 + 1
                for low, q, high in zip(
                    spec.lower_rad, positions, spec.upper_rad, strict=True
                )
            ):
                raise ValueError("observed state outside admitted envelope")
        return {
            "verified": True,
            "scope": "simulation_only",
            "disposition": "verified_completed"
            if payload["outcome"] == "completed"
            else "verified_interrupted",
            "physical_acceptance": False,
            "error": None,
        }
    except Exception as exc:
        return {
            "verified": False,
            "scope": "simulation_only",
            "disposition": "quarantine",
            "physical_acceptance": False,
            "error": str(exc),
        }
