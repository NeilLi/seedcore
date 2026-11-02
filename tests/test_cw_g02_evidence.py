"""Actual PDP/native exports and independent, adversarial offline verification."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
import pytest

from seedcore.robotics.assembly import canonical_assembly_bytes
from seedcore.robotics.component_registry import parse_json, sha256
from seedcore.robotics.cw_evidence import CwReceiptSigner, digest, json_bytes, verify_bundle, MAX_BUNDLE_BYTES
from tools.robotics.cw_g01_test_fixture import make_test_service, test_context as context_fixture

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = 100.
        self.base = datetime.now(timezone.utc)

    def __call__(self):
        return self.value

    def wall(self):
        return self.base + timedelta(seconds=self.value - 100)

    def step(self):
        self.value += .002


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    try:
        from seedcore.robotics.mujoco_workbench.runtime import require_engine
        require_engine()
        if not (ROOT/'rust/target/debug/seedcore-verify').is_file():
            raise RuntimeError('build the Rust token verifier first')
        if not (ROOT/'ts/node_modules/.bin/tsx').is_file() or not (ROOT/'ts/packages/contracts/dist/index.js').is_file():
            raise RuntimeError('build CW workspaces first')
    except (ImportError, RuntimeError) as error:
        if os.getenv('SEEDCORE_CW_G02_REQUIRE_NATIVE') == '1':
            pytest.fail(str(error))
        pytest.skip(str(error))
    directory = tmp_path_factory.mktemp('cw-g02-source')
    subprocess.run([str(ROOT/'ts/node_modules/.bin/tsx'), 'tools/robotics/export-cw-g01.ts', str(directory)],
                   cwd=ROOT, check=True, capture_output=True)
    return (directory/'endpoint-source.json').read_bytes()


@pytest.fixture
def attempt(source, tmp_path, monkeypatch):
    from seedcore.coordinator.core import governance
    clock = Clock()
    monkeypatch.setattr(governance, '_utcnow', clock.wall)
    signer = CwReceiptSigner(Ed25519PrivateKey.generate(), 'cw-receipt-test-host')
    service, store, key = make_test_service(source, tmp_path, clock=clock, wall_clock=clock.wall, receipt_signer=signer)
    candidate = parse_json(source)['candidate']
    admission = service.admit('evidence_attempt', candidate)
    assert admission['state'] == 'admitted', admission
    service.start('evidence_attempt', admission['executionToken'], candidate_digest=candidate['candidateDigest'],
                  binding=candidate['binding'], endpoint_id=candidate['endpointId'])
    trust = dict(version='seedcore.cw-g02.simulation-trust.v1', trusted_keys={
        service._authority.key_ref: dict(key_ref=service._authority.key_ref, key_algorithm='ed25519',
            public_key=base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
            trust_anchor_type='service', endpoint_id=candidate['endpointId']),
        signer.key_ref: signer.trust_entry(candidate['endpointId'])}, revoked_keys=[])
    yield dict(service=service, store=store, clock=clock, signer=signer, admission=admission,
               expected=admission['evidenceContext'], trust=trust, source=source)
    service.close()
    store.close()


def export(a, ticks=120):
    for _ in range(ticks):
        a['clock'].step()
        a['service'].advance('evidence_attempt')
    if ticks < 120:
        a['service'].cancel('evidence_attempt')
    return a['service'].evidence_bundle('evidence_attempt')


def check(a, raw):
    return verify_bundle(raw, expected=a['expected'], trust=a['trust'])


def rewrite(a, raw, mutate):
    """A trusted host signing invalid content must still fail semantic checks."""
    bundle = parse_json(raw)
    artifacts = {name: parse_json(base64.b64decode(data)) for name, data in bundle['artifacts'].items()}
    manifest = bundle['receipt']['artifact']
    mutate(artifacts, manifest)
    capture = artifacts['capture']
    capture['captureDigest'] = digest({k: v for k, v in capture.items() if k != 'captureDigest'})
    encoded = {name: canonical_assembly_bytes(data) for name, data in artifacts.items()}
    # Preserve the separately pinned source's exact original bytes, including newline.
    encoded['source'] = a['source']
    manifest['artifactDigests'] = {name: sha256(data) for name, data in encoded.items()}
    bundle['artifacts'] = {name: base64.b64encode(data).decode() for name, data in encoded.items()}
    bundle['receipt'] = a['signer'].seal(manifest)
    return json_bytes(bundle)


@pytest.mark.parametrize('ticks,disposition', [(120, 'verified_completed'), (7, 'verified_interrupted')])
def test_actual_pdp_native_export_verifies_and_is_immutable(attempt, ticks, disposition):
    a = attempt
    raw = export(a, ticks)
    report = check(a, raw)
    assert report['verified'] is True, report
    assert report['disposition'] == disposition
    assert report['physicalAcceptance'] is False and report['executionAuthority'] == 'none'
    assert report['trustSnapshotDigest'] == digest(a['trust'])
    assert report['expectedContextDigest'] == digest(a['expected'])
    bundle = parse_json(raw)
    assert base64.b64decode(bundle['artifacts']['source']) == a['source']
    assert parse_json(base64.b64decode(bundle['artifacts']['token'])) == a['admission']['executionToken']
    capture = parse_json(base64.b64decode(bundle['artifacts']['capture']))
    assert capture == a['service'].capture('evidence_attempt') and capture['signed'] is False
    before = a['service'].status('evidence_attempt')
    a['clock'].value += 60  # Historical receipt remains valid after token expiry.
    for _ in range(3):
        assert a['service'].evidence_bundle('evidence_attempt') == raw
        assert check(a, raw)['verified'] is True
    assert a['service'].status('evidence_attempt') == before


@pytest.mark.parametrize('field', ['requestId', 'instanceId', 'endpointId', 'candidateDigest', 'sourceDigest',
                                 'executorDigest', 'reviewDigest', 'tokenDigest', 'payloadHash', 'receiptKeyRef', 'tokenKeyRef', 'admittedAt'])
def test_independent_context_cannot_be_replaced_by_bundle_claims(attempt, field):
    a = attempt
    raw = export(a)
    old = a['expected'][field]
    a['expected'][field] = (('b' if old[0] == 'a' else 'a') + old[1:])
    assert check(a, raw)['disposition'] == 'quarantine'


@pytest.mark.parametrize('field', ['revisionDigest', 'assemblyDigest', 'catalogDigest', 'drcDigest', 'modelDigest', 'authorityEpoch'])
def test_all_revision_bindings_are_independently_fenced(attempt, field):
    raw = export(attempt)
    attempt['expected']['binding'][field] = 99 if field == 'authorityEpoch' else 'f'*64
    assert check(attempt, raw)['verified'] is False


@pytest.mark.parametrize('change', ['receipt_signature', 'receipt_hash', 'capture_bytes', 'missing_artifact', 'extra_artifact',
                                  'unknown_signer', 'revoked_receipt', 'revoked_token', 'wrong_endpoint', 'wrong_anchor', 'debug'])
def test_signature_trust_and_original_bytes_refusals(attempt, change):
    a = attempt
    bundle = parse_json(export(a))
    receipt = bundle['receipt']
    if change == 'receipt_signature': receipt['signature']['signature'] = 'AAAA'
    elif change == 'receipt_hash': receipt['artifact_hash']['value'] = '0'*64
    elif change == 'capture_bytes': bundle['artifacts']['capture'] = base64.b64encode(b'{}').decode()
    elif change == 'missing_artifact': del bundle['artifacts']['token']
    elif change == 'extra_artifact': bundle['artifacts']['extra'] = 'e30='
    elif change == 'unknown_signer': del a['trust']['trusted_keys'][a['signer'].key_ref]
    elif change == 'revoked_receipt': a['trust']['revoked_keys'].append(a['signer'].key_ref)
    elif change == 'revoked_token': a['trust']['revoked_keys'].append(a['expected']['tokenKeyRef'])
    elif change == 'wrong_endpoint': a['trust']['trusted_keys'][a['signer'].key_ref]['endpoint_id'] = 'cw_sim://other'
    elif change == 'wrong_anchor': a['trust']['trusted_keys'][a['signer'].key_ref]['trust_anchor_type'] = 'hardware'
    elif change == 'debug': receipt['signature']['signing_scheme'] = 'debug_hash_v1'
    assert check(a, json_bytes(bundle))['verified'] is False


@pytest.mark.parametrize('change', ['gap', 'duplicate', 'reorder', 'truncated', 'wrong_time', 'wrong_control', 'wrong_body',
                                  'bad_quaternion', 'wrong_dimensions', 'outside_bounds', 'missing_step_checks',
                                  'step_expired', 'step_rollback', 'step_ahead', 'start_expired', 'end_rollback', 'end_expired',
                                  'missing_guards', 'unknown_summary_field', 'unknown_outcome'])
def test_even_validly_signed_conflicting_capture_is_quarantined(attempt, change):
    a = attempt
    raw = export(a)
    def mutate(artifacts, m):
        samples = artifacts['capture']['samples']
        if change == 'gap': samples[1]['tick'] = 5
        elif change == 'duplicate': samples[1] = copy.deepcopy(samples[0])
        elif change == 'reorder': samples[0], samples[1] = samples[1], samples[0]
        elif change == 'truncated': samples.pop()
        elif change == 'wrong_time': samples[1]['simTimeSeconds'] = .2
        elif change == 'wrong_control': samples[1]['ctrl'][0] += .01
        elif change == 'wrong_body': samples[1]['bodies'][0]['nodeId'] = 'other'
        elif change == 'bad_quaternion': samples[1]['bodies'][0]['quaternion_wxyz'] = [0, 0, 0, 0]
        elif change == 'wrong_dimensions': samples[1]['qvel'].pop()
        elif change == 'outside_bounds': samples[1]['qpos'][0] = 5
        elif change == 'missing_step_checks': m['stepCheckedAt'].pop()
        elif change == 'step_expired': m['stepCheckedAt'][-1] = artifacts['token']['valid_until']
        elif change == 'step_rollback': m['stepCheckedAt'][1] = m['startedAt']
        elif change == 'step_ahead': m['stepCheckedAt'] = [m['startedAt']]*120
        elif change == 'start_expired': m['startedAt'] = artifacts['token']['valid_until']
        elif change == 'end_rollback': m['endedAt'] = artifacts['token']['issued_at']
        elif change == 'end_expired': m['endedAt'] = artifacts['token']['valid_until']
        elif change == 'missing_guards': artifacts['capture']['summary']['mutationPathsGuarded'] = []
        elif change == 'unknown_summary_field': artifacts['capture']['summary']['hardwareSafe'] = True
        elif change == 'unknown_outcome': m['reason'] = artifacts['capture']['summary']['reason'] = 'invented_outcome'
    report = check(a, rewrite(a, raw, mutate))
    assert report['disposition'] == 'quarantine', (change, report)


def test_stopped_prefix_cannot_be_relabeled_completed(attempt):
    raw = export(attempt, 7)
    def mutate(artifacts, m):
        m.update(terminalState='completed', reason=None)
        artifacts['capture']['summary'].update(state='completed', reason=None)
    assert check(attempt, rewrite(attempt, raw, mutate))['verified'] is False


@pytest.mark.parametrize('change', ['hardware', 'physical', 'authority'])
def test_signer_cannot_claim_hardware_or_execution_authority(attempt, change):
    raw = export(attempt)
    bundle = parse_json(raw)
    payload = bundle['receipt']['artifact']
    if change == 'hardware': payload['scope'] = 'hardware'
    elif change == 'physical': payload['physicalAcceptance'] = True
    else: payload['executionAuthority'] = 'hardware_endpoint'
    # Sign directly to exercise the importer independently of the producer schema.
    from seedcore.robotics.fast_spine.evidence import seal_receipt
    receipt = seal_receipt(payload, attempt['signer']._key, key_ref=attempt['signer'].key_ref)
    bundle['receipt'] = receipt
    assert check(attempt, json_bytes(bundle))['verified'] is False


@pytest.mark.parametrize('raw', [b'{}', b'{"schemaVersion":1,"schemaVersion":2}', b'NaN', b'1e999', b'['*1000, b'x'*(MAX_BUNDLE_BYTES+1)],
                         ids=['empty', 'duplicate-key', 'nan', 'overflow-number', 'deep-nesting', 'oversized'])
def test_malformed_bounded_import_is_quarantined(attempt, raw):
    report = check(attempt, raw)
    assert report['verified'] is False and report['disposition'] == 'quarantine'


def test_nonfinite_artifact_is_rejected_after_valid_manifest_signature(attempt):
    bundle = parse_json(export(attempt))
    raw = base64.b64decode(bundle['artifacts']['capture']).replace(b'"qvel":[', b'"qvel":[NaN,', 1)
    bundle['artifacts']['capture'] = base64.b64encode(raw).decode()
    bundle['receipt']['artifact']['artifactDigests']['capture'] = sha256(raw)
    bundle['receipt'] = attempt['signer'].seal(bundle['receipt']['artifact'])
    assert check(attempt, json_bytes(bundle))['verified'] is False


def test_export_requires_terminal_nonempty_admitted_capture_and_explicit_signer(attempt):
    a = attempt
    with pytest.raises(PermissionError): a['service'].evidence_bundle('evidence_attempt')
    a['service'].cancel('evidence_attempt')
    with pytest.raises(PermissionError): a['service'].evidence_bundle('evidence_attempt')
    a['service']._receipt_signer = None
    with pytest.raises(PermissionError, match='signer'): a['service'].evidence_bundle('evidence_attempt')


def test_sealing_failure_is_not_execution_success_or_unsigned_fallback(attempt, monkeypatch):
    a = attempt
    for _ in range(4): a['clock'].step(); a['service'].advance('evidence_attempt')
    a['service'].cancel('evidence_attempt')
    before = a['service'].status('evidence_attempt')
    def fail(_): raise RuntimeError('signer unavailable')
    monkeypatch.setattr(a['signer'], 'seal', fail)
    with pytest.raises(RuntimeError, match='signer unavailable'): a['service'].evidence_bundle('evidence_attempt')
    assert 'evidence_bundle' not in a['service']._records['evidence_attempt']
    assert a['service'].status('evidence_attempt') == before
    from fastapi.testclient import TestClient
    from seedcore.robotics.mini_studio_api import create_app
    with TestClient(create_app(admission_service=a['service'])) as client:
        response = client.get('/api/cw-g02/evidence_attempt/evidence')
        assert response.status_code == 503 and 'sealing failed' in response.text
    assert a['service'].status('evidence_attempt') == before


def test_configuration_without_signer_and_active_api_export_fail_closed(attempt):
    from fastapi.testclient import TestClient
    from seedcore.robotics.mini_studio_api import create_app
    with TestClient(create_app(admission_service=attempt['service'])) as client:
        assert client.get('/api/cw-g02/evidence_attempt/evidence').status_code == 409
        attempt['service']._receipt_signer = None
        assert client.get('/api/cw-g02/evidence_attempt/evidence').status_code == 409
    with TestClient(create_app()) as client:
        assert client.get('/api/cw-g02/evidence_attempt/evidence').status_code == 503


def test_original_exports_omit_private_service_credentials(attempt):
    bundle = parse_json(export(attempt))
    for encoded in bundle['artifacts'].values():
        raw = base64.b64decode(encoded)
        assert b'explicit-synthetic-service-session' not in raw
        assert b'PRIVATE KEY' not in raw


def test_fault_capture_is_retained_but_not_accepted_as_operator_interruption(attempt):
    a = attempt
    for _ in range(4): a['clock'].step(); a['service'].advance('evidence_attempt')
    a['store'].revoke(a['admission']['tokenId'])
    a['clock'].step(); a['service'].advance('evidence_attempt')
    raw = a['service'].evidence_bundle('evidence_attempt')
    report = check(a, raw)
    assert report['disposition'] == 'quarantine'
    assert report['sourceRefs']['capture']


def test_readonly_api_export_and_cli_verify_actual_download(attempt, tmp_path):
    from fastapi.testclient import TestClient
    from seedcore.robotics.mini_studio_api import create_app
    a = attempt
    export(a)
    with TestClient(create_app(admission_service=a['service'])) as client:
        before = a['service'].status('evidence_attempt')
        response = client.get('/api/cw-g02/evidence_attempt/evidence')
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert 'attachment' in response.headers['content-disposition']
        assert response.content == a['service'].evidence_bundle('evidence_attempt')
        assert client.post('/api/cw-g02/evidence_attempt/evidence').status_code == 405
        assert client.get('/api/cw-g02/missing/evidence').status_code == 404
        assert a['service'].status('evidence_attempt') == before
        raw = response.content
    bundle, expected, trust = (tmp_path/name for name in ('bundle.json', 'expected.json', 'trust.json'))
    bundle.write_bytes(raw); expected.write_bytes(json_bytes(a['expected'])); trust.write_bytes(json_bytes(a['trust']))
    args = [sys.executable, '-m', 'seedcore.robotics.cw_evidence', '--bundle', str(bundle), '--expected', str(expected), '--trust', str(trust)]
    result = subprocess.run(args, capture_output=True, cwd=ROOT, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['disposition'] == 'verified_completed'
    original = bundle.read_bytes()
    a['trust']['revoked_keys'].append(a['signer'].key_ref); trust.write_bytes(json_bytes(a['trust']))
    result = subprocess.run(args, capture_output=True, cwd=ROOT, check=False)
    assert result.returncode == 1 and json.loads(result.stdout)['disposition'] == 'quarantine'
    assert bundle.read_bytes() == original


def test_versioned_config_requires_explicit_private_receipt_key(source, tmp_path):
    from seedcore.robotics.cw_simulation import native_executor_digest
    from seedcore.robotics.cw_simulation_api import load_cw_simulation_service
    review, case = context_fixture(source)
    (tmp_path/'source.json').write_bytes(source)
    for name in ('pdp', 'receipt'):
        key = tmp_path/(name+'.pem')
        key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        key.chmod(0o600)
    config = dict(schemaVersion='seedcore.cw-g02.service-config.v1', sourcePath='source.json', sourceSha256=sha256(source),
        executorDigest=native_executor_digest(), review=review.model_dump(mode='json'), policyCase=case.model_dump(mode='json'),
        signingKeyPath='pdp.pem', keyRef='configured-pdp', claimStorePath='claims.sqlite',
        receiptSigningKeyPath='receipt.pem', receiptKeyRef='configured-receipt')
    path = tmp_path/'config.json'
    path.write_bytes(json_bytes(config)); path.chmod(0o600)
    service = load_cw_simulation_service(path)
    try: assert service.describe()['signedEvidenceConfigured'] is True
    finally: service.close(); service._store.close()
    (tmp_path/'receipt.pem').chmod(0o644)
    with pytest.raises(ValueError, match='private'): load_cw_simulation_service(path)
    (tmp_path/'receipt.pem').chmod(0o600)
    config.pop('receiptSigningKeyPath'); path.write_bytes(json_bytes(config))
    with pytest.raises(ValueError, match='configuration'): load_cw_simulation_service(path)


def test_real_clock_api_admission_context_and_stopped_download(source, tmp_path):
    from fastapi.testclient import TestClient
    from seedcore.robotics.mini_studio_api import create_app
    signer = CwReceiptSigner(Ed25519PrivateKey.generate(), 'real-clock-receipt')
    service, store, key = make_test_service(source, tmp_path, receipt_signer=signer)
    candidate = parse_json(source)['candidate']
    try:
        with TestClient(create_app(admission_service=service)) as client:
            headers = {'origin': 'http://testserver'}
            response = client.post('/api/cw-g01/admit', json=dict(requestId='real_clock', candidate=candidate), headers=headers)
            assert response.status_code == 200 and response.json()['state'] == 'admitted', response.text
            admitted = response.json()
            context = admitted['evidenceContext']
            assert context['instanceId'] == client.get('/api/cw-g01/profile').json()['instanceId']
            result = client.post('/api/cw-g01/real_clock/start', headers=headers, json=dict(
                executionToken=admitted['executionToken'], candidateDigest=candidate['candidateDigest'],
                binding=candidate['binding'], endpointId=candidate['endpointId']))
            assert result.status_code == 200, result.text
            time.sleep(.02)
            service.advance('real_clock')
            assert client.post('/api/cw-g01/real_clock/cancel', json={'revoke': False}, headers=headers).status_code == 200
            raw = client.get('/api/cw-g02/real_clock/evidence').content
            trust = dict(version='seedcore.cw-g02.simulation-trust.v1', trusted_keys={
                signer.key_ref: signer.trust_entry(candidate['endpointId']), service._authority.key_ref: dict(
                    key_ref=service._authority.key_ref, key_algorithm='ed25519', public_key=base64.b64encode(
                        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
                    trust_anchor_type='service', endpoint_id=candidate['endpointId'])}, revoked_keys=[])
            report = verify_bundle(raw, expected=context, trust=trust)
            assert report['disposition'] == 'verified_interrupted', report
    finally:
        service.close(); store.close()
