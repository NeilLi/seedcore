"""Explicit simulation-only admission fixtures, never a physical PDP issuer.

Used by the localhost rehearsal and tests. It has no credentials, registrations,
production policy state or authority to issue a token for a hardware endpoint.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .authority import CONSTRAINT_KEYS, PRECONDITION_KEYS, kernel_timestamp
from .contracts import SessionSpec, digest


def fixture_spec(joints=3, **changes):
    values = dict(
        session_id=uuid4().hex,
        endpoint_id="spine_sim://tabletop/reference-v1",
        boot_nonce=uuid4().hex,
        principal_id="simulation-operator",
        policy_sha256=digest({"policy": "simulation-lesson-v1"}),
        model_sha256=digest(
            {"model": "quintic-controller-fixture-v1", "joints": joints}
        ),
        duration_ms=1000,
        command_timeout_ms=250,
        heartbeat_timeout_ms=300,
        authority_timeout_ms=250,
        lower_rad=(-0.5,) * joints,
        upper_rad=(0.5,) * joints,
        initial_rad=(0.0,) * joints,
        max_velocity_rad_s=1.0,
        max_acceleration_rad_s2=20.0,
        max_jerk_rad_s3=1000.0,
    )
    values.update(changes)
    return SessionSpec(**values)


def fixture_token(
    spec: SessionSpec,
    key: Ed25519PrivateKey,
    *,
    key_ref="simulation-fixture-pdp",
    now=None,
    token_id=None,
    lifetime_ms=1500,
):
    spec = SessionSpec.model_validate(spec.model_dump(mode="json"))
    now = now or datetime.now(timezone.utc)
    constraints = dict.fromkeys(CONSTRAINT_KEYS)
    constraints.update(
        action_type="MOVE",
        principal_agent_id=spec.principal_id,
        endpoint_id=spec.endpoint_id,
        payload_hash=spec.sha256,
    )
    pre = dict.fromkeys(PRECONDITION_KEYS)
    pre.update(endpoint_id=spec.endpoint_id, payload_hash=spec.sha256)
    claims = {
        "token_id": token_id or uuid4().hex,
        "intent_id": uuid4().hex,
        "issued_at": kernel_timestamp(now),
        "valid_until": kernel_timestamp(now + timedelta(milliseconds=lifetime_ms)),
        "contract_version": "simulation-fixture:fast-spine-v1",
        "constraints": constraints,
        "execution_preconditions": pre,
    }
    sha = digest(claims)
    return {
        **claims,
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
