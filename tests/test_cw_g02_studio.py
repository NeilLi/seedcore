"""Studio trust boundary: actual PDP/native attempts and both real verifiers."""
import copy
import json
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from fastapi.testclient import TestClient
import numpy as np
import pytest

from seedcore.robotics.component_registry import parse_json, sha256
from seedcore.robotics.cw_evidence import CwReceiptSigner, digest, json_bytes, MAX_BUNDLE_BYTES
from seedcore.robotics.cw_evidence_studio import CwStudioVerifier
from seedcore.robotics.mini_studio_api import create_app
from tools.robotics.cw_g01_test_fixture import make_test_service, test_context as make_context
from test_cw_g02_evidence import Clock, source  # shared source-build fixture; no mocked allow decision

HEADERS = {'origin':'http://testserver', 'content-type':'application/json'}


@pytest.fixture
def studio(source, tmp_path, monkeypatch):
    from seedcore.coordinator.core import governance
    clock = Clock(); monkeypatch.setattr(governance, '_utcnow', clock.wall)
    signer = CwReceiptSigner(Ed25519PrivateKey.generate(), 'studio-test-host')
    service, store, key = make_test_service(source, tmp_path, clock=clock, wall_clock=clock.wall,
        receipt_signer=signer, evidence_enabled=True)
    candidate = parse_json(source)['candidate']
    admission = service.admit('studio_attempt', candidate)
    assert admission['state'] == 'admitted', admission
    service.start('studio_attempt', admission['executionToken'], candidate_digest=candidate['candidateDigest'],
                  binding=candidate['binding'], endpoint_id=candidate['endpointId'])
    yield dict(service=service, store=store, clock=clock, signer=signer, key=key, candidate=candidate, admission=admission)
    service.close(); store.close()


def finish(s, ticks=120):
    for _ in range(ticks): s['clock'].step(); s['service'].advance('studio_attempt')
    if ticks < 120: s['service'].cancel('studio_attempt')
    return s['service'].evidence_bundle('studio_attempt')


def post(client, raw, attempt='studio_attempt'):
    return client.post(f'/api/cw-g02/{attempt}/verify', content=raw, headers=HEADERS)


@pytest.mark.parametrize('ticks,outcome', [(120,'verified_completed'),(7,'verified_interrupted')])
def test_real_verifiers_inspect_terminal_bytes_without_mutation(studio, ticks, outcome, monkeypatch):
    s = studio; service = s['service']; raw = finish(s, ticks)
    before = service.status('studio_attempt'); record = service._records['studio_attempt']
    qpos = record['data'].qpos.copy(); deadline = record['deadline']
    def control_forbidden(*a, **kw): raise AssertionError('inspection called a control path')
    for name in ('admit','start','cancel'): monkeypatch.setattr(service,name,control_forbidden)
    with TestClient(create_app(admission_service=service)) as client:
        profile = client.get('/api/cw-g01/profile').json()
        assert profile['evidenceVerificationConfigured'] is True
        result = post(client, raw)
        assert result.status_code == 200, result.text
        r = result.json()
        assert r['disposition'] == outcome and r['agreement'] is True and r['matchesRetainedBundle'] is True
        assert r['physicalAcceptance'] is False and r['executionAuthority'] == 'none'
        assert r['expectedContext'] == s['admission']['evidenceContext']
        assert r['trustSnapshotDigest'] == profile['verificationTrustDigest']
        assert r['bundleSha256'] == r['retainedBundleSha256'] == sha256(raw)
        assert json.loads(r['pythonReportJson']) == r['pythonReport']
        assert json.loads(r['rustReportJson']) == r['rustReport']
        assert r['pythonReport']['disposition'] == r['rustReport']['disposition'] == outcome
        assert client.get('/api/cw-g02/studio_attempt/evidence').content == raw
        assert result.headers['cache-control'] == 'no-store'
        assert service.status('studio_attempt') == before and record['deadline'] == deadline
        np.testing.assert_array_equal(qpos,record['data'].qpos)


@pytest.mark.parametrize('raw', [b'{}', b'{"expectedContext":{},"trust":{"trusted_keys":{}}}', b'NaN'])
def test_uploaded_inputs_never_establish_context_or_trust(studio, raw):
    original = finish(studio)
    with TestClient(create_app(admission_service=studio['service'])) as client:
        r = post(client,raw).json()
        assert r['disposition'] == 'quarantine' and r['matchesRetainedBundle'] is False
        assert r['expectedContext'] == studio['admission']['evidenceContext']
        assert r['retainedBundleSha256'] == sha256(original)
        assert post(client,original,'unknown_attempt').status_code == 404


def test_even_valid_outer_reserialization_must_match_retained_original(studio):
    raw = finish(studio)
    reformatted = json.dumps(parse_json(raw), indent=2).encode()
    with TestClient(create_app(admission_service=studio['service'])) as client:
        r = post(client,reformatted).json()
        assert r['pythonReport']['verified'] is r['rustReport']['verified'] is True
        assert r['matchesRetainedBundle'] is False and r['disposition'] == 'quarantine'
        assert 'retained' in r['reason']


@pytest.mark.parametrize('change', ['revoked_receipt','revoked_token','bad_key','wrong_endpoint'])
def test_operator_snapshot_controls_trust_not_the_bundle(studio, change):
    raw = finish(studio); service = studio['service']
    trust = copy.deepcopy(service._evidence_verifier._trust)
    context = studio['admission']['evidenceContext']
    if change == 'revoked_receipt': trust['revoked_keys'] = [context['receiptKeyRef']]
    elif change == 'revoked_token': trust['revoked_keys'] = [context['tokenKeyRef']]
    elif change == 'bad_key': trust['trusted_keys'].pop(context['receiptKeyRef'])
    else: trust['trusted_keys'][context['receiptKeyRef']]['endpoint_id'] = 'cw_sim://other'
    encoded = json_bytes(trust)
    service._evidence_verifier = CwStudioVerifier(encoded,trust_sha256=sha256(encoded))
    with TestClient(create_app(admission_service=service)) as client:
        r = post(client,raw).json()
        assert r['agreement'] is True and r['disposition'] == 'quarantine'
        assert r['trustSnapshotDigest'] == digest(trust)


@pytest.mark.parametrize('change', ['timeout','failure','invalid_report','disagreement'])
def test_verifier_failure_or_disagreement_never_looks_verified(studio, change, monkeypatch):
    raw = finish(studio); verifier = studio['service']._evidence_verifier
    actual = verifier._rust
    def broken(data, expected):
        if change == 'timeout': raise subprocess.TimeoutExpired('fixed verifier',10)
        if change == 'failure': raise RuntimeError('unavailable')
        report,text = actual(data,expected)
        if change == 'invalid_report': report['scope'] = 'hardware'
        else: report.update(verified=False,disposition='quarantine')
        return report,json.dumps(report)+'\n'
    monkeypatch.setattr(verifier,'_rust',broken)
    with TestClient(create_app(admission_service=studio['service'])) as client:
        before = studio['service'].status('studio_attempt')
        r = post(client,raw).json()
        assert r['disposition'] == ('verifier_disagreement' if change == 'disagreement' else 'unavailable')
        assert r['agreement'] is False and r['physicalAcceptance'] is False
        assert studio['service'].status('studio_attempt') == before


def test_busy_missing_trust_active_and_same_origin_gates(studio):
    service = studio['service']
    with TestClient(create_app(admission_service=service)) as client:
        assert post(client,b'{}').status_code == 409
        raw = finish(studio)
        # The shell's static GET fallback may return 404; neither path verifies.
        assert client.get('/api/cw-g02/studio_attempt/verify').status_code in (404,405)
        assert client.post('/api/cw-g02/studio_attempt/verify',content=raw,headers={'content-type':'application/json'}).status_code == 403
        assert client.post('/api/cw-g02/studio_attempt/verify',content=raw,headers={'origin':'https://other.example','content-type':'application/json'}).status_code == 403
        assert client.post('/api/cw-g02/studio_attempt/verify',content=raw,headers={'origin':'http://testserver','content-type':'text/plain'}).status_code == 415
        assert post(client,b'').status_code == 422
        assert post(client,b'x'*(MAX_BUNDLE_BYTES+1)).status_code == 413
        gate = service._evidence_verifier._gate; gate.acquire()
        try: assert post(client,raw).json()['disposition'] == 'unavailable'
        finally: gate.release()
        service._evidence_verifier = None
        assert client.get('/api/cw-g01/profile').json()['evidenceVerificationConfigured'] is False
        assert post(client,raw).status_code == 409
    with TestClient(create_app()) as client:
        assert post(client,b'{}').status_code == 503


@pytest.mark.parametrize('change', ['valid','missing_field','bad_pin','wrong_schema','malformed_root','writable','symlink'])
def test_explicit_v2_operator_snapshot_configuration(source, tmp_path, change):
    from seedcore.robotics.cw_simulation import native_executor_digest
    from seedcore.robotics.cw_simulation_api import load_cw_simulation_service
    import base64
    review,case = make_context(source)
    (tmp_path/'source.json').write_bytes(source)
    keys = {name:Ed25519PrivateKey.generate() for name in ('pdp','receipt')}
    for name,key in keys.items():
        p = tmp_path/(name+'.pem');p.write_bytes(key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()));p.chmod(0o600)
    endpoint = parse_json(source)['candidate']['endpointId']
    trust = dict(version='seedcore.cw-g02.simulation-trust.v1',trusted_keys={name:dict(key_ref=name,key_algorithm='ed25519',
        public_key=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode(),
        trust_anchor_type='service' if name=='pdp' else 'host_simulation',endpoint_id=endpoint) for name,key in keys.items()},revoked_keys=[])
    if change == 'wrong_schema': trust['version'] = 'untrusted'
    elif change == 'malformed_root': trust = [{}]
    trust_bytes = json_bytes(trust);trust_path = tmp_path/'trust.json';trust_path.write_bytes(trust_bytes);trust_path.chmod(0o644)
    config = dict(schemaVersion='seedcore.cw-g02.service-config.v2',sourcePath='source.json',sourceSha256=sha256(source),
        executorDigest=native_executor_digest(),review=review.model_dump(mode='json'),policyCase=case.model_dump(mode='json'),
        signingKeyPath='pdp.pem',keyRef='pdp',claimStorePath='claims.sqlite',receiptSigningKeyPath='receipt.pem',receiptKeyRef='receipt',
        evidenceTrustPath='trust.json',evidenceTrustSha256=sha256(trust_bytes))
    if change == 'missing_field': config.pop('evidenceTrustPath')
    elif change == 'bad_pin': config['evidenceTrustSha256'] = '0'*64
    elif change == 'writable': trust_path.chmod(0o666)
    elif change == 'symlink':
        alias=tmp_path/'alias.json';alias.symlink_to(trust_path);config['evidenceTrustPath']='alias.json'
    p=tmp_path/'config.json';p.write_bytes(json_bytes(config));p.chmod(0o600)
    if change == 'valid':
        service = load_cw_simulation_service(p)
        try: assert service.describe()['evidenceVerificationConfigured'] is True
        finally: service.close();service._store.close()
    else:
        with pytest.raises(ValueError): load_cw_simulation_service(p)
