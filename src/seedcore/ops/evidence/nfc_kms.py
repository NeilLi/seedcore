from __future__ import annotations

import logging
from typing import List, Set, Union

logger = logging.getLogger(__name__)


class NfcKeyRevokedError(Exception):
    """Exception raised when an NFC tag key is revoked."""
    pass


class NfcKmsUnavailableError(Exception):
    """Exception raised when the Key Management Service is unavailable."""
    pass


class NfcKmsClient:
    """Client for retrieving tag-specific derived keys from Key Management Service (KMS).

    Ensures that the Master Key is never exposed or logged.
    """

    def __init__(
        self,
        master_key_hex: str = "",
        revoked_keys: Union[List[str], Set[str], None] = None,
        simulate_unavailable: bool = False,
    ):
        self._config_error: str | None = None
        try:
            self._master_key = bytes.fromhex(str(master_key_hex).strip())
        except Exception:
            self._master_key = b""
            self._config_error = "invalid KMS master key encoding"
        if len(self._master_key) != 16:
            self._master_key = b""
            self._config_error = "invalid KMS master key length"
        self._revoked_keys = set(revoked_keys) if revoked_keys else set()
        self._simulate_unavailable = simulate_unavailable

    def get_tag_derived_key_material(self, nfc_uid_hash: str, cmac_ref: str) -> bytes:
        """Derive a tag-specific AES-128 key using the master key and the tag identity.

        This KDF follows standard symmetric key diversification principles.
        Never logs raw keys, master keys, or raw UIDs.
        """
        if self._simulate_unavailable:
            raise NfcKmsUnavailableError("KMS is currently unreachable")
        if self._config_error is not None:
            raise NfcKmsUnavailableError(self._config_error)

        # Check key revocation
        if cmac_ref in self._revoked_keys:
            logger.warning("Revoked NFC key reference access attempt blocked")
            raise NfcKeyRevokedError("NFC key has been revoked")

        try:
            from cryptography.hazmat.primitives import cmac
            from cryptography.hazmat.primitives.ciphers import algorithms

            uid_hex = nfc_uid_hash
            if uid_hex.startswith("sha256:"):
                uid_hex = uid_hex[7:]

            try:
                uid_bytes = bytes.fromhex(uid_hex)
            except ValueError:
                uid_bytes = uid_hex.encode("utf-8")

            # SV = Diversification constant (1 byte) || System Identifier || UID
            sv = bytes.fromhex("01") + b"NTAG424" + uid_bytes

            c = cmac.CMAC(algorithms.AES(self._master_key))
            c.update(sv)
            derived_key = c.finalize()[:16]

            return derived_key
        except Exception as e:
            logger.error("KMS key derivation failed: %s", str(e))
            raise NfcKmsUnavailableError("Internal KMS error during key derivation") from e
