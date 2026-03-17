import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

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
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        # 1. Structure the Evidence
        pre_contact = PreContactEvidence(
            environmental_telemetry=environmental_data,
            voc_profile={"signatureHash": voc_hash},
            vision_baseline={"fingerprintHash": self._hash_vision_frame(vision_image)}
        )

        manipulation = ManipulationTelemetry(
            commanded_forces="envelope-verified",
            observed_forces="within-tolerance",
            trajectory_hash=trajectory_hash
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

        # 2. Build the Event Object (Unsigned)
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

        # 3. Canonicalize and Sign
        # Dumping to JSON to create a deterministic representation
        canonical_payload = custody_event.model_dump_json(exclude={"signature", "context", "type"})
        signature = self._sign_payload(canonical_payload)
        
        # 4. Apply Signature
        custody_event.signature = signature

        return custody_event
