"""Explicit synthetic service fixtures for tests only; never imported by normal startup."""
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from seedcore.models.action_intent import PolicyCase
from seedcore.robotics.build_admission import ReviewedSimulationBuild
from seedcore.robotics.component_registry import sha256
from seedcore.robotics.cw_simulation import CwSimulationService, native_executor_digest, hashed
from seedcore.robotics.cw_token_authority import CwTokenAuthority
from seedcore.robotics.fast_spine.store import ClaimStore


def test_context(source, now=None):
    now = now or datetime.now(timezone.utc)
    profile = json.loads(source); c = profile['candidate']
    limits = [dict(jointId=j['jointId'], lowerRad=-.1, upperRad=.1, maxVelocityRadS=.1, maxAccelerationRadS2=10)
              for j in c['behavior']['joints']]
    review = ReviewedSimulationBuild.model_validate_json(json.dumps(dict(
        reviewId='review:explicit-synthetic-test', candidateDigest=c['candidateDigest'], endpointId=c['endpointId'],
        assetId='asset:cw-test', sourceRegistrationId='registration:cw-test', registrationDecisionId='decision:cw-test',
        resourceStateHash='sha256:'+hashed(dict(sourceDigest=sha256(source),executorDigest=native_executor_digest())), policySnapshot='snapshot:cw-test', securityContractHash='sha256:'+'8'*64,
        scope='offline_simulation_only', reviewedAt=(now-timedelta(minutes=1)).isoformat(), validUntil=(now+timedelta(hours=1)).isoformat(),
        revoked=False, endpointMaxDurationSeconds=.24, operatorMaxDurationSeconds=.24, endpointLimits=limits, operatorLimits=limits)))
    case = PolicyCase.model_validate(dict(action_intent=dict(intent_id='test-template', timestamp=now.isoformat(),
        valid_until=(now+timedelta(seconds=5)).isoformat(), principal=dict(agent_id='cw-test-agent', role_profile='ROBOT_OPERATOR',
        session_token='explicit-synthetic-service-session'), action=dict(type='MOVE', security_contract=dict(hash=review.securityContractHash,
        version=review.policySnapshot), parameters=dict(endpoint_id=c['endpointId'])), resource=dict(asset_id=review.assetId,
        provenance_hash='sha256:'+c['binding']['assemblyDigest'], resource_state_hash=review.resourceStateHash,
        source_registration_id=review.sourceRegistrationId, registration_decision_id=review.registrationDecisionId)),
        policy_snapshot=review.policySnapshot, approved_source_registrations={review.sourceRegistrationId: review.registrationDecisionId},
        relevant_twin_snapshot={'owner':dict(twin_kind='owner', twin_id='owner:synthetic-test', freshness=dict(status='fresh', observed_at=now.isoformat()),
        delegation=dict(delegations=[dict(assistant_id='cw-test-agent', authority_level='signer', scope=[review.assetId], requires_step_up=False)]))}))
    return review, case


def make_test_service(source, directory, *, clock=None, wall_clock=None, threaded=False, case_change=None, receipt_signer=None):
    now = wall_clock() if wall_clock else datetime.now(timezone.utc)
    review, case = test_context(source, now)
    if case_change: case_change(case)
    key = Ed25519PrivateKey.generate(); store = ClaimStore(Path(directory)/'claims.sqlite')
    args = dict(clock=clock, wall_clock=wall_clock) if clock else {}
    service = CwSimulationService(source, source_sha256=sha256(source), review=review, policy_case=case,
        authority=CwTokenAuthority(key, 'cw-explicit-test-pdp'), store=store, threaded=threaded,
        executor_digest=native_executor_digest(), receipt_signer=receipt_signer, **args)
    return service, store, key
