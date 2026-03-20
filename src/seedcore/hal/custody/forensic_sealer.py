from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from seedcore.models.evidence_bundle import HALCaptureEnvelope
from seedcore.ops.evidence.verification import build_signed_artifact


class ForensicSealer:
    """Builds signed HAL capture envelopes for custody/forensic events."""

    def __init__(self, device_identity: str) -> None:
        self.device_identity = device_identity

    def _canonical_json(self, payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def _hash_payload(self, payload: Any) -> str:
        return "sha256:" + hashlib.sha256(self._canonical_json(payload).encode("utf-8")).hexdigest()

    def seal_custody_event_pilot(
        self,
        *,
        event_id: str,
        platform_state: str,
        policy_hash: str,
        auth_token: str,
        from_zone: str,
        to_zone: str,
        transition_receipt: Optional[Dict[str, Any]] = None,
        actuator_telemetry: Optional[Dict[str, Any]] = None,
        media_hash_references: Optional[List[Dict[str, Any]]] = None,
        trajectory_hash: Optional[str] = None,
        environmental_data: Optional[Dict[str, float]] = None,
    ) -> HALCaptureEnvelope:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        actuator_telemetry = actuator_telemetry if isinstance(actuator_telemetry, dict) else {}
        media_hash_references = [item for item in (media_hash_references or []) if isinstance(item, dict)]
        environmental_data = environmental_data if isinstance(environmental_data, dict) else {}

        transition_receipt_id = (
            transition_receipt.get("transition_receipt_id")
            if isinstance(transition_receipt, dict)
            else None
        )
        if not isinstance(trajectory_hash, str) or not trajectory_hash.strip():
            telemetry_hash = actuator_telemetry.get("trajectory_hash")
            if isinstance(telemetry_hash, str) and telemetry_hash.strip():
                trajectory_hash = telemetry_hash.strip()
            elif isinstance(transition_receipt, dict):
                trajectory_hash = transition_receipt.get("actuator_result_hash")

        payload = {
            "hal_capture_id": str(uuid.uuid4()),
            "event_id": event_id,
            "device_identity": self.device_identity,
            "platform_state": platform_state,
            "policy_receipt_id": policy_hash,
            "transition_receipt_id": transition_receipt_id,
            "media_refs": media_hash_references,
            "environmental_telemetry": {
                str(k): float(v)
                for k, v in environmental_data.items()
                if isinstance(k, str) and isinstance(v, (int, float))
            },
            "trajectory_hash": trajectory_hash if isinstance(trajectory_hash, str) else None,
            "node_id": self.device_identity,
            "captured_at": timestamp,
        }
        _, signer_metadata, signature = build_signed_artifact(
            artifact_type="hal_capture",
            payload=payload,
            endpoint_id=self.device_identity,
            trust_level=(
                "attested"
                if self.device_identity.startswith("hal://") or self.device_identity.startswith("robot_sim://")
                else "baseline"
            ),
            node_id=self.device_identity,
        )
        envelope = HALCaptureEnvelope(
            **payload,
            signer_metadata=signer_metadata,
            signature=signature,
        )
        envelope.media_refs.append(
            {
                "kind": "zone_transition",
                "from_zone": from_zone,
                "to_zone": to_zone,
                "authorization_token": auth_token,
            }
        )
        return envelope

    def seal_custody_event(
        self,
        event_id: str,
        platform_state: str,
        environmental_data: Dict[str, float],
        voc_hash: str,
        vision_image: bytes,
        trajectory_hash: str,
        policy_hash: str,
        auth_token: str,
        from_zone: str,
        to_zone: str,
    ) -> HALCaptureEnvelope:
        media_hash_ref = {
            "source": "legacy_vision_image",
            "sha256": "sha256:" + hashlib.sha256(vision_image).hexdigest(),
            "voc_hash": voc_hash,
        }
        return self.seal_custody_event_pilot(
            event_id=event_id,
            platform_state=platform_state,
            policy_hash=policy_hash,
            auth_token=auth_token,
            from_zone=from_zone,
            to_zone=to_zone,
            transition_receipt=None,
            actuator_telemetry={},
            media_hash_references=[media_hash_ref],
            trajectory_hash=trajectory_hash,
            environmental_data=environmental_data,
        )
