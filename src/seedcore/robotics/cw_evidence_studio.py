"""Read-only Studio adapter for independently provisioned CW evidence trust.

The browser supplies only bundle bytes. Expected admission context comes from
the service's retained attempt; keys come from an operator-pinned snapshot.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock

from .assembly import canonical_assembly_bytes
from .component_registry import parse_json, sha256
from .cw_evidence import ExpectedContext, MAX_BUNDLE_BYTES, digest, verify_bundle

RUST_BINARY = Path(__file__).resolve().parents[3]/'rust/target/debug/seedcore-verify'
MAX_REPORT_BYTES = 32768


class CwStudioVerifier:
    def __init__(self, trust_bytes: bytes, *, trust_sha256: str):
        if not 0 < len(trust_bytes) <= 32768 or sha256(trust_bytes) != trust_sha256:
            raise ValueError('independently pinned verification trust snapshot required')
        trust = parse_json(trust_bytes)
        canonical_assembly_bytes(trust)
        if (not isinstance(trust, dict) or set(trust) != {'version', 'trusted_keys', 'revoked_keys'}
                or trust['version'] != 'seedcore.cw-g02.simulation-trust.v1'
                or not isinstance(trust['trusted_keys'], dict) or not isinstance(trust['revoked_keys'], list)
                or any(not isinstance(key, str) for key in trust['revoked_keys'])):
            raise ValueError('invalid operator verification trust snapshot')
        if RUST_BINARY.is_symlink() or not RUST_BINARY.is_file():
            raise ValueError('build the local Rust evidence verifier before enabling Studio verification')
        self._binary = RUST_BINARY.resolve(strict=True)
        self._binary_pin = self._binary.stat()
        self._trust = copy.deepcopy(trust)
        self.trust_digest = digest(trust)
        self._gate = Lock()

    def _rust(self, raw, expected):
        stat = self._binary.stat()
        if (stat.st_ino, stat.st_size, stat.st_mtime_ns) != (self._binary_pin.st_ino, self._binary_pin.st_size, self._binary_pin.st_mtime_ns):
            raise RuntimeError('installed verifier changed; restart the reviewed service')
        with TemporaryDirectory(prefix='seedcore-cw-studio-verify-') as directory:
            root = Path(directory)
            for name, data in [('bundle', raw), ('expected', canonical_assembly_bytes(expected)), ('trust', canonical_assembly_bytes(self._trust))]:
                (root/(name+'.json')).write_bytes(data)
            # Files avoid unbounded captured output; the fixed Rust command emits
            # one bounded report. Inputs and transcripts disappear on every exit.
            with (root/'stdout').open('w+b') as stdout, (root/'stderr').open('w+b') as stderr:
                result = subprocess.run([str(self._binary), 'verify-cw-evidence', '--bundle', str(root/'bundle.json'),
                    '--expected', str(root/'expected.json'), '--trust', str(root/'trust.json')],
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=10, check=False)
                stdout.seek(0); data = stdout.read(MAX_REPORT_BYTES+1)
            if not 0 < len(data) <= MAX_REPORT_BYTES:
                raise RuntimeError('Rust verifier report missing or oversized')
            report = parse_json(data)
            if result.returncode != (0 if report.get('verified') is True else 1):
                raise RuntimeError('Rust verifier exit/report disagreement')
            return report, data.decode('utf-8', errors='strict')

    def verify(self, raw: bytes, *, expected: dict, retained_digest: str, summary: dict) -> dict:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BUNDLE_BYTES:
            raise ValueError('bundle must contain 1 byte to 2 MiB')
        expected = ExpectedContext.model_validate(expected).model_dump(mode='json')
        context_digest = digest(expected)
        bundle_digest = sha256(raw)
        response = dict(schemaVersion='seedcore.cw-g02.studio-verification.v1', scope='local_simulation_only',
            physicalAcceptance=False, executionAuthority='none', disposition='unavailable', agreement=False,
            expectedContext=copy.deepcopy(expected), expectedContextDigest=context_digest,
            trustSnapshotDigest=self.trust_digest, bundleSha256=bundle_digest, retainedBundleSha256=retained_digest,
            matchesRetainedBundle=bundle_digest == retained_digest, summary=copy.deepcopy(summary),
            pythonReport=None, rustReport=None, pythonReportJson=None, rustReportJson=None, reason=None)
        if not self._gate.acquire(blocking=False):
            response['reason'] = 'Verification is busy. Retry after the current inspection finishes.'
            return response
        try:
            py = verify_bundle(raw, expected=expected, trust=self._trust)
            response.update(pythonReport=py, pythonReportJson=json.dumps(py, sort_keys=True, allow_nan=False)+'\n')
            rust, rust_json = self._rust(raw, expected)
            response.update(rustReport=rust, rustReportJson=rust_json)
            reports = [py, rust]
            for report in reports:
                if (report.get('schemaVersion') != 'seedcore.cw-g02.verification.v1'
                        or type(report.get('verified')) is not bool or report.get('scope') != 'local_simulation_only'
                        or report.get('physicalAcceptance') is not False or report.get('executionAuthority') != 'none'
                        or report.get('bundleSha256') != bundle_digest
                        or report.get('disposition') not in {'verified_completed', 'verified_interrupted', 'quarantine'}
                        or report['verified'] != (report['disposition'] != 'quarantine')):
                    raise RuntimeError('verifier returned an invalid scoped report')
            fields = ['verified', 'disposition', 'scope', 'physicalAcceptance', 'executionAuthority']
            if py['verified']:
                fields += ['expectedContextDigest', 'trustSnapshotDigest', 'sourceRefs']
            agreement = all(py.get(field) == rust.get(field) for field in fields)
            response['agreement'] = agreement
            if not agreement:
                response.update(disposition='verifier_disagreement', reason='Python and Rust disagree. Evidence remains unverified.')
            elif not response['matchesRetainedBundle']:
                response.update(disposition='quarantine', reason='Inspected bytes differ from the original bundle retained for this attempt.')
            elif not py['verified']:
                response.update(disposition='quarantine', reason='Both verifiers quarantined this simulation evidence. Inspect their reports.')
            elif (py.get('expectedContextDigest') != context_digest or py.get('trustSnapshotDigest') != self.trust_digest):
                raise RuntimeError('verifier context/trust binding mismatch')
            else:
                response.update(disposition=py['disposition'], reason='Both verifiers agree under the configured local simulation trust snapshot.')
        except Exception:
            response.update(disposition='unavailable', agreement=False,
                reason='Evidence verification is unavailable or returned an invalid report. Ask the service operator to inspect the verifier.')
        finally:
            self._gate.release()
        return response
