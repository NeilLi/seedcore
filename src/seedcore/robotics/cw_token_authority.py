"""Explicit service signer for PDP-approved CW simulation claims; no fixture fallback."""
from __future__ import annotations

import base64
import copy
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from seedcore.integrations.rust_kernel import verify_execution_token_with_rust, enforce_execution_token_with_rust
from .assembly import canonical_assembly_bytes
from .component_registry import sha256
from .fast_spine.authority import CLAIM_KEYS, CONSTRAINT_KEYS, PRECONDITION_KEYS, kernel_timestamp, utc


class CwTokenAuthority:
    def __init__(self, key: Ed25519PrivateKey, key_ref: str):
        if not isinstance(key, Ed25519PrivateKey) or not key_ref or not key_ref.isascii() or len(key_ref) > 128:
            raise ValueError('explicit Ed25519 service signer required')
        self._key, self.key_ref = key, key_ref
        self._trust = dict(version='cw-g01-local-simulation-v1', trusted_keys={key_ref: dict(
            key_ref=key_ref, key_algorithm='ed25519', public_key=base64.b64encode(
                key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(), trust_anchor_type='service')})

    def __call__(self, claims: dict) -> dict:
        claims = copy.deepcopy(claims)
        if (set(claims) != set(CLAIM_KEYS) or set(claims['constraints']) != set(CONSTRAINT_KEYS)
                or set(claims['execution_preconditions']) != set(PRECONDITION_KEYS)
                or claims['constraints']['action_type'] != 'MOVE'
                or not str(claims['constraints']['endpoint_id']).startswith('cw_sim://')):
            raise ValueError('configured CW signer rejects other token scopes/shapes')
        for field in ('issued_at', 'valid_until'):
            claims[field] = kernel_timestamp(utc(claims[field]))
        digest = sha256(canonical_assembly_bytes(claims))
        return dict(**claims, artifact_hash=dict(algorithm='sha256', value=digest), signature=dict(
            signer_type='service', signer_id=self.key_ref, signing_scheme='ed25519', key_ref=self.key_ref,
            attestation_level='baseline', signature=base64.b64encode(self._key.sign(digest.encode('ascii'))).decode()))

    def verify(self, token: dict, expected: dict, *, intent_id: str, contract_version: str, now: datetime) -> dict:
        """Check signatures and frozen enforcement through the actual Rust kernels."""
        if set(token) != set(CLAIM_KEYS) | {'artifact_hash', 'signature'}:
            raise PermissionError('invalid token shape')
        signature = token['signature']
        if (signature.get('signing_scheme') != 'ed25519' or signature.get('key_ref') != self.key_ref
                or signature.get('signer_type') != 'service' or signature.get('signer_id') != self.key_ref
                or signature.get('attestation_level') != 'baseline'):
            raise PermissionError('only the explicitly configured service signer is admitted')
        issued, expires = utc(token['issued_at']), utc(token['valid_until'])
        if (not issued <= now < expires or (expires-issued).total_seconds() > 5
                or token['intent_id'] != intent_id or token['contract_version'] != contract_version
                or token['constraints'] != {k: expected[k] for k in CONSTRAINT_KEYS}
                or token['execution_preconditions'] != expected['execution_preconditions']):
            raise PermissionError('token window, intent, profile or execution binding mismatch')
        verified = verify_execution_token_with_rust(token, now=now, trust_bundle=self._trust)
        enforced = enforce_execution_token_with_rust(token, expected, now=now)
        if verified.get('verified') is not True or enforced.get('allowed') is not True:
            raise PermissionError('Rust token verification/enforcement rejected the request')
        return dict(token_id=token['token_id'], key_ref=self.key_ref, expires=expires,
                    token_sha256=sha256(canonical_assembly_bytes(token)))
