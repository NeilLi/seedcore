"""One explicitly configured, service-owned native CW simulation endpoint.

The browser proposes a candidate and requests start/stop. Only this service owns
MjModel/MjData. There is no serial, RPC actuator, arbitrary XML or control input.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from threading import RLock, Thread, Event
import time
from uuid import uuid4

import numpy as np

from seedcore.models.action_intent import PolicyCase
from .assembly import canonical_assembly_bytes
from .build_admission import BuildBinding, ReviewedSimulationBuild, read_build_candidate, prepare_cw_policy_case, _time
from .component_registry import parse_json, sha256
from .cw_token_authority import CwTokenAuthority
from .fast_spine.store import ClaimStore
from .mujoco_workbench.runtime import require_engine

NATIVE_PROFILE = 'seedcore.cw-g01.native-admission.v1'
REFERENCE_MODEL = '2478a5c6f22e4d46f9f0c130ea2505b16394d699564ffb3007658fa26300fab5'
DT = 0.002
MAX_RECORDS = 128
GUARDS = ['ctrl', 'qfrc_applied', 'xfrc_applied', 'qpos_qvel_act_state', 'opt_timestep', 'policy_model_switch']


def hashed(value):
    return sha256(canonical_assembly_bytes(value))


def native_executor_descriptor():
    """Review pin for this local adapter image and its frozen execution clocks."""
    package=Path(__file__).resolve().parents[1]
    files=['robotics/cw_simulation.py','robotics/cw_simulation_api.py','robotics/cw_token_authority.py','robotics/cw_evidence.py','robotics/build_admission.py',
           'robotics/fast_spine/store.py','coordinator/core/governance.py','integrations/rust_kernel.py']
    return dict(profile=NATIVE_PROFILE,engineVersion='3.15.0',timestepSeconds=DT,maxTicks=120,
                maxSubstepsPerBatch=8,maxStallMs=250,maxWallDurationSeconds=1,
                artifactDigest=hashed([dict(path=p,sha256=sha256((package/p).read_bytes())) for p in files]))


def native_executor_digest():
    return hashed(native_executor_descriptor())


class CwSimulationService:
    def __init__(self, source: bytes, *, source_sha256: str, review: ReviewedSimulationBuild,
                 policy_case: PolicyCase, authority: CwTokenAuthority, store: ClaimStore,
                 executor_digest: str, receipt_signer=None,
                 clock=time.monotonic, wall_clock=lambda: datetime.now(timezone.utc), threaded=True):
        if len(source) > 262144 or sha256(source) != source_sha256:
            raise ValueError('independently pinned endpoint source required')
        profile = parse_json(source)
        if (set(profile) != {'schemaVersion', 'scope', 'physicalAcceptance', 'executionAuthority', 'candidate', 'model', 'gesture', 'frames'}
                or profile['schemaVersion'] != 'seedcore.cw-g01.endpoint-source.v1'
                or profile['scope'] != 'offline_simulation_only' or profile['physicalAcceptance'] is not False
                or profile['executionAuthority'] != 'none'):
            raise ValueError('unsupported endpoint source scope')
        candidate = read_build_candidate(profile['candidate'])
        model = profile['model']; gesture = profile['gesture']
        if (model['modelDigest'] != REFERENCE_MODEL or hashed({k: v for k, v in model.items() if k != 'modelDigest'}) != REFERENCE_MODEL
                or candidate.binding.modelDigest != REFERENCE_MODEL or candidate.behavior.totalTicks != 120
                or hashed({k: v for k, v in gesture.items() if k != 'gestureDigest'}) != gesture['gestureDigest']
                or gesture['gestureDigest'] != candidate.behavior.gestureDigest
                or gesture['draft']['binding'] != candidate.binding.model_dump(mode='json')
                or len(profile['frames']) != 120):
            raise ValueError('only the pinned two-joint CW-S04 reference is supported')
        self._profile = copy.deepcopy(profile)
        self._source_bytes = bytes(source)
        self._instance_id = uuid4().hex
        if receipt_signer is not None:
            from .cw_evidence import CwReceiptSigner
            if (not isinstance(receipt_signer, CwReceiptSigner) or receipt_signer.key_ref == authority.key_ref
                    or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,128}', authority.key_ref)):
                raise ValueError('separate-purpose explicit receipt signer required')
        self._receipt_signer = receipt_signer
        self._source_sha = source_sha256
        self._review = ReviewedSimulationBuild.model_validate_json(review.model_dump_json())
        self._executor=native_executor_descriptor();self._executor_digest=hashed(self._executor)
        if executor_digest!=self._executor_digest:
            raise ValueError('reviewed executor digest does not match this installed adapter/clock profile')
        if review.resourceStateHash!='sha256:'+hashed(dict(sourceDigest=source_sha256,executorDigest=executor_digest)):
            raise ValueError('trusted review must bind both the source and native executor')
        if review.candidateDigest != candidate.candidateDigest or review.endpointId != candidate.endpointId:
            raise ValueError('configured review does not pin the endpoint source')
        self._template = PolicyCase.model_validate(policy_case.model_dump(mode='json'))
        self._clock, self._wall, self._threaded = clock, wall_clock, threaded
        # Validate the baseline trusted review and context without minting a token.
        prepare_cw_policy_case(profile['candidate'], review=self._review, current_binding=candidate.binding,
                               policy_case=self._fresh_case('startup-check'), now=wall_clock())
        self._authority, self._store = authority, store
        self._mj = require_engine()
        self._records = {}; self._lock = RLock(); self._closed = False
        self._threads = []; self._shutdown = Event()
        self._baseline = candidate
        # Trusted frames are additionally checked against compiled data at startup.
        for index, frame in enumerate(profile['frames']):
            if set(frame) != {'tick', 'targetRad', 'virtualLed'} or frame['tick'] != index+1:
                raise ValueError('invalid required control-frame inventory')
            targets = self._targets(index+1)
            if frame['targetRad'] != targets or not re.fullmatch(r'#[0-9a-f]{6}', frame['virtualLed']):
                raise ValueError('control frames differ from compiled gesture')
        self._controls = tuple(tuple(f['targetRad']) for f in profile['frames'])
        self._cues = tuple(f['virtualLed'] for f in profile['frames'])

    def _fresh_case(self, request_id):
        case = PolicyCase.model_validate(self._template.model_dump(mode='json'))
        now = self._wall() if hasattr(self, '_wall') else datetime.now(timezone.utc)
        case.action_intent.intent_id = request_id
        case.action_intent.timestamp = now.isoformat()
        case.action_intent.valid_until = min(now+timedelta(seconds=5), _time(self._review.validUntil)).isoformat()
        return case

    def _targets(self, tick):
        g = self._profile['gesture']; draft = g['draft']
        duration = draft['durationTicks']*draft['timeScale']
        local = duration if tick == g['totalTicks'] else tick % duration
        result = []
        for index, track in enumerate(g['tracks']):
            knot = next((k for k in draft['tracks'][index]['knots'] if k['tick']*draft['timeScale'] == local), None)
            if knot is not None:
                result.append(knot['positionRad']); continue
            s = next(s for s in track['segments'] if local <= s['endTick'])
            a, b, c, d = s['coefficients']; u = (local-s['startTick'])/(s['endTick']-s['startTick'])
            result.append(((a*u+b)*u+c)*u+d)
        return result

    def describe(self):
        return dict(configured=True, profile=NATIVE_PROFILE, endpointId=self._review.endpointId,
                    modelDigest=REFERENCE_MODEL, sourceDigest=self._source_sha, scope='local_simulation_only',
                    executorDigest=self._executor_digest, instanceId=self._instance_id,
                    signedEvidenceConfigured=self._receipt_signer is not None,
                    physicalAcceptance=False, requiresAdmission=True, maxTicks=120, timestepSeconds=DT,
                    maxWallDurationSeconds=1, limitations=['synthetic_reference_only', 'unsigned_capture', 'no_hardware_endpoint'])

    def _resolve(self, raw):
        c = read_build_candidate(raw)
        baseline = self._baseline.model_dump(mode='json')
        # Only local revision/epoch vary. Assembly/catalog/DRC/model and every
        # semantic behavior/runtime field still come from the separately pinned source.
        for field in ('assemblyDigest', 'catalogDigest', 'drcDigest', 'modelDigest'):
            if getattr(c.binding, field) != getattr(self._baseline.binding, field):
                raise PermissionError('build is outside the registered reference profile')
        binding = c.binding.model_dump(mode='json')
        gesture = copy.deepcopy(self._profile['gesture']); gesture['draft']['binding'] = binding
        gesture['gestureDigest'] = hashed({k: v for k, v in gesture.items() if k != 'gestureDigest'})
        baseline['binding'] = binding
        baseline['behavior']['gestureDigest'] = gesture['gestureDigest']
        baseline['candidateDigest'] = hashed({k: v for k, v in baseline.items() if k != 'candidateDigest'})
        if canonical_assembly_bytes(c.model_dump(mode='json')) != canonical_assembly_bytes(baseline):
            raise PermissionError('gesture/runtime/endpoint differs from the registered reference')
        review = self._review.model_dump(mode='json'); review['candidateDigest'] = c.candidateDigest
        return c, ReviewedSimulationBuild.model_validate_json(json.dumps(review))

    def admit(self, request_id: str, raw):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', request_id):
            raise ValueError('bounded request identity required')
        with self._lock:
            if self._closed or request_id in self._records or len(self._records) >= MAX_RECORDS:
                raise PermissionError('closed, duplicate or full admission registry')
            record = dict(id=request_id, state='checking', reason=None, samples=[], tick=0, cleared=0)
            self._records[request_id] = record
        try:
            from seedcore.coordinator.core.governance import evaluate_intent, _build_execution_constraints, _build_execution_preconditions
            candidate, review = self._resolve(raw)
            case = prepare_cw_policy_case(candidate.model_dump(mode='json'), review=review, current_binding=candidate.binding,
                                          policy_case=self._fresh_case(request_id), now=self._wall())
            # The candidate describes the compiler/browser reference. The actual
            # native executor is a separate, explicitly reviewed signed binding.
            params=case.action_intent.action.parameters;params.pop('payload_hash')
            params['cw_build']['executor']=copy.deepcopy(self._executor)
            params['payload_hash']='sha256:'+hashed(params)
            decision = evaluate_intent(case, token_minter=self._authority)
            if decision.allowed is not True or decision.disposition != 'allow' or decision.execution_token is None:
                with self._lock:
                    if record['state'] == 'checking': record.update(state='denied', reason=decision.deny_code or decision.reason)
                return self.status(request_id)
            expected = _build_execution_constraints(case.action_intent)
            expected['execution_preconditions'] = _build_execution_preconditions(case.action_intent).model_dump(mode='json')
            token = decision.execution_token.model_dump(mode='json')
            claims = self._authority.verify(token, expected, intent_id=request_id,
                                            contract_version=case.action_intent.action.security_contract.version, now=self._wall())
            with self._lock:
                if record['state'] != 'checking' or self._closed:
                    return self.status(request_id)
                if self._store.is_revoked(claims['token_id'], claims['key_ref']):
                    raise PermissionError('revoked before admission completed')
                record.update(state='admitted', candidate=candidate.model_dump(mode='json'), token=token, claims=claims, expected=expected,
                              review=review, case=case, admittedAt=self._wall().isoformat())
                response = self.status(request_id); response['executionToken'] = copy.deepcopy(token)
                if self._receipt_signer is not None:
                    from .cw_evidence import ExpectedContext
                    record['evidence_context'] = ExpectedContext.model_validate(dict(
                        schemaVersion='seedcore.cw-g02.expected.v1', requestId=request_id, instanceId=self._instance_id,
                        endpointId=candidate.endpointId, admittedAt=record['admittedAt'], candidateDigest=candidate.candidateDigest,
                        binding=candidate.binding.model_dump(mode='json'), sourceDigest=self._source_sha,
                        executorDigest=self._executor_digest, reviewDigest=hashed(review.model_dump(mode='json')),
                        tokenDigest=hashed(token), payloadHash=token['constraints']['payload_hash'],
                        tokenKeyRef=self._authority.key_ref, receiptKeyRef=self._receipt_signer.key_ref)).model_dump(mode='json')
                    response['evidenceContext'] = copy.deepcopy(record['evidence_context'])
                return response
        except Exception as error:
            with self._lock:
                if record['state'] == 'checking': record.update(state='denied', reason=f'{type(error).__name__}: {str(error)[:300]}')
            return self.status(request_id)

    def _make_model(self):
        model = self._mj.MjModel.from_xml_string(self._profile['model']['xml'])
        manifest = self._profile['model']['manifest']
        if (model.nq, model.nv, model.nu, model.njnt, model.nbody) != (2, 2, 2, 2, len(manifest['bodies'])+1) or model.opt.timestep != DT:
            raise PermissionError('native model dimensions/clock mismatch')
        for index, joint in enumerate(manifest['joints']):
            if (self._mj.mj_name2id(model, self._mj.mjtObj.mjOBJ_JOINT, joint['jointName']) != index
                    or self._mj.mj_name2id(model, self._mj.mjtObj.mjOBJ_ACTUATOR, joint['actuatorName']) != index
                    or model.actuator_gainprm[index, 0] != 1 or model.qpos0[index] != joint['restAngleRad']):
                raise PermissionError('native joint/actuator/home mapping mismatch')
        return model

    def start(self, request_id, token, *, candidate_digest, binding, endpoint_id):
        with self._lock:
            r = self._records[request_id]
            if r['state'] != 'admitted' or self._closed:
                raise PermissionError('fresh admission required; attempts never resume')
            if (hashed(token) != hashed(r['token']) or candidate_digest != r['candidate']['candidateDigest']
                    or binding != r['candidate']['binding'] or endpoint_id != self._review.endpointId):
                self._fence(r, 'execution binding changed'); raise PermissionError('execution binding changed')
            if any(x is not r and x['state'] in {'starting', 'running'} for x in self._records.values()):
                self._fence(r, 'endpoint_busy'); raise PermissionError('endpoint is busy')
            r['state'] = 'starting'
        try:
            self._authority.verify(token, r['expected'], intent_id=request_id,
                                   contract_version=r['case'].action_intent.action.security_contract.version, now=self._wall())
            model = self._make_model(); data = self._mj.MjData(model); display = self._mj.MjData(model)
            self._mj.mj_forward(model, data)
            with self._lock:
                if r['state'] != 'starting' or self._closed: return self.status(request_id)
                self._store.claim(token_id=r['claims']['token_id'], token_hash=r['claims']['token_sha256'],
                                  endpoint=endpoint_id, session_id=request_id, key_ref=r['claims']['key_ref'])
                now, wall = self._clock(), self._wall()
                if not math.isfinite(now) or not _time(token['issued_at']) <= wall < r['claims']['expires']:
                    raise PermissionError('authority/clock expired during verification or claim')
                r.update(state='running', model=model, data=data, display=display, started=now, last=now, last_wall=wall,
                         deadline=min(now+1, now+(r['claims']['expires']-wall).total_seconds()), samples=[], tick=0,
                         pinned_model=model, schedule=self._controls, executor_digest=self._executor_digest,
                         startedAt=wall.isoformat(), step_checks=[])
                r['state_snapshot'] = self._state_snapshot(r)
                self._check(r, now)
                if self._threaded and r['state'] == 'running':
                    thread = Thread(target=self._drive, args=(request_id,), daemon=True)
                    self._threads.append(thread); thread.start()
                return self.status(request_id)
        except Exception as error:
            with self._lock: self._fence(r, str(error))
            raise PermissionError('governed simulation start rejected: '+str(error)) from error

    def _state_snapshot(self, r):
        d = r['data']
        return np.concatenate((d.qpos.copy(), d.qvel.copy(), d.act.copy(), d.qacc_warmstart.copy(), [d.time]))

    def _clear(self, r):
        d = r.get('data')
        if d is not None:
            r['cleared'] += int(np.count_nonzero(d.qfrc_applied))+int(np.count_nonzero(d.xfrc_applied))
            d.ctrl[:] = 0; d.qfrc_applied[:] = 0; d.xfrc_applied[:] = 0

    def _fence(self, r, reason, state='fenced'):
        if r['state'] not in {'completed', 'stopped', 'fenced', 'denied'}:
            self._clear(r); r.update(state=state, reason=reason, endedAt=self._wall().isoformat())

    def _check(self, r, now):
        if r['state'] != 'running': return False
        wall = self._wall()
        reason = None
        if not math.isfinite(now) or now < r['last'] or wall < r['last_wall']: reason = 'clock_rollback'
        elif now-r['last'] > .25 or now-r['started']-r['tick']*DT > .25: reason = 'clock_stall'
        elif now >= r['deadline'] or wall >= r['claims']['expires']: reason = 'attempt_deadline'
        elif wall >= _time(r['review'].validUntil): reason = 'review_expired'
        else:
            try:
                if self._store.is_revoked(r['claims']['token_id'], r['claims']['key_ref']): reason = 'revoked'
            except Exception: reason = 'authority_unavailable'
        if reason:
            self._fence(r, reason); return False
        r['last'], r['last_wall'] = now, wall
        return True

    def advance(self, request_id):
        with self._lock:
            r = self._records[request_id]; now = self._clock()
            if not self._check(r, now): return self.status(request_id)
            due = min(8, max(0, int((now-r['started'])/DT+1e-7)-r['tick']))
            for _ in range(due):
                if not self._check(r, self._clock()): break
                d, model = r['data'], r['model']
                if model is not r['pinned_model'] or r['schedule'] is not self._controls or r['executor_digest']!=self._executor_digest:
                    self._fence(r, 'policy_model_switch'); break
                if model.opt.timestep != DT:
                    self._fence(r, 'timestep_altered'); break
                if not np.array_equal(self._state_snapshot(r), r['state_snapshot']):
                    self._fence(r, 'external_state_tampered'); break
                if len(r['samples']) >= 120:
                    self._fence(r, 'capture_overflow'); break
                self._clear(r)
                target = np.asarray(r['schedule'][r['tick']])
                limits = r['case'].action_intent.action.parameters['cw_build']['intersectedLimits']
                if (target.shape != (2,) or not np.isfinite(target).all()
                        or any(not lim['lowerRad'] <= q <= lim['upperRad'] for q, lim in zip(target, limits))
                        or np.any(target < model.actuator_ctrlrange[:, 0]) or np.any(target > model.actuator_ctrlrange[:, 1])):
                    self._fence(r, 'control_out_of_range'); break
                d.ctrl[:] = target
                # Recheck current authority after control preparation, immediately before mj_step.
                if not self._check(r, self._clock()): break
                try:
                    self._mj.mj_step(model, d)
                    r['tick'] += 1
                    if not np.isfinite(self._state_snapshot(r)).all():
                        self._fence(r, 'nonfinite_engine_state'); break
                    r['state_snapshot'] = self._state_snapshot(r)
                    display = r['display']; display.qpos[:] = d.qpos
                    self._mj.mj_forward(model, display)  # FK on separate data; never inject state into the solver.
                    bodies = []
                    for b in self._profile['model']['manifest']['bodies']:
                        bid = self._mj.mj_name2id(model, self._mj.mjtObj.mjOBJ_BODY, b['bodyName'])
                        bodies.append(dict(nodeId=b['nodeId'], position_m=display.xpos[bid].tolist(), quaternion_wxyz=display.xquat[bid].tolist()))
                    r['samples'].append(dict(tick=r['tick'], simTimeSeconds=float(d.time), qpos=d.qpos.tolist(), qvel=d.qvel.tolist(),
                                             ctrl=d.ctrl.tolist(), qfrcActuator=d.qfrc_actuator.tolist(), xpos=d.xpos.reshape(-1).tolist(),
                                             bodies=bodies, virtualLed=self._cues[r['tick']-1]))
                    r['step_checks'].append(r['last_wall'].isoformat())
                    if r['tick'] == 120:
                        r.update(state='completed', reason=None, endedAt=self._wall().isoformat()); break
                except Exception:
                    self._fence(r, 'engine_step_failed'); break
            return self.status(request_id)

    def _drive(self, request_id):
        while not self._shutdown.wait(.002):
            try:
                if self.advance(request_id)['state'] != 'running': return
            except Exception:
                with self._lock: self._fence(self._records[request_id], 'executor_failed')
                return

    def cancel(self, request_id, *, revoke=False, reason='operator_stop'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', request_id): raise ValueError('invalid request identity')
        with self._lock:
            if request_id not in self._records:
                if len(self._records) >= MAX_RECORDS: raise PermissionError('cancellation registry full')
                self._records[request_id] = dict(id=request_id, state='stopped', reason=reason, samples=[], tick=0, cleared=0)
            r = self._records[request_id]
            if revoke and 'claims' in r: self._store.revoke(r['claims']['token_id'])
            self._fence(r, 'revoked' if revoke else reason, 'fenced' if revoke else 'stopped')
            return self.status(request_id)

    def status(self, request_id):
        with self._lock:
            r = self._records[request_id]
            if r['state'] == 'admitted' and (self._wall() >= r['claims']['expires'] or self._wall() >= _time(r['review'].validUntil)):
                self._fence(r, 'admission_expired')
            result = dict(id=request_id, state=r['state'], reason=r['reason'], executedSubsteps=r['tick'], totalSubsteps=120,
                          profile=NATIVE_PROFILE, scope='local_simulation_only', physicalAcceptance=False,
                          executionAuthority='simulation_endpoint_only' if 'claims' in r else 'none',
                          mutationPathsGuarded=GUARDS.copy(), clearedExternalMutations=r['cleared'])
            if 'token' in r:
                result.update(tokenId=r['token']['token_id'], validUntil=r['token']['valid_until'],
                              candidateDigest=r['candidate']['candidateDigest'], binding=copy.deepcopy(r['candidate']['binding']),
                              endpointId=self._review.endpointId, modelDigest=REFERENCE_MODEL,
                              payloadHash=r['token']['constraints']['payload_hash'], tokenVerification='rust_signature_and_constraints')
            return result

    def capture(self, request_id):
        with self._lock:
            r = self._records[request_id]
            if r['state'] in {'checking', 'admitted', 'starting', 'running'}: raise PermissionError('capture is not terminal')
            payload = dict(schemaVersion='seedcore.cw-g01.capture.v1', summary=self.status(request_id), samples=copy.deepcopy(r['samples']),
                           scope='local_simulation_only', physicalAcceptance=False, signed=False,
                           sourceDigest=self._source_sha, executorDigest=self._executor_digest, timestepSeconds=DT)
            return dict(**payload, captureDigest=hashed(payload))

    def evidence_bundle(self, request_id) -> bytes:
        """Seal a terminal attempt once. Export cannot advance or reopen a run."""
        from .cw_evidence import seal_bundle
        with self._lock:
            r = self._records[request_id]
            if self._receipt_signer is None:
                raise PermissionError('no host simulation receipt signer configured')
            if r['state'] not in {'completed', 'stopped', 'fenced'} or not r.get('samples') or 'evidence_context' not in r:
                raise PermissionError('nonempty terminal admitted capture required')
            if 'evidence_bundle' not in r:
                artifacts = dict(source=self._source_bytes,
                    token=canonical_assembly_bytes(r['token']), candidate=canonical_assembly_bytes(r['candidate']),
                    parameters=canonical_assembly_bytes(r['case'].action_intent.action.parameters),
                    review=canonical_assembly_bytes(r['review'].model_dump(mode='json')),
                    executor=canonical_assembly_bytes(self._executor), capture=canonical_assembly_bytes(self.capture(request_id)))
                manifest = dict(schemaVersion='seedcore.cw-g02.receipt.v1', profile=NATIVE_PROFILE,
                    scope='local_simulation_only', physicalAcceptance=False, executionAuthority='none',
                    context=copy.deepcopy(r['evidence_context']), startedAt=r['startedAt'], endedAt=r['endedAt'],
                    stepCheckedAt=list(r['step_checks']), terminalState=r['state'], reason=r['reason'],
                    executedSubsteps=r['tick'], totalSubsteps=120)
                # Failure is visible to the caller and never changes execution state.
                r['evidence_bundle'] = seal_bundle(artifacts, manifest, self._receipt_signer)
            return r['evidence_bundle']

    def close(self):
        self._shutdown.set()
        with self._lock:
            self._closed = True
            for r in self._records.values(): self._fence(r, 'service_shutdown', 'stopped')
        for thread in self._threads: thread.join(timeout=1)
