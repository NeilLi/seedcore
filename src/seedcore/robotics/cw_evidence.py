"""CW-G02 offline host-signed simulation evidence. This module cannot execute.

Trust and expected admission context are caller inputs, never adopted from an
imported bundle. Original JSON artifacts are carried as base64 bytes. Signatures
use the existing signed-artifact envelope over an RFC 8785 SHA-256 manifest.
"""
from __future__ import annotations

import base64
import copy
from datetime import timedelta
import json
import math
import re
from pathlib import Path
from typing import Annotated, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import Field

from .assembly import canonical_assembly_bytes
from .build_admission import BuildBinding, Contract, Digest, Endpoint, Name, ReviewedSimulationBuild, read_build_candidate
from .component_registry import parse_json, sha256
from .fast_spine.authority import CLAIM_KEYS, CONSTRAINT_KEYS, PRECONDITION_KEYS, utc

MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 262144
ARTIFACTS = {'token', 'candidate', 'source', 'parameters', 'review', 'executor', 'capture'}
PROFILE = 'seedcore.cw-g01.native-admission.v1'
MODEL = '2478a5c6f22e4d46f9f0c130ea2505b16394d699564ffb3007658fa26300fab5'
SCOPE = 'local_simulation_only'
SIGNATURE_FIELDS = {'signer_type', 'signer_id', 'signing_scheme', 'key_ref', 'attestation_level', 'signature'}
GUARDS = ['ctrl', 'qfrc_applied', 'xfrc_applied', 'qpos_qvel_act_state', 'opt_timestep', 'policy_model_switch']


def _timestamp(value):
    """Frozen CW clock domain: RFC 3339 with at most microsecond precision."""
    pattern = (r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]'
               r'(?:\.[0-9]{1,6})?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])')
    _require(isinstance(value, str) and re.fullmatch(pattern, value) is not None, 'invalid CW timestamp/precision')
    return utc(value.replace('t', 'T').replace('z', 'Z'))


def _base64(value):
    decoded = base64.b64decode(value, validate=True)
    _require(base64.b64encode(decoded).decode('ascii') == value, 'noncanonical base64 encoding')
    return decoded


def digest(value):
    return sha256(canonical_assembly_bytes(value))


def _same(left, right):
    # JSON numbers may share a canonical spelling; booleans must never alias 0/1.
    return canonical_assembly_bytes(left) == canonical_assembly_bytes(right)


def json_bytes(value):
    """Stable outer serialization; artifact and manifest hashing remain RFC 8785."""
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode() + b'\n'
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError('evidence bundle exceeds 2 MiB')
    return data


def read_json_file(path: Path, limit=MAX_BUNDLE_BYTES):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('empty or oversized evidence input')
    return raw


class ExpectedContext(Contract):
    schemaVersion: Literal['seedcore.cw-g02.expected.v1']
    requestId: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')]
    instanceId: Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')]
    endpointId: Endpoint
    admittedAt: str
    candidateDigest: Digest
    binding: BuildBinding
    sourceDigest: Digest
    executorDigest: Digest
    reviewDigest: Digest
    tokenDigest: Digest
    payloadHash: Annotated[str, Field(pattern=r'^sha256:[a-f0-9]{64}$')]
    tokenKeyRef: Name
    receiptKeyRef: Name


class ReceiptManifest(Contract):
    schemaVersion: Literal['seedcore.cw-g02.receipt.v1']
    profile: Literal['seedcore.cw-g01.native-admission.v1']
    scope: Literal['local_simulation_only']
    physicalAcceptance: Literal[False]
    executionAuthority: Literal['none']
    context: ExpectedContext
    startedAt: str
    endedAt: str
    stepCheckedAt: list[str] = Field(min_length=1, max_length=120)
    terminalState: Literal['completed', 'stopped', 'fenced']
    reason: str | None
    executedSubsteps: int = Field(ge=1, le=120)
    totalSubsteps: Literal[120]
    artifactDigests: dict[str, Digest]


class CwReceiptSigner:
    """Explicit, separate-purpose host signer; no key creation or fallback."""

    def __init__(self, key: Ed25519PrivateKey, key_ref: str):
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError('explicit Ed25519 receipt signer required')
        # Validate with the same bounded key-reference domain as the contract.
        if not isinstance(key_ref, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,128}', key_ref):
            raise ValueError('invalid receipt key reference')
        self._key, self.key_ref = key, key_ref

    def seal(self, payload):
        payload = ReceiptManifest.model_validate(payload).model_dump(mode='json')
        hashed = digest(payload)
        return dict(artifact=payload, artifact_hash=dict(algorithm='sha256', value=hashed), signature=dict(
            signer_type='service', signer_id=self.key_ref, signing_scheme='ed25519', key_ref=self.key_ref,
            attestation_level='baseline', signature=base64.b64encode(self._key.sign(hashed.encode('ascii'))).decode('ascii')))

    def trust_entry(self, endpoint_id):
        """Public provisioning material; callers must establish trust separately."""
        return dict(key_ref=self.key_ref, key_algorithm='ed25519', public_key=base64.b64encode(
            self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode('ascii'),
            trust_anchor_type='host_simulation', endpoint_id=endpoint_id)


def seal_bundle(artifacts: dict[str, bytes], manifest: dict, signer: CwReceiptSigner) -> bytes:
    if set(artifacts) != ARTIFACTS:
        raise ValueError('exact original-artifact inventory required')
    for raw in artifacts.values():
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ARTIFACT_BYTES:
            raise ValueError('bounded original artifact bytes required')
        canonical_assembly_bytes(parse_json(raw))
    payload = copy.deepcopy(manifest)
    payload['artifactDigests'] = {name: sha256(raw) for name, raw in artifacts.items()}
    return json_bytes(dict(schemaVersion='seedcore.cw-g02.bundle.v1', receipt=signer.seal(payload),
                           artifacts={name: base64.b64encode(raw).decode('ascii') for name, raw in artifacts.items()}))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _signature(payload, artifact_hash, signature, trust, *, key_ref, anchor, endpoint):
    _require(set(signature) == SIGNATURE_FIELDS, 'signature envelope mismatch')
    _require((signature['signer_type'], signature['signer_id'], signature['signing_scheme'],
              signature['key_ref'], signature['attestation_level']) ==
             ('service', key_ref, 'ed25519', key_ref, 'baseline'), 'signer identity/scheme mismatch')
    _require(key_ref not in trust['revoked_keys'], 'revoked signer key')
    entry = trust['trusted_keys'][key_ref]
    _require(set(entry) == {'key_ref', 'key_algorithm', 'public_key', 'trust_anchor_type', 'endpoint_id'} and
             (entry['key_ref'], entry['key_algorithm'], entry['trust_anchor_type'], entry['endpoint_id']) ==
             (key_ref, 'ed25519', anchor, endpoint), 'trust purpose/endpoint mismatch')
    hashed = digest(payload)
    _require(artifact_hash == dict(algorithm='sha256', value=hashed), 'signed artifact hash mismatch')
    key = Ed25519PublicKey.from_public_bytes(_base64(entry['public_key']))
    key.verify(_base64(signature['signature']), hashed.encode('ascii'))


def _vector(value, count):
    _require(isinstance(value, list) and len(value) == count and all(
        type(v) in (int, float) and math.isfinite(v) for v in value), 'invalid/nonfinite sample vector')


def _check_artifacts(a, m, context, trust):
    token, candidate, source, params, review, executor, capture = (a[name] for name in
        ('token', 'candidate', 'source', 'parameters', 'review', 'executor', 'capture'))
    c = read_build_candidate(candidate)
    _require(c.candidateDigest == context['candidateDigest'] and candidate['binding'] == context['binding']
             and c.endpointId == context['endpointId'] and c.binding.modelDigest == MODEL and c.behavior.totalTicks == 120,
             'candidate/epoch/model binding mismatch')
    _require(digest(token) == context['tokenDigest'] and digest(review) == context['reviewDigest']
             and digest(executor) == context['executorDigest'], 'token/review/executor binding mismatch')
    r = ReviewedSimulationBuild.model_validate_json(json.dumps(review))
    _require(r.candidateDigest == c.candidateDigest and r.endpointId == c.endpointId and r.revoked is False
             and r.resourceStateHash == 'sha256:' + digest(dict(sourceDigest=context['sourceDigest'], executorDigest=context['executorDigest'])),
             'review/source/executor binding mismatch')
    _require(all(type(executor[field]) in (int, float) for field in (
        'timestepSeconds', 'maxTicks', 'maxSubstepsPerBatch', 'maxStallMs', 'maxWallDurationSeconds')),
        'numeric executor clock settings required')
    _require(executor['profile'] == PROFILE and executor['engineVersion'] == '3.15.0'
             and executor['timestepSeconds'] == .002 and executor['maxTicks'] == 120
             and executor['maxSubstepsPerBatch'] == 8 and executor['maxStallMs'] == 250
             and executor['maxWallDurationSeconds'] == 1, 'unsupported executor/clock profile')
    _require(set(token) == set(CLAIM_KEYS) | {'artifact_hash', 'signature'}
             and set(token['constraints']) == set(CONSTRAINT_KEYS)
             and set(token['execution_preconditions']) == set(PRECONDITION_KEYS), 'frozen token shape mismatch')
    claims = {key: token[key] for key in CLAIM_KEYS}
    _signature(claims, token['artifact_hash'], token['signature'], trust, key_ref=context['tokenKeyRef'],
               anchor='service', endpoint=c.endpointId)
    constraints, pre = token['constraints'], token['execution_preconditions']
    _require(token['intent_id'] == context['requestId'] and constraints['action_type'] == 'MOVE'
             and constraints['endpoint_id'] == pre['endpoint_id'] == c.endpointId
             and constraints['asset_id'] == r.assetId and constraints['source_registration_id'] == r.sourceRegistrationId
             and constraints['registration_decision_id'] == r.registrationDecisionId
             and pre['resource_state_hash'] == r.resourceStateHash and token['contract_version'] == r.policySnapshot,
             'token action/review binding mismatch')
    _require(params['payload_hash'] == constraints['payload_hash'] == pre['payload_hash'] == context['payloadHash']
             == 'sha256:' + digest({k: v for k, v in params.items() if k != 'payload_hash'}), 'execution payload hash mismatch')
    build = params['cw_build']
    _require(_same(build['candidate'], candidate) and build['reviewDigest'] == context['reviewDigest']
             and _same(build['executor'], executor) and build['scope'] == 'offline_simulation_only'
             and build['physicalAcceptance'] is False and build['executionAuthority'] == 'none',
             'execution payload/candidate mismatch')

    issued, expires = _timestamp(token['issued_at']), _timestamp(token['valid_until'])
    admitted, started, ended = (_timestamp(value) for value in (context['admittedAt'], m['startedAt'], m['endedAt']))
    _require(issued <= admitted <= started < expires and timedelta(0) < expires-issued <= timedelta(seconds=5)
             and _timestamp(r.reviewedAt) <= admitted <= started < _timestamp(r.validUntil) and ended >= started,
             'invalid admission/execution time window')
    previous = started
    _require(len(m['stepCheckedAt']) == m['executedSubsteps'], 'missing step authority coverage')
    for index, checked in enumerate(m['stepCheckedAt']):
        at = _timestamp(checked)
        _require(previous <= at <= ended and at < min(expires, _timestamp(r.validUntil), started+timedelta(seconds=1)),
                 'step outside authority window/clock rollback')
        _require((at-started).total_seconds() >= (index+1)*.002-1e-6, 'capture runs ahead of admitted clock')
        previous = at

    _require(set(source) == {'schemaVersion', 'scope', 'physicalAcceptance', 'executionAuthority', 'candidate', 'model', 'gesture', 'frames'}
             and source['schemaVersion'] == 'seedcore.cw-g01.endpoint-source.v1' and source['scope'] == 'offline_simulation_only'
             and source['physicalAcceptance'] is False and source['executionAuthority'] == 'none'
             and source['model']['modelDigest'] == MODEL and len(source['frames']) == 120, 'unsupported endpoint source')
    _require(digest({k: v for k, v in source['model'].items() if k != 'modelDigest'}) == MODEL,
             'compiled source model digest mismatch')
    _require(set(capture) == {'schemaVersion', 'summary', 'samples', 'scope', 'physicalAcceptance', 'signed',
                             'sourceDigest', 'executorDigest', 'timestepSeconds', 'captureDigest'}
             and capture['schemaVersion'] == 'seedcore.cw-g01.capture.v1' and capture['scope'] == SCOPE
             and capture['physicalAcceptance'] is False and capture['signed'] is False
             and capture['timestepSeconds'] == .002 and capture['sourceDigest'] == context['sourceDigest']
             and capture['executorDigest'] == context['executorDigest']
             and capture['captureDigest'] == digest({k: v for k, v in capture.items() if k != 'captureDigest'}),
             'capture scope/integrity mismatch')
    summary = capture['summary']
    BuildBinding.model_validate(summary['binding'])
    _require(set(summary) == {'id', 'state', 'reason', 'executedSubsteps', 'totalSubsteps', 'profile', 'scope',
                             'physicalAcceptance', 'executionAuthority', 'mutationPathsGuarded', 'clearedExternalMutations',
                             'tokenId', 'validUntil', 'candidateDigest', 'binding', 'endpointId', 'modelDigest',
                             'payloadHash', 'tokenVerification'} and summary['id'] == context['requestId']
             and summary['candidateDigest'] == c.candidateDigest
             and summary['binding'] == candidate['binding'] and summary['endpointId'] == c.endpointId
             and summary['modelDigest'] == MODEL and summary['tokenId'] == token['token_id']
             and summary['payloadHash'] == context['payloadHash'] and summary['validUntil'] == token['valid_until']
             and summary['profile'] == PROFILE and summary['scope'] == SCOPE and summary['physicalAcceptance'] is False
             and summary['executionAuthority'] == 'simulation_endpoint_only'
             and summary['tokenVerification'] == 'rust_signature_and_constraints' and summary['mutationPathsGuarded'] == GUARDS
             and type(summary['clearedExternalMutations']) is int and summary['clearedExternalMutations'] >= 0
             and summary['state'] == m['terminalState'] and summary['reason'] == m['reason']
             and type(summary['executedSubsteps']) is int and summary['executedSubsteps'] == m['executedSubsteps']
             and type(summary['totalSubsteps']) is int and summary['totalSubsteps'] == 120, 'capture/receipt summary mismatch')
    _require((m['terminalState'] == 'completed' and m['reason'] is None and m['executedSubsteps'] == 120)
             or (m['terminalState'] == 'stopped' and m['reason'] in {'operator_stop', 'service_shutdown'}
                 and m['executedSubsteps'] < 120), 'unsupported/conflicting terminal outcome')
    if m['terminalState'] == 'completed':
        _require(ended < min(expires, _timestamp(r.validUntil), started+timedelta(seconds=1)),
                 'completion outside authority window')
    samples = capture['samples']
    _require(isinstance(samples, list) and len(samples) == m['executedSubsteps'], 'capture coverage mismatch')
    bodies = source['model']['manifest']['bodies']
    _require(len(source['model']['manifest']['joints']) == 2, 'unsupported joint inventory')
    for i, sample in enumerate(samples):
        _require(set(sample) == {'tick', 'simTimeSeconds', 'qpos', 'qvel', 'ctrl', 'qfrcActuator', 'xpos', 'bodies', 'virtualLed'}
                 and type(sample['tick']) is int and sample['tick'] == i+1
                 and type(sample['simTimeSeconds']) in (int, float)
                 and abs(sample['simTimeSeconds']-(i+1)*.002) <= 1e-12, 'sample gap/order/clock mismatch')
        for name in ('qpos', 'qvel', 'ctrl', 'qfrcActuator'):
            _vector(sample[name], 2)
        limits = build['intersectedLimits']
        _require(len(limits) == 2 and all(lim['lowerRad'] <= q <= lim['upperRad'] for lim, q in
                                        zip(limits, sample['qpos'], strict=True)), 'observed state outside admitted bounds')
        _vector(sample['xpos'], 3*(len(bodies)+1))
        frame = source['frames'][i]
        _require(type(frame['tick']) is int and frame['tick'] == i+1 and _same(sample['ctrl'], frame['targetRad'])
                 and sample['virtualLed'] == frame['virtualLed'], 'sample control/cue mismatch')
        _require(len(sample['bodies']) == len(bodies), 'sample body inventory mismatch')
        for observed, body in zip(sample['bodies'], bodies, strict=True):
            _require(set(observed) == {'nodeId', 'position_m', 'quaternion_wxyz'}
                     and observed['nodeId'] == body['nodeId'], 'sample body identity mismatch')
            _vector(observed['position_m'], 3)
            _vector(observed['quaternion_wxyz'], 4)
            _require(abs(sum(q*q for q in observed['quaternion_wxyz'])-1) < 1e-9, 'invalid pose quaternion')


def verify_bundle(raw: bytes, *, expected: dict, trust: dict) -> dict:
    """Offline verification only; no current-time expiry check on historical runs."""
    report = dict(schemaVersion='seedcore.cw-g02.verification.v1', verified=False, disposition='quarantine',
                  scope=SCOPE, physicalAcceptance=False, executionAuthority='none', bundleSha256=sha256(raw),
                  expectedContextDigest=None, trustSnapshotDigest=None, sourceRefs={}, error=None)
    try:
        _require(0 < len(raw) <= MAX_BUNDLE_BYTES, 'empty or oversized evidence bundle')
        context = ExpectedContext.model_validate(expected).model_dump(mode='json')
        report['expectedContextDigest'] = digest(context)
        report['trustSnapshotDigest'] = digest(trust)
        _require(set(trust) == {'version', 'trusted_keys', 'revoked_keys'}
                 and trust['version'] == 'seedcore.cw-g02.simulation-trust.v1'
                 and isinstance(trust['trusted_keys'], dict) and isinstance(trust['revoked_keys'], list)
                 and all(isinstance(k, str) for k in trust['revoked_keys']), 'invalid trust snapshot')
        bundle = parse_json(raw)
        _require(set(bundle) == {'schemaVersion', 'receipt', 'artifacts'}
                 and bundle['schemaVersion'] == 'seedcore.cw-g02.bundle.v1', 'bundle schema mismatch')
        receipt = bundle['receipt']
        _require(set(receipt) == {'artifact', 'artifact_hash', 'signature'}, 'receipt envelope mismatch')
        manifest = ReceiptManifest.model_validate(receipt['artifact']).model_dump(mode='json')
        _require(receipt['artifact']['physicalAcceptance'] is False, 'invalid physical acceptance claim')
        _require(manifest['context'] == context, 'independently expected admission context mismatch')
        _signature(receipt['artifact'], receipt['artifact_hash'], receipt['signature'], trust,
                   key_ref=context['receiptKeyRef'], anchor='host_simulation', endpoint=context['endpointId'])
        _require(set(bundle['artifacts']) == set(manifest['artifactDigests']) == ARTIFACTS,
                 'missing/extra original artifacts')
        artifacts = {}
        for name, encoded in bundle['artifacts'].items():
            _require(isinstance(encoded, str) and len(encoded) <= 4*((MAX_ARTIFACT_BYTES+2)//3), 'oversized artifact encoding')
            data = _base64(encoded)
            _require(0 < len(data) <= MAX_ARTIFACT_BYTES and sha256(data) == manifest['artifactDigests'][name],
                     'original artifact hash mismatch: '+name)
            artifacts[name] = parse_json(data)
            canonical_assembly_bytes(artifacts[name])
        report['sourceRefs'] = copy.deepcopy(manifest['artifactDigests'])
        _require(manifest['artifactDigests']['source'] == context['sourceDigest'], 'original source hash mismatch')
        _check_artifacts(artifacts, manifest, context, trust)
        report.update(verified=True, disposition='verified_completed' if manifest['terminalState'] == 'completed'
                      else 'verified_interrupted')
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {str(error)[:500]}'
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Verify a CW host-signed simulation bundle offline; no execution authority.')
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected', required=True, type=Path, help='Previously saved admission context from a trusted channel')
    parser.add_argument('--trust', required=True, type=Path, help='Independently provisioned trusted/revoked key snapshot')
    args = parser.parse_args(argv)
    try:
        report = verify_bundle(read_json_file(args.bundle), expected=parse_json(read_json_file(args.expected, 32768)),
                               trust=parse_json(read_json_file(args.trust, 32768)))
    except Exception as error:
        report = dict(verified=False, disposition='quarantine', scope=SCOPE, physicalAcceptance=False,
                      executionAuthority='none', error=f'{type(error).__name__}: {str(error)[:500]}')
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
