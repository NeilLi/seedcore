#!/usr/bin/env python3
"""Generate strict TPM attestation fixtures for restricted custody receipts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "rust" / "fixtures" / "receipts"
DEFAULT_RECEIPT_FILE = "restricted_transition_receipt_strict_tpm_artifact.json"
DEFAULT_TRUST_BUNDLE_FILE = "restricted_transition_trust_bundle_strict_tpm.json"
AK_PRIVATE_KEY_HEX = "1f3e5d7c9b2a4867fedcba9876543210f1e2d3c4b5a6978877665544332211"
ROOT_PRIVATE_KEY_HEX = "2a4c6e8f1029384756abcdef1234567890fedcba112233445566778899aabb"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_root_certificate(root_key: ec.EllipticCurvePrivateKey) -> x509.Certificate:
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SeedCore Fixtures"),
            x509.NameAttribute(NameOID.COMMON_NAME, "SeedCore TPM Fixture Root CA"),
        ]
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(root_key.public_key())
        .serial_number(0xA1000001)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key=root_key, algorithm=hashes.SHA256())
    )


def _build_ak_certificate(
    *,
    root_key: ec.EllipticCurvePrivateKey,
    root_certificate: x509.Certificate,
    ak_public_key: ec.EllipticCurvePublicKey,
) -> x509.Certificate:
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SeedCore Fixtures"),
            x509.NameAttribute(NameOID.COMMON_NAME, "SeedCore TPM Fixture AK"),
        ]
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_certificate.subject)
        .public_key(ak_public_key)
        .serial_number(0xA1000002)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key=root_key, algorithm=hashes.SHA256())
    )


def _ecdsa_sign_b64(private_key: ec.EllipticCurvePrivateKey, data: bytes) -> str:
    signature = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


def _private_key_from_hex(hex_value: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int(hex_value, 16), ec.SECP256R1())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def generate(output_dir: Path) -> tuple[Path, Path]:
    endpoint_id = "hal://phase-a-edge-strict-01"
    key_ref = "tpm-phase-a-strict-key-01"
    transition_receipt_id = "transition-receipt-phase-a-strict-001"
    receipt_nonce = "nonce-phase-a-strict-001"
    receipt_counter = 7
    ak_key_ref = "ak-phase-a-strict-01"
    pcr_digest = "2a" * 32

    ak_key = _private_key_from_hex(AK_PRIVATE_KEY_HEX)
    root_key = _private_key_from_hex(ROOT_PRIVATE_KEY_HEX)
    root_cert = _build_root_certificate(root_key)
    ak_cert = _build_ak_certificate(
        root_key=root_key,
        root_certificate=root_cert,
        ak_public_key=ak_key.public_key(),
    )

    public_key_material = base64.b64encode(
        ak_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    ).decode("ascii")
    public_key_fingerprint = f"sha256:{hashlib.sha256(public_key_material.encode('utf-8')).hexdigest()}"

    quote_message = {
        "ak_key_ref": ak_key_ref,
        "endpoint_id": endpoint_id,
        "key_ref": key_ref,
        "nonce": receipt_nonce,
        "pcr_digest": pcr_digest,
        "public_key_fingerprint": public_key_fingerprint,
    }
    quote_message_bytes = _canonical_json(quote_message).encode("utf-8")
    quote_signature_b64 = _ecdsa_sign_b64(ak_key, quote_message_bytes)
    quote_payload = json.dumps(
        {
            "format": "seedcore_tpm_quote_v1",
            "message_b64": base64.b64encode(quote_message_bytes).decode("ascii"),
            "signature_b64": quote_signature_b64,
            "nonce": receipt_nonce,
            "pcr_digest": pcr_digest,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )

    receipt_payload_without_signature = {
        "transition_receipt_id": transition_receipt_id,
        "intent_id": "intent-transfer-phase-a-strict-001",
        "execution_token_id": "token-transfer-phase-a-strict-001",
        "endpoint_id": endpoint_id,
        "workflow_type": "custody_transfer",
        "hardware_uuid": "hw-phase-a-strict-001",
        "actuator_result_hash": {
            "algorithm": "sha256",
            "value": "9e36f8ab15790b7e3586a5375db83f6d78559f9ecf1f63e5f7c73f1e32578e47",
        },
        "from_zone": "vault_a",
        "to_zone": "handoff_bay_5",
        "executed_at": "2026-04-02T09:30:10Z",
        "receipt_nonce": receipt_nonce,
    }
    inner_payload_hash = _sha256_hex(_canonical_json(receipt_payload_without_signature))
    inner_signature = _ecdsa_sign_b64(ak_key, inner_payload_hash.encode("utf-8"))

    ak_cert_pem = ak_cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    root_cert_pem = root_cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    transparency_proof_hash = hashlib.sha256(
        f"rekor:{transition_receipt_id}:{inner_payload_hash}".encode("utf-8")
    ).hexdigest()

    receipt_payload = {
        **receipt_payload_without_signature,
        "payload_hash": {"algorithm": "sha256", "value": inner_payload_hash},
        "signer": {
            "signer_type": "hal_endpoint",
            "signer_id": endpoint_id,
            "signing_scheme": "ecdsa_p256_sha256",
            "key_ref": key_ref,
            "attestation_level": "attested",
            "signature": inner_signature,
        },
        "trust_proof": {
            "signer_profile": "receipt",
            "trust_anchor_type": "tpm2",
            "key_algorithm": "ecdsa_p256_sha256",
            "key_ref": key_ref,
            "public_key_fingerprint": public_key_fingerprint,
            "key_binding": {
                "binding_type": "tpm2_ak_binding",
                "key_handle": "0x81010030",
                "key_label": endpoint_id,
                "certificate_chain": [ak_cert_pem],
                "metadata": {"provider_mode": "fixture_strict_tpm"},
            },
            "attestation": {
                "attestation_type": "tpm2_ak_binding",
                "ak_key_ref": ak_key_ref,
                "quote": quote_payload,
                "endorsement_chain": [root_cert_pem],
                "summary": {
                    "endpoint_id": endpoint_id,
                    "node_id": endpoint_id,
                    "attestation_level": "attested",
                    "workflow_type": "custody_transfer",
                },
                "issued_at": "2026-04-02T09:30:10+00:00",
            },
            "replay": {
                "receipt_nonce": receipt_nonce,
                "receipt_counter": receipt_counter,
                "previous_receipt_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
            },
            "revocation_id": f"tpm2:{key_ref}",
            "transparency": {
                "status": "anchored",
                "log_url": "https://rekor.sigstore.dev",
                "entry_id": "rekor-entry-phase-a-strict-001",
                "integrated_time": "2026-04-02T09:30:11+00:00",
                "proof_hash": transparency_proof_hash,
                "details": {"provider": "fixture_strict_tpm"},
            },
        },
    }

    replay_payload = {
        "artifact_type": "transition_receipt",
        "artifact": receipt_payload,
    }
    artifact_hash_hex = _sha256_hex(_canonical_json(replay_payload))
    outer_signature = _ecdsa_sign_b64(ak_key, f"sha256:{artifact_hash_hex}".encode("utf-8"))

    receipt_artifact = {
        "artifact_id": transition_receipt_id,
        **replay_payload,
        "artifact_hash": {"algorithm": "sha256", "value": artifact_hash_hex},
        "signature": {
            "signer_type": "hal_endpoint",
            "signer_id": endpoint_id,
            "signing_scheme": "ecdsa_p256_sha256",
            "key_ref": key_ref,
            "attestation_level": "attested",
            "signature": outer_signature,
        },
        "previous_artifact_hash": None,
    }

    root_fingerprint = hashlib.sha256(
        root_cert.public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    trust_bundle = {
        "version": "phase_a_v1",
        "trusted_keys": {
            key_ref: {
                "key_ref": key_ref,
                "key_algorithm": "ecdsa_p256_sha256",
                "public_key": public_key_material,
                "trust_anchor_type": "tpm2",
                "signer_profile": "receipt",
                "endpoint_id": endpoint_id,
                "node_id": endpoint_id,
                "revocation_id": f"tpm2:{key_ref}",
                "attestation_root": ak_key_ref,
                "metadata": {},
            }
        },
        "endpoint_bindings": {endpoint_id: key_ref},
        "node_bindings": {endpoint_id: key_ref},
        "accepted_trust_anchor_types": ["tpm2"],
        "attestation_roots": {ak_key_ref: f"sha256:{root_fingerprint}"},
        "revoked_keys": [],
        "revoked_nodes": [],
        "revocation_cutoffs": {},
        "transparency": {
            "enabled": True,
            "log_url": "https://rekor.sigstore.dev",
            "public_key": "fixture-rekor-key",
            "metadata": {},
        },
        "metadata": {"attestation_validation_mode": "strict_tpm_v1"},
    }

    receipt_path = output_dir / DEFAULT_RECEIPT_FILE
    bundle_path = output_dir / DEFAULT_TRUST_BUNDLE_FILE
    _write_json(receipt_path, receipt_artifact)
    _write_json(bundle_path, trust_bundle)
    return receipt_path, bundle_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where receipt/trust-bundle fixtures will be written.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    receipt_path, bundle_path = generate(output_dir)
    print(f"Generated strict TPM receipt fixture: {receipt_path}")
    print(f"Generated strict TPM trust bundle fixture: {bundle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
