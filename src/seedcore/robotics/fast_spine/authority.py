"""Existing ExecutionToken shape; explicit Ed25519 trust, no dev-secret fallback."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from types import MappingProxyType

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import SessionSpec, digest

CONSTRAINT_KEYS = (
    "action_type",
    "target_zone",
    "asset_id",
    "principal_agent_id",
    "source_registration_id",
    "registration_decision_id",
    "endpoint_id",
    "plan_dag_hash",
    "payload_hash",
)
PRECONDITION_KEYS = (
    "resource_state_hash",
    "approval_transition_head",
    "context_token",
    "plan_dag_hash",
    "payload_hash",
    "endpoint_id",
)
CLAIM_KEYS = (
    "token_id",
    "intent_id",
    "issued_at",
    "valid_until",
    "contract_version",
    "constraints",
    "execution_preconditions",
)


def utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid token timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("token timestamps require an explicit timezone")
    return parsed.astimezone(timezone.utc)


def kernel_timestamp(value: datetime) -> str:
    """Chrono-compatible UTC serialization (seconds, milliseconds or microseconds)."""
    value = value.astimezone(timezone.utc)
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        fraction = f"{value.microsecond:06d}"
        base += "." + (fraction[:3] if value.microsecond % 1000 == 0 else fraction)
    return base + "Z"


class TokenAuthority:
    def __init__(self, trusted_keys: dict[str, Ed25519PublicKey]):
        if not trusted_keys or any(
            not isinstance(k, Ed25519PublicKey) for k in trusted_keys.values()
        ):
            raise ValueError("explicit Ed25519 trust roots required")
        self.keys = MappingProxyType(dict(trusted_keys))

    def verify(self, token: dict, spec: SessionSpec, *, now: datetime):
        if not isinstance(token, dict) or set(token) != set(CLAIM_KEYS) | {
            "artifact_hash",
            "signature",
        }:
            raise PermissionError("invalid ExecutionToken schema")
        try:
            claims = {name: token[name] for name in CLAIM_KEYS}
            for name in ("token_id", "intent_id", "contract_version"):
                if (
                    not isinstance(claims[name], str)
                    or not 1 <= len(claims[name]) <= 128
                    or not claims[name].isascii()
                ):
                    raise ValueError("invalid token identity")
            constraints, pre = claims["constraints"], claims["execution_preconditions"]
            if set(constraints) != set(CONSTRAINT_KEYS) or set(pre) != set(
                PRECONDITION_KEYS
            ):
                raise ValueError("frozen token binding shape mismatch")
            if any(
                v is not None and (not isinstance(v, str) or not v.isascii())
                for v in (*constraints.values(), *pre.values())
            ):
                raise ValueError("invalid token binding types")
            expected_hash = digest(claims)
            if token["artifact_hash"] != {
                "algorithm": "sha256",
                "value": expected_hash,
            }:
                raise ValueError("token hash mismatch")
            signature = token["signature"]
            if set(signature) != {
                "signer_type",
                "signer_id",
                "signing_scheme",
                "key_ref",
                "attestation_level",
                "signature",
            }:
                raise ValueError("invalid signature envelope")
            if (signature["signing_scheme"], signature["attestation_level"]) != (
                "ed25519",
                "baseline",
            ):
                raise ValueError(
                    "only explicitly trusted simulation signatures are supported"
                )
            key_ref = signature["key_ref"]
            if (
                signature["signer_type"] != "service"
                or signature["signer_id"] != key_ref
            ):
                raise ValueError("untrusted signer identity")
            self.keys[key_ref].verify(
                base64.b64decode(signature["signature"], validate=True),
                expected_hash.encode("ascii"),
            )
            issued, expires = utc(token["issued_at"]), utc(token["valid_until"])
            if token["issued_at"] != kernel_timestamp(issued) or token[
                "valid_until"
            ] != kernel_timestamp(expires):
                raise ValueError("non-canonical token timestamp")
            if (
                now.tzinfo is None
                or not issued <= now < expires
                or (expires - issued).total_seconds() > 5
            ):
                raise ValueError("expired/future/overlong token window")
            if (
                constraints["action_type"] != "MOVE"
                or constraints["principal_agent_id"] != spec.principal_id
            ):
                raise ValueError("action/principal scope mismatch")
            if (
                constraints["endpoint_id"] != spec.endpoint_id
                or pre["endpoint_id"] != spec.endpoint_id
            ):
                raise ValueError("wrong endpoint")
            if (
                constraints["payload_hash"] != spec.sha256
                or pre["payload_hash"] != spec.sha256
            ):
                raise ValueError("session payload binding mismatch")
            # This rehearsal does not accept unsupported live-context obligations.
            if any(
                pre[k] is not None
                for k in PRECONDITION_KEYS
                if k not in {"endpoint_id", "payload_hash"}
            ):
                raise ValueError("unsupported live execution precondition")
            if any(
                constraints[k] is not None
                for k in (
                    "target_zone",
                    "asset_id",
                    "source_registration_id",
                    "registration_decision_id",
                    "plan_dag_hash",
                )
            ):
                raise ValueError("unsupported live authority binding")
            return {
                "token_id": token["token_id"],
                "intent_id": token["intent_id"],
                "token_sha256": digest(token),
                "key_ref": key_ref,
                "expires": expires,
            }
        except Exception as exc:
            raise PermissionError("ExecutionToken rejected: " + str(exc)) from exc
