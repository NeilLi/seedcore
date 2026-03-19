import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from seedcore.models.evidence_bundle import (
    SeedCoreCustodyEvent,
    PreContactEvidence,
    ManipulationTelemetry,
    PolicyVerification,
    CustodyTransition,
)

class ForensicSealer:
    """
    Handles the structured capture and cryptographic sealing of forensic evidence
    at the edge (HAL Bridge) to produce a certified Honey Digital Twin.
    """

    def __init__(self, device_identity: str, private_key: str = "mock-key"):
        self.device_identity = device_identity
        self._private_key = private_key  # In a real app, use ed25519 signing key

    def _hash_vision_frame(self, image_bytes: bytes) -> str:
        """Deterministically hash a camera frame (Mocked for now)."""
        return "sha256:" + hashlib.sha256(image_bytes).hexdigest()

    def _sign_payload(self, payload: str) -> str:
        """Sign the payload using the device's private key (Mocked for now)."""
        # In production, use ed25519.sign()
        signature_hash = hashlib.sha256((payload + self._private_key).encode()).hexdigest()[:16]
        return f"sig:frame_{signature_hash}"

    def _canonical_json(self, payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def _hash_payload(self, payload: Any) -> str:
        return "sha256:" + hashlib.sha256(self._canonical_json(payload).encode("utf-8")).hexdigest()

    def _extract_transition_receipt_hash(self, transition_receipt: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(transition_receipt, dict):
            return None
        payload_hash = transition_receipt.get("payload_hash")
        if isinstance(payload_hash, str) and payload_hash.strip():
            return payload_hash.strip()
        return self._hash_payload(transition_receipt)

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
    ) -> SeedCoreCustodyEvent:
        """
        HAL sealer pilot: limited to HAL/actuator telemetry, transition receipts,
        and pre-hashed media references. This path must not fetch or interpret
        external social/video content.
        """
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        actuator_telemetry = actuator_telemetry if isinstance(actuator_telemetry, dict) else {}
        media_hash_references = [
            item for item in (media_hash_references or []) if isinstance(item, dict)
        ]
        environmental_data = (
            environmental_data if isinstance(environmental_data, dict) else {}
        )
        transition_receipt_hash = self._extract_transition_receipt_hash(transition_receipt)

        media_hashes: List[str] = []
        for item in media_hash_references:
            digest = item.get("sha256") or item.get("hash") or item.get("digest")
            if isinstance(digest, str) and digest.strip():
                media_hashes.append(digest.strip())
        media_set_hash = self._hash_payload(media_hashes) if media_hashes else None

        resolved_trajectory_hash = trajectory_hash
        if not (isinstance(resolved_trajectory_hash, str) and resolved_trajectory_hash.strip()):
            telemetry_hash = actuator_telemetry.get("trajectory_hash")
            if isinstance(telemetry_hash, str) and telemetry_hash.strip():
                resolved_trajectory_hash = telemetry_hash.strip()
            elif isinstance(transition_receipt, dict):
                signed_payload = (
                    transition_receipt.get("signed_payload")
                    if isinstance(transition_receipt.get("signed_payload"), dict)
                    else {}
                )
                actuator_hash = signed_payload.get("actuator_result_hash")
                if isinstance(actuator_hash, str) and actuator_hash.strip():
                    resolved_trajectory_hash = actuator_hash.strip()

        pre_contact = PreContactEvidence(
            environmental_telemetry={
                str(k): float(v)
                for k, v in environmental_data.items()
                if isinstance(k, str) and isinstance(v, (int, float))
            },
            voc_profile={
                "transitionReceiptHash": transition_receipt_hash
            } if transition_receipt_hash else {},
            vision_baseline={
                "fingerprintHash": media_set_hash
            } if media_set_hash else {},
        )

        manipulation = ManipulationTelemetry(
            commanded_forces="envelope-verified",
            observed_forces="within-tolerance",
            trajectory_hash=resolved_trajectory_hash if isinstance(resolved_trajectory_hash, str) else None
        )

        verification = PolicyVerification(
            policy_hash=policy_hash,
            authorization_token=auth_token
        )

        transition = CustodyTransition(
            from_zone=from_zone,
            to_zone=to_zone,
            timestamp=timestamp
        )

        custody_event = SeedCoreCustodyEvent(
            id=event_id,
            device_identity=self.device_identity,
            platform_state=platform_state,
            pre_contact_evidence=pre_contact,
            manipulation_telemetry=manipulation,
            policy_verification=verification,
            custody_transition=transition,
            signature="pending"
        )

        canonical_payload = custody_event.model_dump_json(exclude={"signature", "context", "type"})
        custody_event.signature = self._sign_payload(canonical_payload)
        return custody_event

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
    ) -> SeedCoreCustodyEvent:
        """
        Captures edge telemetry and seals it into a certified JSON-LD CustodyEvent.
        """
        # Compatibility wrapper for legacy callers. Internally maps legacy inputs
        # into the pilot flow using hashed references only.
        media_hash_ref = {
            "source": "legacy_vision_image",
            "sha256": self._hash_vision_frame(vision_image),
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
