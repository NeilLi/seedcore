"""Real PDP + Ed25519 + Rust verification + native MuJoCo admission boundary."""
from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
import time

import numpy as np
import pytest

from seedcore.robotics.cw_simulation import hashed
from tools.robotics.cw_g01_test_fixture import make_test_service

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = 100.; self.base = datetime.now(timezone.utc); self.wall_offset = 0.
    def __call__(self): return self.value
    def wall(self): return self.base+timedelta(seconds=self.value-100+self.wall_offset)
    def step(self, ticks=1): self.value += ticks*.002


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    strict=os.getenv('SEEDCORE_CW_G01_REQUIRE_NATIVE')=='1'
    try:
        from seedcore.robotics.mujoco_workbench.runtime import require_engine
        require_engine()
        if not (ROOT/'ts/node_modules/.bin/tsx').is_file() or not (ROOT/'ts/packages/contracts/dist/index.js').is_file():
            raise RuntimeError('CW workspaces must be built first')
    except (ImportError, RuntimeError) as error:
        if strict: pytest.fail(str(error))
        pytest.skip(str(error))
    out = tmp_path_factory.mktemp('cw-g01-source')
    subprocess.run([str(ROOT/'ts/node_modules/.bin/tsx'), 'tools/robotics/export-cw-g01.ts', str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True)
    return (out/'endpoint-source.json').read_bytes()


@pytest.fixture
def setup(source, tmp_path, monkeypatch):
    clock = Clock()
    from seedcore.coordinator.core import governance
    monkeypatch.setattr(governance, '_utcnow', clock.wall)
    service, store, key = make_test_service(source, tmp_path, clock=clock, wall_clock=clock.wall)
    yield service, store, key, clock, json.loads(source)['candidate']
    service.close(); store.close()


def admitted(setup, request_id='attempt_1'):
    service, store, key, clock, candidate = setup
    response = service.admit(request_id, candidate)
    assert response['state'] == 'admitted', json.dumps(response)
    return response


def started(setup, request_id='attempt_1'):
    service, _, _, _, candidate = setup
    response = admitted(setup, request_id)
    service.start(request_id, response['executionToken'], candidate_digest=candidate['candidateDigest'],
                  binding=candidate['binding'], endpoint_id=candidate['endpointId'])
    return response


def test_real_pdp_configured_signature_rust_verification_and_native_completion(setup, source):
    service, store, _, clock, candidate = setup
    response = started(setup)
    assert response['executionToken']['signature']['signing_scheme'] == 'ed25519'
    assert response['tokenVerification'] == 'rust_signature_and_constraints'
    params=service._records['attempt_1']['case'].action_intent.action.parameters
    assert params['cw_build']['executor']['profile']=='seedcore.cw-g01.native-admission.v1'
    assert response['payloadHash']=='sha256:'+hashed({k:v for k,v in params.items() if k!='payload_hash'})
    model = service._mj.MjModel.from_xml_string(json.loads(source)['model']['xml'])
    independent = service._mj.MjData(model)
    forward = service._mj.MjData(model)
    for _ in range(120):
        clock.step(); service.advance('attempt_1')
    capture = service.capture('attempt_1')
    assert capture['summary']['state'] == 'completed' and len(capture['samples']) == 120
    assert capture['physicalAcceptance'] is False and capture['signed'] is False
    for sample in capture['samples']:
        independent.ctrl[:] = sample['ctrl']; service._mj.mj_step(model, independent)
        for name, actual in [('qpos', independent.qpos), ('qvel', independent.qvel), ('qfrcActuator', independent.qfrc_actuator), ('xpos', independent.xpos.reshape(-1))]:
            np.testing.assert_allclose(sample[name], actual, atol=1e-12, rtol=0)
        forward.qpos[:]=independent.qpos;service._mj.mj_forward(model,forward)
        for body,declared in zip(sample['bodies'],json.loads(source)['model']['manifest']['bodies']):
            bid=service._mj.mj_name2id(model,service._mj.mjtObj.mjOBJ_BODY,declared['bodyName'])
            assert body['nodeId']==declared['nodeId']
            np.testing.assert_allclose(body['position_m'],forward.xpos[bid],atol=1e-12,rtol=0)
            np.testing.assert_allclose(body['quaternion_wxyz'],forward.xquat[bid],atol=1e-12,rtol=0)
    with pytest.raises(PermissionError):
        service.start('attempt_1', response['executionToken'], candidate_digest=candidate['candidateDigest'], binding=candidate['binding'], endpoint_id=candidate['endpointId'])
    with pytest.raises(PermissionError): service.admit('attempt_1', candidate)


@pytest.mark.parametrize('change', ['forged', 'future', 'expired', 'wrong_endpoint', 'wrong_payload', 'wrong_principal', 'wrong_epoch', 'debug', 'untrusted_key'])
def test_bad_tokens_cannot_start_or_dispatch(setup, change):
    service, _, _, clock, candidate = setup
    response = admitted(setup); token = copy.deepcopy(response['executionToken'])
    if change == 'forged': token['signature']['signature'] = 'A'*88
    elif change == 'future': token['issued_at'] = (clock.wall()+timedelta(seconds=1)).isoformat()
    elif change == 'expired': clock.value += 5
    elif change == 'wrong_endpoint': token['constraints']['endpoint_id'] = 'cw_sim://other'
    elif change == 'wrong_payload': token['constraints']['payload_hash'] = 'sha256:'+'0'*64
    elif change == 'wrong_principal': token['constraints']['principal_agent_id'] = 'other-agent'
    elif change == 'wrong_epoch': candidate['binding']['authorityEpoch'] += 1
    elif change == 'debug': token['signature']['signing_scheme'] = 'debug_hash_v1'
    elif change == 'untrusted_key': token['signature']['key_ref'] = 'other-key'
    with pytest.raises(PermissionError):
        service.start('attempt_1', token, candidate_digest=candidate['candidateDigest'], binding=candidate['binding'], endpoint_id=candidate['endpointId'])
    assert service.status('attempt_1')['executedSubsteps'] == 0
    assert not service.capture('attempt_1')['samples']


@pytest.mark.parametrize('change', ['token_revoked', 'key_revoked', 'stop', 'clock_rollback', 'wall_rollback', 'stall', 'deadline', 'state', 'timestep', 'authority_unavailable', 'policy_switch', 'capture_overflow'])
def test_each_substep_observes_latched_fences(setup, change):
    service, store, _, clock, _ = setup; response = started(setup)
    for _ in range(5): clock.step(); service.advance('attempt_1')
    r = service._records['attempt_1']
    if change == 'token_revoked': store.revoke(response['tokenId'])
    elif change == 'key_revoked': store.revoke('cw-explicit-test-pdp', kind='key')
    elif change == 'stop': service.cancel('attempt_1')
    elif change == 'clock_rollback': clock.value -= .1
    elif change == 'wall_rollback': clock.wall_offset -= 1
    elif change == 'stall': clock.value += .251
    elif change == 'deadline': clock.value += 5
    elif change == 'state': r['data'].qpos[0] += .1
    elif change == 'timestep': r['model'].opt.timestep = .004
    elif change == 'authority_unavailable': store.close()
    elif change == 'policy_switch': r['schedule'] = tuple((0., 0.) for _ in range(120))
    elif change == 'capture_overflow': r['samples'] = [dict(tick=0)]*120
    clock.step(); service.advance('attempt_1')
    assert service.status('attempt_1')['state'] in {'stopped', 'fenced'}
    assert service.status('attempt_1')['executedSubsteps'] == 5
    assert list(r['data'].ctrl) == [0, 0]
    before = r['data'].qpos.copy()
    clock.value += .1; service.advance('attempt_1')
    np.testing.assert_array_equal(before, r['data'].qpos)


def test_unauthorized_external_forces_are_cleared_before_step(setup):
    service, _, _, clock, _ = setup; started(setup)
    r = service._records['attempt_1']; r['data'].qfrc_applied[:] = 5; r['data'].xfrc_applied[:] = 9
    r['data'].ctrl[:] = 8
    clock.step(); service.advance('attempt_1')
    assert service.status('attempt_1')['executedSubsteps'] == 1
    assert service.status('attempt_1')['clearedExternalMutations'] > 0
    assert np.count_nonzero(r['data'].qfrc_applied) == 0 and np.count_nonzero(r['data'].xfrc_applied) == 0


def test_precancel_and_delayed_admission_cannot_resurrect_attempt(setup, monkeypatch):
    service, _, _, _, candidate = setup
    service.cancel('pre_cancel')
    with pytest.raises(PermissionError): service.admit('pre_cancel', candidate)
    entered, release = threading.Event(), threading.Event(); original = service._authority.verify
    def delayed(*args, **kwargs):
        entered.set(); assert release.wait(5); return original(*args, **kwargs)
    monkeypatch.setattr(service._authority, 'verify', delayed)
    thread = threading.Thread(target=lambda: service.admit('delayed', candidate)); thread.start()
    assert entered.wait(5); service.cancel('delayed'); release.set(); thread.join(5)
    assert not thread.is_alive() and service.status('delayed')['state'] == 'stopped'
    assert service.status('delayed')['executedSubsteps'] == 0


def test_unregistered_semantics_and_changed_content_cannot_be_admitted(setup):
    service, _, _, _, candidate = setup
    candidate['behavior']['joints'][0]['upperRad'] = .01
    candidate['candidateDigest'] = hashed({k:v for k,v in candidate.items() if k != 'candidateDigest'})
    response = service.admit('different_behavior', candidate)
    assert response['state'] == 'denied' and response['executedSubsteps'] == 0


@pytest.mark.parametrize('policy_failure', ['observer', 'missing_registration', 'revoked'])
def test_policy_denial_cannot_reach_configured_signer_or_dispatch(source, tmp_path, monkeypatch, policy_failure):
    from seedcore.coordinator.core import governance
    from seedcore.robotics.cw_token_authority import CwTokenAuthority
    clock=Clock();monkeypatch.setattr(governance,'_utcnow',clock.wall)
    def change(case):
        owner=case.relevant_twin_snapshot['owner']
        if policy_failure=='observer': owner.delegation['delegations'][0]['authority_level']='observer'
        elif policy_failure=='missing_registration': case.approved_source_registrations.clear()
        else: owner.delegation['revoked']=True
    service,store,key=make_test_service(source,tmp_path,clock=clock,wall_clock=clock.wall,case_change=change)
    class RecordingSigner(CwTokenAuthority):
        calls=0
        def __call__(self,claims):
            self.calls+=1
            return super().__call__(claims)
    signer=RecordingSigner(key,service._authority.key_ref);service._authority=signer
    try:
        response=service.admit('policy_denied',json.loads(source)['candidate'])
        assert response['state']=='denied' and response['executedSubsteps']==0
        assert signer.calls==0 and 'executionToken' not in response
        assert not service.capture('policy_denied')['samples']
    finally: service.close();store.close()


def test_rebinding_local_revision_preserves_only_registered_semantics(setup):
    service, _, _, _, candidate = setup
    candidate['binding']['authorityEpoch'] = 9; candidate['binding']['revisionDigest'] = 'a'*64
    gesture = copy.deepcopy(service._profile['gesture']); gesture['draft']['binding'] = candidate['binding']
    candidate['behavior']['gestureDigest'] = hashed({k:v for k,v in gesture.items() if k != 'gestureDigest'})
    candidate['candidateDigest'] = hashed({k:v for k,v in candidate.items() if k != 'candidateDigest'})
    assert service.admit('current_revision', candidate)['state'] == 'admitted'


def test_unsigned_or_scope_widening_minter_is_rejected_before_token_issuance(setup, monkeypatch):
    from seedcore.coordinator.core import governance
    service, _, _, clock, candidate = setup
    c, review = service._resolve(candidate)
    from seedcore.robotics.build_admission import prepare_cw_policy_case
    case = prepare_cw_policy_case(candidate, review=review, current_binding=c.binding, policy_case=service._fresh_case('mint-test'), now=clock.wall())
    def widen(claims):
        claims['constraints']['endpoint_id'] = 'hal://hardware'
        # This fixture signer is deliberately not used as a valid approval path.
        return dict(**claims, artifact_hash={}, signature={})
    with pytest.raises(ValueError, match='changed_claims'):
        governance.evaluate_intent(case, token_minter=widen)


def test_forged_signature_reaches_and_is_rejected_by_actual_rust_verifier(setup):
    service, _, _, clock, _ = setup; response = admitted(setup)
    token = copy.deepcopy(response['executionToken']); token['signature']['signature'] = 'A'*88
    r = service._records['attempt_1']
    with pytest.raises(PermissionError, match='Rust token'):
        service._authority.verify(token, r['expected'], intent_id='attempt_1', contract_version=token['contract_version'], now=clock.wall())
    assert r['tick'] == 0


@pytest.mark.parametrize('window', ['future', 'expired', 'overlong'])
def test_legitimately_signed_invalid_windows_are_refused(setup, window):
    from seedcore.robotics.fast_spine.authority import CLAIM_KEYS
    service, _, _, clock, _ = setup; response = admitted(setup)
    claims = {k:response['executionToken'][k] for k in CLAIM_KEYS}
    issued, expires = {'future':(1,2),'expired':(-2,-1),'overlong':(0,6)}[window]
    claims['issued_at']=(clock.wall()+timedelta(seconds=issued)).isoformat()
    claims['valid_until']=(clock.wall()+timedelta(seconds=expires)).isoformat()
    token=service._authority(claims)  # Valid configured signature; refusal must be temporal.
    r=service._records['attempt_1']
    with pytest.raises(PermissionError, match='window'):
        service._authority.verify(token,r['expected'],intent_id='attempt_1',contract_version=token['contract_version'],now=clock.wall())
    assert r['tick']==0


def test_valid_signature_from_another_root_with_same_key_ref_is_refused(setup):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from seedcore.robotics.cw_token_authority import CwTokenAuthority
    from seedcore.robotics.fast_spine.authority import CLAIM_KEYS
    service, _, _, clock, _ = setup; response=admitted(setup)
    other=CwTokenAuthority(Ed25519PrivateKey.generate(),service._authority.key_ref)
    token=other({k:response['executionToken'][k] for k in CLAIM_KEYS})
    r=service._records['attempt_1']
    with pytest.raises(PermissionError,match='Rust token'):
        service._authority.verify(token,r['expected'],intent_id='attempt_1',contract_version=token['contract_version'],now=clock.wall())
    assert r['tick']==0


def test_durable_claim_survives_service_restart(setup, source, tmp_path):
    from seedcore.robotics.cw_simulation import CwSimulationService
    from seedcore.robotics.fast_spine.store import ClaimStore
    from seedcore.robotics.component_registry import sha256
    service, _, _, clock, candidate = setup; started(setup)
    service.cancel('attempt_1'); service.close()
    store2 = ClaimStore(tmp_path/'claims.sqlite')
    again = CwSimulationService(source, source_sha256=sha256(source), review=service._review, policy_case=service._template,
        authority=service._authority, store=store2, clock=clock, wall_clock=clock.wall, threaded=False, executor_digest=service._executor_digest)
    try:
        response = again.admit('attempt_1', candidate)
        assert response['state'] == 'admitted'
        with pytest.raises(PermissionError, match='replayed token or session'):
            again.start('attempt_1', response['executionToken'], candidate_digest=candidate['candidateDigest'], binding=candidate['binding'], endpoint_id=candidate['endpointId'])
        assert again.status('attempt_1')['executedSubsteps'] == 0
    finally: again.close(); store2.close()


def test_polling_does_not_advance_or_extend_authority(setup):
    service, _, _, clock, _ = setup; started(setup)
    deadline = service._records['attempt_1']['deadline']
    for _ in range(20): service.status('attempt_1')
    assert service._records['attempt_1']['deadline'] == deadline
    assert service.status('attempt_1')['executedSubsteps'] == 0
    clock.step(); service.advance('attempt_1'); service.cancel('attempt_1')
    before = service._records['attempt_1']['data'].qpos.copy()
    for _ in range(20): service.capture('attempt_1'); service.status('attempt_1')
    np.testing.assert_array_equal(before, service._records['attempt_1']['data'].qpos)


def test_closed_http_boundary_same_origin_and_unconfigured_mode(setup):
    from fastapi.testclient import TestClient
    from seedcore.robotics.mini_studio_api import create_app
    service, _, _, _, candidate = setup
    with TestClient(create_app(admission_service=service)) as client:
        assert client.get('/api/cw-g01/profile').json()['configured'] is True
        payload = dict(requestId='api_attempt', candidate=candidate)
        assert client.post('/api/cw-g01/admit', json=payload).status_code == 403
        assert client.post('/api/cw-g01/admit', json=payload, headers={'origin':'https://other.example'}).status_code == 403
        headers={'origin':'http://testserver'}
        assert client.post('/api/cw-g01/admit', json=dict(**payload, principal={}), headers=headers).status_code == 422
        response=client.post('/api/cw-g01/admit', json=payload, headers=headers)
        assert response.status_code == 200 and response.json()['state'] == 'admitted', response.text
        token=response.json()['executionToken']
        r=client.post('/api/cw-g01/api_attempt/start',json=dict(executionToken=token,candidateDigest=candidate['candidateDigest'],binding=candidate['binding'],endpointId=candidate['endpointId']),headers=headers)
        assert r.status_code == 200 and r.json()['state'] == 'running', r.text
        assert client.post('/api/cw-g01/api_attempt/cancel',json={'revoke':False},headers=headers).json()['state'] == 'stopped'
    with TestClient(create_app()) as client:
        assert client.get('/api/cw-g01/profile').json()['configured'] is False
        assert client.post('/api/cw-g01/admit',json=payload,headers={'origin':'http://testserver'}).status_code == 503
        assert client.get('/api/starter').status_code == 200


def test_explicit_private_config_required_and_bad_pins_reject(source, tmp_path):
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    from tools.robotics.cw_g01_test_fixture import test_context
    from seedcore.robotics.component_registry import sha256
    from seedcore.robotics.cw_simulation_api import load_cw_simulation_service
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    review, case = test_context(source)
    (tmp_path/'source.json').write_bytes(source)
    key=tmp_path/'key.pem'; key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption())); key.chmod(0o600)
    config=dict(schemaVersion='seedcore.cw-g01.service-config.v1',sourcePath='source.json',sourceSha256=sha256(source),review=review.model_dump(mode='json'),
        policyCase=case.model_dump(mode='json'),signingKeyPath='key.pem',keyRef='explicit-config-test',claimStorePath='claims.sqlite')
    from seedcore.robotics.cw_simulation import native_executor_digest
    config['executorDigest']=native_executor_digest()
    file=tmp_path/'config.json';file.write_text(json.dumps(config));file.chmod(0o600)
    loaded=load_cw_simulation_service(file)
    assert loaded.describe()['configured'] is True
    loaded.close();loaded._store.close()
    file.chmod(0o644)
    with pytest.raises(ValueError,match='private'): load_cw_simulation_service(file)
    file.chmod(0o600); alias=tmp_path/'alias.json';alias.symlink_to(file)
    with pytest.raises(ValueError,match='private'): load_cw_simulation_service(alias)
    config['sourceSha256']='f'*64;file.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='pinned'): load_cw_simulation_service(file)
    config['sourceSha256']=sha256(source);config['executorDigest']='f'*64;file.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='executor'): load_cw_simulation_service(file)


def test_browser_download_native_parity_if_requested(source):
    import os
    file=os.getenv('SEEDCORE_CW_G01_NATIVE_CAPTURE')
    if not file: pytest.skip('governed browser capture lane not requested')
    from seedcore.robotics.mujoco_workbench.runtime import require_engine
    raw=json.loads(Path(file).read_bytes()); summary=raw['summary']
    assert hashed({k:v for k,v in raw.items() if k!='captureDigest'})==raw['captureDigest']
    assert raw['physicalAcceptance'] is False and raw['signed'] is False
    from seedcore.robotics.component_registry import sha256
    assert raw['sourceDigest']==sha256(source)
    from seedcore.robotics.cw_simulation import native_executor_digest
    assert raw['executorDigest']==native_executor_digest()
    assert summary['state']=='completed' and summary['executedSubsteps']==120
    mj=require_engine();model=mj.MjModel.from_xml_string(json.loads(source)['model']['xml']);data=mj.MjData(model)
    for sample in raw['samples']:
        data.ctrl[:]=sample['ctrl'];mj.mj_step(model,data)
        for name,actual in [('qpos',data.qpos),('qvel',data.qvel),('qfrcActuator',data.qfrc_actuator),('xpos',data.xpos.reshape(-1))]:
            np.testing.assert_allclose(sample[name],actual,atol=1e-12,rtol=0)
