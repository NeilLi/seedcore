from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from seedcore.models.pdp_hot_path import (
    HotPathEvaluateRequest,
    HotPathEvaluateResponse,
    HotPathContextFreshness,
    HotPathSignedContextEnvelope,
    HotPathAssetContext,
    HotPathTelemetryContext,
    HotPathDecisionView,
    HotPathCheckResult,
    HotPathSignerProvenance,
)
from seedcore.models.action_intent import ActionIntent, ExecutionToken
from seedcore.ops.pdp_hot_path_pb2 import (
    HotPathEvaluateRequestProto,
    HotPathEvaluateResponseProto,
)


def _to_iso(dt: Any) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _from_iso(val: str) -> datetime | None:
    if not val:
        return None
    try:
        parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def serialize_request_to_protobuf(request: HotPathEvaluateRequest) -> bytes:
    proto = HotPathEvaluateRequestProto()
    proto.contract_version = request.contract_version or ""
    proto.request_id = request.request_id or ""
    proto.requested_at = _to_iso(request.requested_at)
    proto.policy_snapshot_ref = request.policy_snapshot_ref or ""

    if request.context_freshness:
        proto.context_freshness.local_view_ref = request.context_freshness.local_view_ref or ""
        proto.context_freshness.minimum_observed_at = request.context_freshness.minimum_observed_at or ""
        proto.context_freshness.causality_token = request.context_freshness.causality_token or ""

    if request.action_intent:
        proto.action_intent_json = request.action_intent.model_dump_json()

    for env in request.signed_context_envelopes:
        e_proto = proto.signed_context_envelopes.add()
        e_proto.envelope_id = env.envelope_id or ""
        e_proto.issuer = env.issuer or ""
        e_proto.issued_at = env.issued_at or ""
        e_proto.claims_hash = env.claims_hash or ""
        e_proto.signature_ref = env.signature_ref or ""
        for caveat in env.caveats:
            e_proto.caveats.append(caveat)

    if request.asset_context:
        proto.asset_context.asset_ref = request.asset_context.asset_ref or ""
        proto.asset_context.current_custodian_ref = request.asset_context.current_custodian_ref or ""
        proto.asset_context.current_zone = request.asset_context.current_zone or ""
        proto.asset_context.source_registration_status = request.asset_context.source_registration_status or ""
        proto.asset_context.registration_decision_ref = request.asset_context.registration_decision_ref or ""

    if request.telemetry_context:
        proto.telemetry_context.observed_at = request.telemetry_context.observed_at or ""
        proto.telemetry_context.current_zone = request.telemetry_context.current_zone or ""
        proto.telemetry_context.current_coordinate_ref = request.telemetry_context.current_coordinate_ref or ""
        if request.telemetry_context.freshness_seconds is not None:
            proto.telemetry_context.freshness_seconds = int(request.telemetry_context.freshness_seconds)
            proto.telemetry_context.has_freshness_seconds = True
        if request.telemetry_context.max_allowed_age_seconds is not None:
            proto.telemetry_context.max_allowed_age_seconds = int(request.telemetry_context.max_allowed_age_seconds)
            proto.telemetry_context.has_max_allowed_age_seconds = True
        for ref in request.telemetry_context.evidence_refs:
            proto.telemetry_context.evidence_refs.append(ref)

    if request.request_schema_bundle is not None:
        proto.request_schema_bundle_json = json.dumps(request.request_schema_bundle)
    if request.taxonomy_bundle is not None:
        proto.taxonomy_bundle_json = json.dumps(request.taxonomy_bundle)

    return proto.SerializeToString()


def deserialize_request_from_protobuf(data: bytes) -> HotPathEvaluateRequest:
    proto = HotPathEvaluateRequestProto()
    proto.ParseFromString(data)

    context_freshness = None
    if proto.HasField("context_freshness"):
        context_freshness = HotPathContextFreshness(
            local_view_ref=proto.context_freshness.local_view_ref or None,
            minimum_observed_at=proto.context_freshness.minimum_observed_at or None,
            causality_token=proto.context_freshness.causality_token or None,
        )

    action_intent = None
    if proto.action_intent_json:
        action_intent = ActionIntent.model_validate_json(proto.action_intent_json)

    signed_context_envelopes = []
    for env in proto.signed_context_envelopes:
        signed_context_envelopes.append(
            HotPathSignedContextEnvelope(
                envelope_id=env.envelope_id,
                issuer=env.issuer,
                issued_at=env.issued_at,
                claims_hash=env.claims_hash,
                signature_ref=env.signature_ref,
                caveats=list(env.caveats),
            )
        )

    asset_context = HotPathAssetContext(
        asset_ref=proto.asset_context.asset_ref,
        current_custodian_ref=proto.asset_context.current_custodian_ref or None,
        current_zone=proto.asset_context.current_zone or None,
        source_registration_status=proto.asset_context.source_registration_status or None,
        registration_decision_ref=proto.asset_context.registration_decision_ref or None,
    )

    freshness_seconds = None
    if proto.telemetry_context.has_freshness_seconds:
        freshness_seconds = proto.telemetry_context.freshness_seconds

    max_allowed_age_seconds = None
    if proto.telemetry_context.has_max_allowed_age_seconds:
        max_allowed_age_seconds = proto.telemetry_context.max_allowed_age_seconds

    telemetry_context = HotPathTelemetryContext(
        observed_at=proto.telemetry_context.observed_at,
        freshness_seconds=freshness_seconds,
        max_allowed_age_seconds=max_allowed_age_seconds,
        current_zone=proto.telemetry_context.current_zone or None,
        current_coordinate_ref=proto.telemetry_context.current_coordinate_ref or None,
        evidence_refs=list(proto.telemetry_context.evidence_refs),
    )

    request_schema_bundle = None
    if proto.request_schema_bundle_json:
        request_schema_bundle = json.loads(proto.request_schema_bundle_json)

    taxonomy_bundle = None
    if proto.taxonomy_bundle_json:
        taxonomy_bundle = json.loads(proto.taxonomy_bundle_json)

    requested_at = _from_iso(proto.requested_at) or datetime.now(timezone.utc)

    return HotPathEvaluateRequest(
        contract_version=proto.contract_version,
        request_id=proto.request_id,
        requested_at=requested_at,
        policy_snapshot_ref=proto.policy_snapshot_ref,
        context_freshness=context_freshness,
        action_intent=action_intent,
        signed_context_envelopes=signed_context_envelopes,
        asset_context=asset_context,
        telemetry_context=telemetry_context,
        request_schema_bundle=request_schema_bundle,
        taxonomy_bundle=taxonomy_bundle,
    )


def serialize_response_to_protobuf(response: HotPathEvaluateResponse) -> bytes:
    proto = HotPathEvaluateResponseProto()
    proto.contract_version = response.contract_version or ""
    proto.request_id = response.request_id or ""
    proto.decided_at = _to_iso(response.decided_at)
    proto.latency_ms = int(response.latency_ms or 0)

    if response.decision:
        proto.decision.allowed = response.decision.allowed
        proto.decision.disposition = response.decision.disposition or ""
        proto.decision.reason_code = response.decision.reason_code or ""
        proto.decision.reason = response.decision.reason or ""
        proto.decision.policy_snapshot_ref = response.decision.policy_snapshot_ref or ""
        proto.decision.policy_snapshot_hash = response.decision.policy_snapshot_hash or ""

        if response.decision.trust_alert:
            proto.decision.trust_alert = str(response.decision.trust_alert)

    for val in response.required_approvals:
        proto.required_approvals.append(val)
    for val in response.trust_gaps:
        proto.trust_gaps.append(val)

    if response.obligations:
        proto.obligations_json = json.dumps(response.obligations)

    for chk in response.checks:
        c_proto = proto.checks.add()
        c_proto.check_id = chk.check_id or ""
        c_proto.result = chk.result or ""
        c_proto.detail = chk.detail or ""

    if response.execution_token:
        proto.execution_token_json = response.execution_token.model_dump_json()
    if response.execution_preconditions is not None:
        proto.execution_preconditions_json = json.dumps(response.execution_preconditions)
    if response.governed_receipt is not None:
        proto.governed_receipt_json = json.dumps(response.governed_receipt)

    for prov in response.signer_provenance:
        p_proto = proto.signer_provenance.add()
        p_proto.artifact_type = prov.artifact_type or ""
        p_proto.signer_type = prov.signer_type or ""
        p_proto.signer_id = prov.signer_id or ""
        p_proto.key_ref = prov.key_ref or ""
        p_proto.attestation_level = prov.attestation_level or ""

    if response.request_schema_bundle is not None:
        proto.request_schema_bundle_json = json.dumps(response.request_schema_bundle)
    if response.taxonomy_bundle is not None:
        proto.taxonomy_bundle_json = json.dumps(response.taxonomy_bundle)

    return proto.SerializeToString()


def deserialize_response_from_protobuf(data: bytes) -> HotPathEvaluateResponse:
    proto = HotPathEvaluateResponseProto()
    proto.ParseFromString(data)

    trust_alert = proto.decision.trust_alert or None

    decision = HotPathDecisionView(
        allowed=proto.decision.allowed,
        disposition=proto.decision.disposition,
        reason_code=proto.decision.reason_code,
        reason=proto.decision.reason,
        policy_snapshot_ref=proto.decision.policy_snapshot_ref,
        policy_snapshot_hash=proto.decision.policy_snapshot_hash or None,
        trust_alert=trust_alert,
    )

    obligations = []
    if proto.obligations_json:
        obligations = json.loads(proto.obligations_json)

    checks = []
    for chk in proto.checks:
        checks.append(
            HotPathCheckResult(
                check_id=chk.check_id,
                result=chk.result,
                detail=chk.detail or None,
            )
        )

    execution_token = None
    if proto.execution_token_json:
        execution_token = ExecutionToken.model_validate_json(proto.execution_token_json)

    execution_preconditions = None
    if proto.execution_preconditions_json:
        execution_preconditions = json.loads(proto.execution_preconditions_json)

    governed_receipt = {}
    if proto.governed_receipt_json:
        governed_receipt = json.loads(proto.governed_receipt_json)

    signer_provenance = []
    for prov in proto.signer_provenance:
        signer_provenance.append(
            HotPathSignerProvenance(
                artifact_type=prov.artifact_type,
                signer_type=prov.signer_type,
                signer_id=prov.signer_id,
                key_ref=prov.key_ref,
                attestation_level=prov.attestation_level,
            )
        )

    request_schema_bundle = None
    if proto.request_schema_bundle_json:
        request_schema_bundle = json.loads(proto.request_schema_bundle_json)

    taxonomy_bundle = None
    if proto.taxonomy_bundle_json:
        taxonomy_bundle = json.loads(proto.taxonomy_bundle_json)

    decided_at = _from_iso(proto.decided_at) or datetime.now(timezone.utc)

    return HotPathEvaluateResponse(
        contract_version=proto.contract_version,
        request_id=proto.request_id,
        decided_at=decided_at,
        latency_ms=proto.latency_ms,
        decision=decision,
        required_approvals=list(proto.required_approvals),
        trust_gaps=list(proto.trust_gaps),
        obligations=obligations,
        checks=checks,
        execution_token=execution_token,
        execution_preconditions=execution_preconditions,
        governed_receipt=governed_receipt,
        signer_provenance=signer_provenance,
        request_schema_bundle=request_schema_bundle,
        taxonomy_bundle=taxonomy_bundle,
    )
