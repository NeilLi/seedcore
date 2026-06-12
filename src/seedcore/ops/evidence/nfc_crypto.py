from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Protocol, runtime_checkable

from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms

logger = logging.getLogger(__name__)


@runtime_checkable
class NfcCryptoVerifier(Protocol):
    """Protocol defining cryptographic verification for dynamic NFC evidence."""

    def verify(self, payload: Any, key_material: bytes) -> bool:
        """Verify the dynamic NFC cryptogram or challenge response.

        Args:
            payload: The NFC payload containing hashes, counters, and refs.
            key_material: Cryptographic key material (e.g. derived key).

        Returns:
            True if verification passes, False otherwise.
        """
        ...


class FixtureDynamicNfcVerifier:
    """Verifier for simulated fixture dynamic NFC challenge-responses using HMAC-SHA256."""

    def verify(self, payload: Any, key_material: bytes) -> bool:
        try:
            nfc_uid_hash = payload.nfc_uid_hash
            anchor_profile_ref = payload.anchor_profile_ref
            cmac_ref = payload.cmac_ref
            asset_ref = payload.asset_ref
            workflow_join_key = payload.workflow_join_key
            challenge_nonce = payload.challenge_nonce
            scan_counter = payload.scan_counter
            challenge_response_hash = payload.challenge_response_hash

            tag_material = f"{nfc_uid_hash}|{anchor_profile_ref}|{cmac_ref}"
            # key_material acts as the mock root key here
            tag_key = hmac.new(
                key_material,
                tag_material.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            response_material = f"{asset_ref}|{workflow_join_key}|{challenge_nonce}|{scan_counter}"
            expected_hash = "sha256:" + hmac.new(tag_key, response_material.encode("utf-8"), hashlib.sha256).hexdigest()

            return hmac.compare_digest(expected_hash, challenge_response_hash)
        except Exception as e:
            logger.error("Fixture verification failed with error: %s", str(e))
            return False


class Ntag424SunCmacVerifier:
    """Verifier for standard AES-128 CMAC (SUN cryptograms) from NXP NTAG 424 DNA tags."""

    def verify(self, payload: Any, key_material: bytes) -> bool:
        """Verify AES-128 CMAC over tag UID, scan counter, and optional nonce.

        Never logs raw keys or raw UID/PII.
        """
        try:
            if len(key_material) != 16:
                logger.error("Ntag424 verification requires a 16-byte key.")
                return False

            # Convert scan counter to 3-byte big-endian representation
            counter_bytes = int(payload.scan_counter).to_bytes(3, "big")

            # We use a stable SHA256 of the UID instead of raw UID to preserve privacy,
            # or bytes derived from the nfc_uid_hash if it is already hex-encoded.
            # In NTAG 424 DNA, the CMAC is computed over mirrored data.
            # Mirror data = UID (7 bytes) || Counter (3 bytes) || optional nonce
            # Since raw UID is sensitive, we reconstruct using bytes from nfc_uid_hash.
            # To ensure standard test vectors match, we check if nfc_uid_hash is a hex string
            # representing the UID (length 14 for 7 bytes) or a SHA256 hash.
            uid_hex = payload.nfc_uid_hash
            if uid_hex.startswith("sha256:"):
                uid_hex = uid_hex[7:]

            try:
                uid_bytes = bytes.fromhex(uid_hex)
            except ValueError:
                # If not valid hex, fallback to encoding string
                uid_bytes = uid_hex.encode("utf-8")

            # Construct message payload for CMAC validation
            msg = uid_bytes + counter_bytes
            if payload.challenge_nonce:
                msg += payload.challenge_nonce.encode("utf-8")

            # Compute AES-128 CMAC
            c = cmac.CMAC(algorithms.AES(key_material))
            c.update(msg)
            full_cmac = c.finalize()

            # Truncate CMAC to 8 bytes if the incoming challenge_response_hash is 8 bytes (16 hex chars)
            # or compare full 16 bytes.
            expected_cmac = full_cmac
            incoming_hash = payload.challenge_response_hash
            if incoming_hash.startswith("sha256:"):
                incoming_hash = incoming_hash[7:]

            try:
                incoming_bytes = bytes.fromhex(incoming_hash)
            except ValueError:
                incoming_bytes = incoming_hash.encode("utf-8")

            if len(incoming_bytes) == 8:
                expected_cmac = full_cmac[:8]

            return hmac.compare_digest(expected_cmac, incoming_bytes)
        except Exception as e:
            # Avoid logging payload details for privacy and security
            logger.error("Ntag424 CMAC verification failed: %s", str(e))
            return False
