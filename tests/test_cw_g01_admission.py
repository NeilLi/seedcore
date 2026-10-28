"""Candidate/preparation coverage, not live admission or physical execution acceptance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from seedcore.models.action_intent import PolicyCase
from seedcore.robotics.assembly import canonical_assembly_bytes
from seedcore.robotics.component_registry import sha256
from seedcore.robotics.build_admission import (
    BuildBinding, ReviewedSimulationBuild, read_build_candidate, prepare_cw_policy_case,
)

NOW = datetime(2026, 10, 28, 6, tzinfo=timezone.utc)


def rehash(value):
    value['candidateDigest'] = sha256(canonical_assembly_bytes({k: v for k, v in value.items() if k != 'candidateDigest'}))
    return value


@pytest.fixture
def candidate():
    source = os.getenv('SEEDCORE_CW_G01_CANDIDATE')
    if source:
        return read_build_candidate(Path(source).read_bytes()).model_dump(mode='json')
    # Independent schema fixture; these pins are not an approved runtime/profile.
    return rehash(dict(
        schemaVersion='seedcore.cw-g01.candidate.v1', scope='offline_simulation_only', physicalAcceptance=False,
        executionAuthority='none', endpointId='cw_sim://fixture/1',
        binding=dict(revisionDigest='1'*64, assemblyDigest='2'*64, catalogDigest='3'*64,
                     drcDigest='4'*64, modelDigest='5'*64, authorityEpoch=1),
        runtime=dict(profile='seedcore.cw-s02.mujoco-wasm-st.v1', engineVersion='3.15.0',
                     wasmSha256='d59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d',
                     timestepSeconds=0.002, actuatorMode='position', positionKp=1),
        behavior=dict(compiler='seedcore.cw-s04.hermite.v1', gestureDigest='6'*64, totalTicks=120, durationSeconds=0.24,
                      joints=[dict(jointId=f'joint_{i}', lowerRad=0, upperRad=0.001, maxVelocityRadS=0.0125,
                                   maxAccelerationRadS2=5/12, requestedMaxVelocityRadS=0.1,
                                   requestedMaxAccelerationRadS2=10) for i in range(2)])))


@pytest.fixture
def context(candidate):
    limits = [dict(jointId=j['jointId'], lowerRad=-1, upperRad=1, maxVelocityRadS=0.08, maxAccelerationRadS2=8)
              for j in candidate['behavior']['joints']]
    review = ReviewedSimulationBuild.model_validate_json(json.dumps(dict(
        reviewId='review:synthetic-test', candidateDigest=candidate['candidateDigest'], endpointId=candidate['endpointId'],
        assetId='asset:synthetic-test', sourceRegistrationId='registration:synthetic-test', registrationDecisionId='decision:synthetic-test',
        resourceStateHash='sha256:'+'7'*64, policySnapshot='snapshot:cw-g01-test', securityContractHash='sha256:'+'8'*64,
        scope='offline_simulation_only', reviewedAt=(NOW-timedelta(minutes=1)).isoformat(),
        validUntil=(NOW+timedelta(minutes=1)).isoformat(), revoked=False,
        endpointMaxDurationSeconds=0.24, operatorMaxDurationSeconds=0.24, endpointLimits=limits, operatorLimits=limits)))
    case = PolicyCase.model_validate(dict(
        action_intent=dict(intent_id='intent:cw-g01-test', timestamp=NOW.isoformat(), valid_until=(NOW+timedelta(seconds=3)).isoformat(),
            principal=dict(agent_id='agent-test', role_profile='ROBOT_OPERATOR', session_token='authenticated-test-session'),
            action=dict(type='MOVE', security_contract=dict(hash=review.securityContractHash, version=review.policySnapshot),
                        parameters=dict(endpoint_id=candidate['endpointId'], approval_context={'review_ref': review.reviewId})),
            resource=dict(asset_id=review.assetId, source_registration_id=review.sourceRegistrationId,
                          registration_decision_id=review.registrationDecisionId, resource_state_hash=review.resourceStateHash,
                          provenance_hash='sha256:'+candidate['binding']['assemblyDigest'])),
        policy_snapshot=review.policySnapshot, approved_source_registrations={review.sourceRegistrationId: review.registrationDecisionId},
        relevant_twin_snapshot={'owner': dict(twin_kind='owner', twin_id='owner:test',
            freshness=dict(status='fresh', observed_at=NOW.isoformat()), delegation=dict(delegations=[dict(
                assistant_id='agent-test', authority_level='signer', scope=[review.assetId], requires_step_up=False)]))},
        authoritative_approval_envelope={'review_ref': review.reviewId},
        authoritative_approval_transition_history=[{'test_marker': 'original'}], authoritative_approval_transition_head='sha256:'+'9'*64,
        telemetry_summary={'test_marker': 'original'}, evidence_summary={'test_marker': 'original'}))
    return dict(review=review, current_binding=BuildBinding.model_validate(candidate['binding']), policy_case=case, now=NOW)


def test_deterministic_preparation_binds_entire_payload_and_preserves_trusted_context(candidate, context):
    original = context['policy_case'].model_dump(mode='json')
    prepared = prepare_cw_policy_case(candidate, **context)
    again = prepare_cw_policy_case(json.dumps(candidate), **context)
    assert prepared == again
    assert context['policy_case'].model_dump(mode='json') == original
    params = prepared.action_intent.action.parameters
    payload_hash = params.pop('payload_hash')
    assert payload_hash == 'sha256:'+sha256(canonical_assembly_bytes(params))
    assert params['requires_approved_source_registration'] is True
    payload = params['cw_build']
    assert payload['physicalAcceptance'] is False and payload['executionAuthority'] == 'none'
    assert payload['candidate'] == candidate
    assert payload['maxDurationSeconds'] == 0.24
    for joint in payload['intersectedLimits']:
        assert joint['maxVelocityRadS'] == 0.08 and joint['maxAccelerationRadS2'] == 8
    for field in ('relevant_twin_snapshot', 'approved_source_registrations', 'authoritative_approval_envelope',
                  'authoritative_approval_transition_history', 'authoritative_approval_transition_head', 'telemetry_summary', 'evidence_summary'):
        assert getattr(prepared, field) == getattr(context['policy_case'], field)
    assert prepared.action_intent.principal == context['policy_case'].action_intent.principal
    prepared.relevant_twin_snapshot['owner'].delegation.clear()
    assert context['policy_case'].relevant_twin_snapshot['owner'].delegation


@pytest.mark.parametrize('key', ['revisionDigest', 'assemblyDigest', 'catalogDigest', 'drcDigest', 'modelDigest', 'authorityEpoch'])
def test_every_current_binding_is_required(candidate, context, key):
    changed = context['current_binding'].model_dump(mode='json')
    changed[key] = 2 if key == 'authorityEpoch' else 'f'*64
    context['current_binding'] = BuildBinding.model_validate(changed)
    with pytest.raises(ValueError, match='current binding'):
        prepare_cw_policy_case(candidate, **context)


@pytest.mark.parametrize('change', ['pin', 'endpoint', 'no_review', 'revoked', 'expired', 'future', 'physical', 'timezone'])
def test_review_cannot_be_created_or_replaced_by_browser(candidate, context, change):
    review = context['review'].model_dump(mode='json')
    if change == 'no_review':
        context['review'] = None
    else:
        if change == 'pin': review['candidateDigest'] = 'f'*64
        elif change == 'endpoint': review['endpointId'] = 'cw_sim://other/1'
        elif change == 'revoked': review['revoked'] = True
        elif change == 'expired': review['validUntil'] = NOW.isoformat()
        elif change == 'future': review['reviewedAt'] = (NOW+timedelta(seconds=1)).isoformat()
        elif change == 'physical': review['scope'] = 'hardware'
        elif change == 'timezone': review['reviewedAt'] = '2026-10-28T06:00:00'
        if change == 'physical':
            with pytest.raises(ValueError): ReviewedSimulationBuild.model_validate_json(json.dumps(review))
            return
        context['review'] = ReviewedSimulationBuild.model_validate_json(json.dumps(review))
    with pytest.raises(ValueError): prepare_cw_policy_case(candidate, **context)


@pytest.mark.parametrize('field', ['lowerRad', 'upperRad', 'maxVelocityRadS', 'maxAccelerationRadS2', 'duration', 'inventory', 'duplicate'])
def test_intersection_is_per_joint_and_never_clamps_curve(candidate, context, field):
    review = context['review'].model_dump(mode='json')
    joint = review['operatorLimits'][0]
    curve = candidate['behavior']['joints'][0]
    if field == 'lowerRad': joint[field] = curve['lowerRad']+0.0001
    elif field == 'upperRad': joint[field] = curve['upperRad']-0.0001
    elif field in {'maxVelocityRadS', 'maxAccelerationRadS2'}: joint[field] = curve[field]/2
    elif field == 'duration': review['operatorMaxDurationSeconds'] = 0.2
    elif field == 'inventory': joint['jointId'] = 'unknown_joint'
    elif field == 'duplicate': review['operatorLimits'][1] = deepcopy(joint)
    context['review'] = ReviewedSimulationBuild.model_validate_json(json.dumps(review))
    with pytest.raises(ValueError): prepare_cw_policy_case(candidate, **context)


def test_limits_intersect_each_joint_independently(candidate, context):
    review = context['review'].model_dump(mode='json')
    review['endpointLimits'][0]['maxVelocityRadS'] = 0.02
    review['operatorLimits'][1]['maxVelocityRadS'] = 0.07
    review['operatorLimits'].reverse()  # Names, not array order, bind limits.
    context['review'] = ReviewedSimulationBuild.model_validate_json(json.dumps(review))
    limits = prepare_cw_policy_case(candidate, **context).action_intent.action.parameters['cw_build']['intersectedLimits']
    assert [j['maxVelocityRadS'] for j in limits] == [0.02, 0.07]


@pytest.mark.parametrize('change', ['asset', 'registration', 'decision', 'state', 'provenance', 'policy', 'contract', 'endpoint',
                                    'no_owner', 'empty_delegations', 'expired', 'future', 'overlong', 'prebound', 'plan'])
def test_trusted_template_must_match_review_and_remain_bounded(candidate, context, change):
    case = context['policy_case']; intent = case.action_intent
    if change == 'asset': intent.resource.asset_id = 'asset:other'
    elif change == 'registration': intent.resource.source_registration_id = 'registration:other'
    elif change == 'decision': intent.resource.registration_decision_id = 'decision:other'
    elif change == 'state': intent.resource.resource_state_hash = 'sha256:'+'a'*64
    elif change == 'provenance': intent.resource.provenance_hash = 'sha256:'+'a'*64
    elif change == 'policy': case.policy_snapshot = 'snapshot:other'
    elif change == 'contract': intent.action.security_contract.hash = 'sha256:'+'a'*64
    elif change == 'endpoint': intent.action.parameters['endpoint_id'] = 'cw_sim://other/1'
    elif change == 'no_owner': case.relevant_twin_snapshot.clear()
    elif change == 'empty_delegations': case.relevant_twin_snapshot['owner'].delegation['delegations'] = []
    elif change == 'expired': context['now'] += timedelta(seconds=4)
    elif change == 'future': context['now'] -= timedelta(seconds=1)
    elif change == 'overlong': intent.valid_until = (NOW+timedelta(seconds=6)).isoformat()
    elif change == 'prebound': intent.action.parameters['payload_hash'] = 'sha256:'+'a'*64
    elif change == 'plan': intent.action.parameters['plan_dag_hash'] = 'sha256:'+'a'*64
    with pytest.raises(ValueError): prepare_cw_policy_case(candidate, **context)


@pytest.mark.parametrize('change', ['missing_registration', 'mismatched_registration', 'observer', 'wrong_scope', 'revoked', 'stale'])
def test_existing_pdp_denials_survive_preparation(candidate, context, change, monkeypatch):
    from seedcore.coordinator.core import governance
    case = context['policy_case']; owner = case.relevant_twin_snapshot['owner']
    expected = 'owner_scope_violation'
    if change == 'missing_registration': case.approved_source_registrations.clear(); expected = 'unapproved_source_registration'
    elif change == 'mismatched_registration': case.approved_source_registrations[context['review'].sourceRegistrationId] = 'other'; expected = 'mismatched_registration_decision'
    elif change == 'observer': owner.delegation['delegations'][0]['authority_level'] = 'observer'; expected = 'owner_observer_restricted'
    elif change == 'wrong_scope': owner.delegation['delegations'][0]['scope'] = ['asset:other']
    elif change == 'revoked': owner.delegation['revoked'] = True; expected = 'revoked_delegation'
    elif change == 'stale': owner.freshness.status = 'stale'; expected = 'stale_twin_state'
    monkeypatch.setattr(governance, '_utcnow', lambda: NOW)
    monkeypatch.setattr(governance, '_mint_execution_token', lambda **_: pytest.fail('Denied input reached token minting'))
    decision = governance.evaluate_intent(prepare_cw_policy_case(candidate, **context))
    assert decision.allowed is False and decision.execution_token is None
    assert decision.deny_code == expected


@pytest.mark.parametrize('change', ['unknown', 'physical', 'authority', 'endpoint', 'profile', 'bool_kp', 'duration', 'digest', 'duplicate_joint'])
def test_closed_candidate_schema_even_after_rehashing(candidate, change):
    if change == 'unknown': candidate['signature'] = 'browser-self-signature'
    elif change == 'physical': candidate['physicalAcceptance'] = True
    elif change == 'authority': candidate['executionAuthority'] = 'motor'
    elif change == 'endpoint': candidate['endpointId'] = 'hal://robot/1'
    elif change == 'profile': candidate['runtime']['wasmSha256'] = '0'*64
    elif change == 'bool_kp': candidate['runtime']['positionKp'] = True
    elif change == 'duration': candidate['behavior']['durationSeconds'] = 0.2
    elif change == 'digest': candidate['binding']['modelDigest'] = '0'*64
    elif change == 'duplicate_joint': candidate['behavior']['joints'][1] = deepcopy(candidate['behavior']['joints'][0])
    if change != 'digest': rehash(candidate)
    with pytest.raises(ValueError): read_build_candidate(candidate)


def test_raw_import_is_size_duplicate_and_number_bounded(candidate):
    raw = json.dumps(candidate)
    assert read_build_candidate(raw).candidateDigest == candidate['candidateDigest']
    with pytest.raises(ValueError): read_build_candidate(raw.replace('"schemaVersion":', '"schemaVersion":0,"schemaVersion":'))
    with pytest.raises(ValueError): read_build_candidate(' '*16385)
    candidate['binding']['authorityEpoch'] = 2**53
    with pytest.raises(ValueError): read_build_candidate(candidate)
    candidate['binding']['authorityEpoch'] = float('nan')
    with pytest.raises(ValueError): read_build_candidate(candidate)


def test_actual_browser_export_parses_if_required():
    source = os.getenv('SEEDCORE_CW_G01_BROWSER_CANDIDATE')
    if not source:
        pytest.skip('actual browser candidate lane not requested')
    raw = Path(source).read_bytes()
    parsed = read_build_candidate(raw)
    assert canonical_assembly_bytes(parsed.model_dump(mode='json'))+b'\n' == raw
    assert parsed.endpointId == 'cw_sim://fixture/1'
