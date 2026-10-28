"""CW-G01 review-candidate intake and existing PolicyCase preparation.

No token issuer, claim store, executor, HTTP route or hardware profile lives here.
``review``, ``current_binding`` and ``policy_case`` must come from the trusted
service's review/registration/authentication context, never from browser JSON.
The result still requires the existing PDP and execution-boundary checks.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seedcore.models.action_intent import PolicyCase
from .assembly import canonical_assembly_bytes
from .component_registry import parse_json, sha256

MAX_CANDIDATE_BYTES = 16384
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")]
Endpoint = Annotated[str, Field(pattern=r"^cw_sim://[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")]
Finite = Annotated[float, Field(allow_inf_nan=False, ge=-1000, le=1000)]
Positive = Annotated[float, Field(allow_inf_nan=False, gt=0, le=1000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BuildBinding(Contract):
    revisionDigest: Digest
    assemblyDigest: Digest
    catalogDigest: Digest
    drcDigest: Digest
    modelDigest: Digest
    authorityEpoch: int = Field(ge=0, le=2**53-1)


class RuntimeProfile(Contract):
    profile: Literal["seedcore.cw-s02.mujoco-wasm-st.v1"]
    engineVersion: Literal["3.15.0"]
    wasmSha256: Literal["d59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d"]
    timestepSeconds: Literal[0.002]
    actuatorMode: Literal["position"]
    positionKp: Literal[1]

    @field_validator('positionKp', 'timestepSeconds', mode='before')
    @classmethod
    def numeric_profile(cls, value):
        if type(value) not in (int, float):
            raise ValueError('numeric runtime settings required')
        return value


class CurveBounds(Contract):
    jointId: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")]
    lowerRad: Annotated[float, Field(allow_inf_nan=False, ge=-10, le=10)]
    upperRad: Annotated[float, Field(allow_inf_nan=False, ge=-10, le=10)]
    maxVelocityRadS: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    maxAccelerationRadS2: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)]
    requestedMaxVelocityRadS: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
    requestedMaxAccelerationRadS2: Positive

    @model_validator(mode="after")
    def bounds(self):
        if (self.lowerRad > self.upperRad or self.maxVelocityRadS > self.requestedMaxVelocityRadS
                or self.maxAccelerationRadS2 > self.requestedMaxAccelerationRadS2):
            raise ValueError("inconsistent requested/full-curve bounds")
        return self


class Behavior(Contract):
    compiler: Literal["seedcore.cw-s04.hermite.v1"]
    gestureDigest: Digest
    totalTicks: int = Field(ge=1, le=120)
    durationSeconds: Positive
    joints: tuple[CurveBounds, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def bounded(self):
        if self.durationSeconds != self.totalTicks * 0.002 or len({j.jointId for j in self.joints}) != len(self.joints):
            raise ValueError("duration or joint inventory mismatch")
        return self


class BuildCandidate(Contract):
    schemaVersion: Literal["seedcore.cw-g01.candidate.v1"]
    scope: Literal["offline_simulation_only"]
    physicalAcceptance: bool
    executionAuthority: Literal["none"]
    endpointId: Endpoint
    binding: BuildBinding
    runtime: RuntimeProfile
    behavior: Behavior
    candidateDigest: Digest

    @model_validator(mode="after")
    def digest_and_scope(self):
        if self.physicalAcceptance is not False or any(p in {".", ".."} for p in self.endpointId.split('/')):
            raise ValueError("unsupported candidate scope/endpoint")
        payload = self.model_dump(mode="json", exclude={"candidateDigest"})
        if sha256(canonical_assembly_bytes(payload)) != self.candidateDigest:
            raise ValueError("candidate digest mismatch")
        return self


def read_build_candidate(raw: bytes | str | dict) -> BuildCandidate:
    """Closed, duplicate-key-safe JSON with the same canonical bytes as Studio."""
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if isinstance(data, bytes):
        if not 0 < len(data) <= MAX_CANDIDATE_BYTES:
            raise ValueError("candidate exceeds 16 KiB")
        data = parse_json(data)
    data = canonical_assembly_bytes(data)
    if len(data) > MAX_CANDIDATE_BYTES:
        raise ValueError("candidate exceeds 16 KiB")
    return BuildCandidate.model_validate_json(data)


class JointLimits(Contract):
    jointId: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")]
    lowerRad: Finite
    upperRad: Finite
    maxVelocityRadS: Positive
    maxAccelerationRadS2: Positive

    @model_validator(mode="after")
    def nonempty(self):
        if self.lowerRad >= self.upperRad:
            raise ValueError("empty joint envelope")
        return self


class ReviewedSimulationBuild(Contract):
    """Trusted service input: a separately reviewed candidate pin, not enrollment.

    This record is not a signed hardware profile. No helper auto-approves a
    browser candidate. Review must independently check original compiler inputs.
    """
    reviewId: Name
    candidateDigest: Digest
    endpointId: Endpoint
    assetId: Name
    sourceRegistrationId: Name
    registrationDecisionId: Name
    resourceStateHash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    policySnapshot: Name
    securityContractHash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    scope: Literal["offline_simulation_only"]
    reviewedAt: str
    validUntil: str
    revoked: bool
    endpointMaxDurationSeconds: Positive
    operatorMaxDurationSeconds: Positive
    endpointLimits: tuple[JointLimits, ...] = Field(min_length=1, max_length=3)
    operatorLimits: tuple[JointLimits, ...] = Field(min_length=1, max_length=3)


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("explicit timezone required")
    return result


def prepare_cw_policy_case(raw: bytes | str | dict, *, review: ReviewedSimulationBuild | None,
                           current_binding: BuildBinding, policy_case: PolicyCase, now: datetime) -> PolicyCase:
    """Bind trusted context and intersect limits before handing off to the PDP.

    No policy allow is implied. Preserve approval/delegation/telemetry context;
    the caller must use the existing PDP, token verification, durable claim,
    revocation and per-substep enforcement before any execution.
    """
    candidate = read_build_candidate(raw)
    # Revalidate even model_construct/model_copy inputs; none is an authority marker.
    if review is None:
        raise ValueError("separate trusted review/endpoint registration required")
    review = ReviewedSimulationBuild.model_validate_json(review.model_dump_json())
    current_binding = BuildBinding.model_validate_json(current_binding.model_dump_json())
    case = PolicyCase.model_validate(policy_case.model_dump(mode="json"))
    intent = case.action_intent
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("explicit current timezone required")
    if (review.revoked or not _time(review.reviewedAt) <= now < _time(review.validUntil)
            or review.candidateDigest != candidate.candidateDigest or review.endpointId != candidate.endpointId
            or current_binding != candidate.binding):
        raise ValueError("stale/revoked review, changed build/gesture/endpoint or current binding")
    if (intent.action.type != 'MOVE' or intent.resource.asset_id != review.assetId
            or intent.resource.source_registration_id != review.sourceRegistrationId
            or intent.resource.registration_decision_id != review.registrationDecisionId
            or intent.resource.resource_state_hash != review.resourceStateHash
            or intent.resource.provenance_hash != f'sha256:{candidate.binding.assemblyDigest}'
            or intent.action.security_contract.hash != review.securityContractHash
            or intent.action.security_contract.version != review.policySnapshot or case.policy_snapshot != review.policySnapshot
            or intent.action.parameters.get('endpoint_id') != candidate.endpointId):
        raise ValueError("trusted asset/registration/state/policy/endpoint context mismatch")
    owner = case.relevant_twin_snapshot.get('owner')
    if owner is None or not isinstance(owner.delegation.get('delegations'), list) or not owner.delegation['delegations']:
        raise ValueError("current owner delegation context required for the existing PDP")
    issued, expires = _time(intent.timestamp), _time(intent.valid_until)
    if not issued <= now < expires or (expires-issued).total_seconds() > 5 or expires > _time(review.validUntil):
        raise ValueError("intent must be current and bounded by the review and five-second preparation window")
    if any(k in intent.action.parameters for k in ('payload_hash', 'plan_dag_hash', 'cw_build')):
        raise ValueError("template already contains an execution payload/plan binding")
    joints = {j.jointId for j in candidate.behavior.joints}
    endpoints = {j.jointId: j for j in review.endpointLimits}
    operators = {j.jointId: j for j in review.operatorLimits}
    if (set(endpoints) != joints or set(operators) != joints or len(endpoints) != len(review.endpointLimits)
            or len(operators) != len(review.operatorLimits)):
        raise ValueError("reviewed per-joint inventories must match exactly")
    duration = min(review.endpointMaxDurationSeconds, review.operatorMaxDurationSeconds)
    if candidate.behavior.durationSeconds > duration:
        raise ValueError("gesture exceeds reviewed duration; no time stretching or clipping")
    intersected = []
    for requested in candidate.behavior.joints:
        endpoint, operator = endpoints[requested.jointId], operators[requested.jointId]
        low, high = max(endpoint.lowerRad, operator.lowerRad), min(endpoint.upperRad, operator.upperRad)
        velocity = min(endpoint.maxVelocityRadS, operator.maxVelocityRadS, requested.requestedMaxVelocityRadS)
        acceleration = min(endpoint.maxAccelerationRadS2, operator.maxAccelerationRadS2, requested.requestedMaxAccelerationRadS2)
        if (low > high or requested.lowerRad < low or requested.upperRad > high
                or requested.maxVelocityRadS > velocity or requested.maxAccelerationRadS2 > acceleration):
            raise ValueError(f"full curve exceeds intersected limits for {requested.jointId}; no silent clamping")
        intersected.append(dict(jointId=requested.jointId, lowerRad=low, upperRad=high,
                                maxVelocityRadS=velocity, maxAccelerationRadS2=acceleration))
    payload = dict(schemaVersion='seedcore.cw-g01.prepared.v1', scope='offline_simulation_only', physicalAcceptance=False,
                   executionAuthority='none', candidate=candidate.model_dump(mode='json'),
                   reviewDigest=sha256(canonical_assembly_bytes(review.model_dump(mode='json'))),
                   maxDurationSeconds=duration, intersectedLimits=intersected)
    intent.action.parameters.update(cw_build=payload, requires_approved_source_registration=True)
    # Bind the entire parameters map, including any existing trusted approval context.
    intent.action.parameters['payload_hash'] = 'sha256:' + sha256(canonical_assembly_bytes(intent.action.parameters))
    return case
