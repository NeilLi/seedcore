#!/usr/bin/env python3
"""Retain explicit synthetic CW-G02 fixtures. Never used by normal startup.

Uses real PDP/token/Rust/native code with a test clock, temporary registration
and keys. Exports public test trust material, never private keys or credentials.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from seedcore.robotics.assembly import canonical_assembly_bytes
from seedcore.robotics.component_registry import parse_json, sha256
from seedcore.robotics.cw_evidence import CwReceiptSigner, digest, json_bytes, verify_bundle
from cw_g01_test_fixture import make_test_service


class FixtureClock:
    def __init__(self):
        self.ticks = 0
        self.base = datetime.now(timezone.utc)

    def __call__(self):
        return 100+self.ticks*.002

    def wall(self):
        return self.base+timedelta(milliseconds=self.ticks*2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.source.read_bytes()
    candidate = parse_json(source)['candidate']
    clock = FixtureClock()
    signer = CwReceiptSigner(Ed25519PrivateKey.generate(), 'cw-g02-explicit-test-receipt')
    with TemporaryDirectory(prefix='cw-g02-evidence-fixtures-') as directory, patch(
            'seedcore.coordinator.core.governance._utcnow', clock.wall):
        service, store, key = make_test_service(source, directory, clock=clock, wall_clock=clock.wall, receipt_signer=signer)
        trust = dict(version='seedcore.cw-g02.simulation-trust.v1', trusted_keys={
            service._authority.key_ref: dict(key_ref=service._authority.key_ref, key_algorithm='ed25519',
                public_key=base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
                trust_anchor_type='service', endpoint_id=candidate['endpointId']),
            signer.key_ref: signer.trust_entry(candidate['endpointId'])}, revoked_keys=[])
        (args.out/'trust.json').write_bytes(json_bytes(trust))
        try:
            for label, ticks in [('completed', 120), ('stopped', 7)]:
                request = 'fixture_'+label
                admitted = service.admit(request, candidate)
                if admitted['state'] != 'admitted': raise RuntimeError(admitted)
                service.start(request, admitted['executionToken'], candidate_digest=candidate['candidateDigest'],
                              binding=candidate['binding'], endpoint_id=candidate['endpointId'])
                for _ in range(ticks):
                    clock.ticks += 1
                    service.advance(request)
                if ticks < 120: service.cancel(request)
                raw = service.evidence_bundle(request)
                expected = admitted['evidenceContext']
                report = verify_bundle(raw, expected=expected, trust=trust)
                if not report['verified']: raise RuntimeError(report)
                (args.out/(label+'.bundle.json')).write_bytes(raw)
                (args.out/(label+'.expected.json')).write_bytes(json_bytes(expected))
                (args.out/(label+'.verification.json')).write_bytes(json_bytes(report))
            # A valid host signature cannot excuse a gapped simulated capture.
            bundle = parse_json(raw)
            capture = parse_json(base64.b64decode(bundle['artifacts']['capture']))
            capture['samples'][1]['tick'] = 99
            capture['captureDigest'] = digest({k: v for k, v in capture.items() if k != 'captureDigest'})
            data = canonical_assembly_bytes(capture)
            bundle['artifacts']['capture'] = base64.b64encode(data).decode()
            bundle['receipt']['artifact']['artifactDigests']['capture'] = sha256(data)
            bundle['receipt'] = signer.seal(bundle['receipt']['artifact'])
            gapped = json_bytes(bundle)
            report = verify_bundle(gapped, expected=expected, trust=trust)
            if report['verified']: raise RuntimeError('gapped evidence passed')
            (args.out/'gapped.bundle.json').write_bytes(gapped)
            (args.out/'gapped.verification.json').write_bytes(json_bytes(report))
            trust['revoked_keys'] = [signer.key_ref]
            report = verify_bundle(raw, expected=expected, trust=trust)
            if report['verified']: raise RuntimeError('revoked signer passed')
            (args.out/'revoked-trust.json').write_bytes(json_bytes(trust))
            (args.out/'revoked.verification.json').write_bytes(json_bytes(report))
        finally:
            service.close()
            store.close()
    print('CW-G02 retained completed/stopped and gapped/revoked synthetic fixtures; physical acceptance false.')


if __name__ == '__main__':
    main()
