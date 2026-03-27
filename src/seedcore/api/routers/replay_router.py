from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_async_pg_session, get_async_redis_client
from ...models.replay import ReplayProjectionKind, TrustCertificate, TrustPageProjection, VerificationResult
from ...services.replay_service import ReplayService, ReplayServiceError


router = APIRouter()
replay_service = ReplayService()


class TrustPublishRequest(BaseModel):
    task_id: Optional[str] = None
    intent_id: Optional[str] = None
    audit_id: Optional[str] = None
    ttl_hours: Optional[int] = None


class TrustRevokeRequest(BaseModel):
    public_id: str


class VerifyRequest(BaseModel):
    reference_id: Optional[str] = None
    public_id: Optional[str] = None
    audit_id: Optional[str] = None
    subject_id: Optional[str] = None
    subject_type: Optional[str] = None


class TrustBundlePublishRequest(BaseModel):
    task_id: Optional[str] = None
    intent_id: Optional[str] = None
    audit_id: Optional[str] = None
    bundle_version: Optional[str] = None
    promote_current: bool = True
    revoked_keys: List[str] = Field(default_factory=list)
    revoked_nodes: List[str] = Field(default_factory=list)
    revocation_cutoffs: Dict[str, Any] = Field(default_factory=dict)


def _raise_http_from_service_error(exc: ReplayServiceError) -> None:
    if exc.code in {"invalid_lookup", "invalid_audit_id", "invalid_public_id", "invalid_verification_request"}:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if exc.code in {"record_not_found"}:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if exc.code in {"ambiguous_task_id"}:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if exc.code in {"missing_evidence_bundle"}:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if exc.code in {"redis_unavailable"}:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if exc.code in {"invalid_signature"}:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _public_urls(request: Request, public_id: str) -> Dict[str, str]:
    base = _base_url(request)
    return {
        "trust_url": f"{base}/api/v1/trust/{public_id}",
        "verify_url": f"{base}/api/v1/verify/{public_id}",
        "jsonld_url": f"{base}/api/v1/trust/{public_id}/jsonld",
        "certificate_url": f"{base}/api/v1/trust/{public_id}/certificate",
    }


async def _resolve_public_reference_or_http(public_id: str) -> tuple[Any, Any]:
    try:
        reference = replay_service.decode_public_reference(public_id)
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)
    if replay_service._parse_datetime(reference.expires_at) <= replay_service._utcnow():
        raise HTTPException(status_code=410, detail="Public trust reference has expired")
    redis_client = await get_async_redis_client()
    if await replay_service.reference_is_revoked(reference=reference, redis_client=redis_client):
        await _close_async_client(redis_client)
        raise HTTPException(status_code=410, detail="Public trust reference has been revoked")
    return reference, redis_client


async def _close_async_client(client: Any) -> None:
    if client is None:
        return
    for attr in ("aclose", "close"):
        closer = getattr(client, attr, None)
        if callable(closer):
            result = closer()
            if hasattr(result, "__await__"):
                await result
            return


@router.get("/replay")
async def get_replay(
    task_id: str | None = None,
    intent_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
    projection: ReplayProjectionKind = ReplayProjectionKind.INTERNAL,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    try:
        lookup_key, lookup_value, replay = await replay_service.assemble_replay_record(
            session,
            task_id=task_id,
            intent_id=intent_id,
            audit_id=audit_id,
            subject_id=subject_id,
            subject_type=subject_type,
        )
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)
    return {
        "lookup_key": lookup_key,
        "lookup_value": lookup_value,
        "projection": projection.value,
        "record": replay.model_dump(mode="json"),
        "view": replay_service.project_record(replay, projection),
    }


@router.get("/replay/timeline")
async def get_replay_timeline(
    task_id: str | None = None,
    intent_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    try:
        lookup_key, lookup_value, replay = await replay_service.assemble_replay_record(
            session,
            task_id=task_id,
            intent_id=intent_id,
            audit_id=audit_id,
            subject_id=subject_id,
            subject_type=subject_type,
        )
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)
    return {
        "lookup_key": lookup_key,
        "lookup_value": lookup_value,
        "replay_id": replay.replay_id,
        "subject_type": replay.subject_type,
        "subject_id": replay.subject_id,
        "verification_status": replay.verification_status.model_dump(mode="json"),
        "timeline": [item.model_dump(mode="json") for item in replay.replay_timeline],
    }


@router.get("/replay/artifacts")
async def get_replay_artifacts(
    task_id: str | None = None,
    intent_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
    projection: ReplayProjectionKind = ReplayProjectionKind.INTERNAL,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    try:
        lookup_key, lookup_value, replay = await replay_service.assemble_replay_record(
            session,
            task_id=task_id,
            intent_id=intent_id,
            audit_id=audit_id,
            subject_id=subject_id,
            subject_type=subject_type,
        )
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)

    if projection in {ReplayProjectionKind.PUBLIC, ReplayProjectionKind.BUYER}:
        view = replay_service.project_record(replay, projection)
        public_jsonld = replay_service.build_jsonld_export(replay, projection=projection)
        return {
            "lookup_key": lookup_key,
            "lookup_value": lookup_value,
            "projection": projection.value,
            "verification_status": replay.verification_status.model_dump(mode="json"),
            "public_artifacts": {
                "fingerprint_summary": view.get("fingerprint_summary"),
                "policy_summary": view.get("policy_summary"),
                "public_media_refs": view.get("public_media_refs"),
                "verifiable_claims": view.get("verifiable_claims"),
                "approval_transition_chain": (
                    public_jsonld.get("proof", {}).get("approval_transition_chain")
                    if isinstance(public_jsonld.get("proof"), dict)
                    else None
                ),
            },
        }

    internal_jsonld = replay_service.build_jsonld_export(replay, projection=ReplayProjectionKind.INTERNAL)
    return {
        "lookup_key": lookup_key,
        "lookup_value": lookup_value,
        "projection": projection.value,
        "verification_status": replay.verification_status.model_dump(mode="json"),
        "authz_graph": replay.authz_graph,
        "governed_receipt": replay.governed_receipt,
        "policy_receipt": replay.policy_receipt,
        "evidence_bundle": replay.evidence_bundle,
        "transition_receipts": replay.transition_receipts,
        "signer_chain": replay.signer_chain,
        "approval_transition_chain": (
            internal_jsonld.get("proof", {}).get("approval_transition_chain")
            if isinstance(internal_jsonld.get("proof"), dict)
            else None
        ),
    }


@router.get("/replay/jsonld")
async def get_replay_jsonld(
    task_id: str | None = None,
    intent_id: str | None = None,
    audit_id: str | None = None,
    subject_id: str | None = None,
    subject_type: str | None = None,
    projection: ReplayProjectionKind = ReplayProjectionKind.INTERNAL,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    try:
        _, _, replay = await replay_service.assemble_replay_record(
            session,
            task_id=task_id,
            intent_id=intent_id,
            audit_id=audit_id,
            subject_id=subject_id,
            subject_type=subject_type,
        )
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)
    return replay_service.build_jsonld_export(replay, projection=projection)


@router.post("/trust/publish")
async def publish_trust_reference(
    payload: TrustPublishRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    try:
        lookup_key, lookup_value, replay = await replay_service.assemble_replay_record(
            session,
            task_id=payload.task_id,
            intent_id=payload.intent_id,
            audit_id=payload.audit_id,
        )
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)

    reference, public_id = replay_service.build_public_reference(
        lookup_key=lookup_key,
        lookup_value=lookup_value,
        replay=replay,
        ttl_hours=payload.ttl_hours,
    )
    urls = _public_urls(request, public_id)
    return {
        "public_id": public_id,
        "trust_url": urls["trust_url"],
        "verify_url": urls["verify_url"],
        "jsonld_url": urls["jsonld_url"],
        "certificate_url": urls["certificate_url"],
        "issued_at": reference.issued_at,
        "expires_at": reference.expires_at,
        "subject_type": replay.subject_type,
        "subject_id": replay.subject_id,
    }


@router.post("/trust/refresh")
async def refresh_trust_reference(
    payload: TrustPublishRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    return await publish_trust_reference(payload=payload, request=request, session=session)


@router.post("/trust/revoke")
async def revoke_trust_reference(payload: TrustRevokeRequest) -> Dict[str, Any]:
    redis_client = await get_async_redis_client()
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Redis is required to revoke public trust references")
    try:
        result = await replay_service.revoke_reference(public_id=payload.public_id, redis_client=redis_client)
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)
    finally:
        await _close_async_client(redis_client)
    return result


@router.post("/trust/bundles/publish")
async def publish_trust_bundle(
    payload: TrustBundlePublishRequest,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    redis_client = await get_async_redis_client()
    try:
        return await replay_service.publish_trust_bundle(
            session,
            task_id=payload.task_id,
            intent_id=payload.intent_id,
            audit_id=payload.audit_id,
            bundle_version=payload.bundle_version,
            promote_current=payload.promote_current,
            revoked_keys=payload.revoked_keys,
            revoked_nodes=payload.revoked_nodes,
            revocation_cutoffs=payload.revocation_cutoffs,
            redis_client=redis_client,
        )
    except ReplayServiceError as exc:
        _raise_http_from_service_error(exc)
    finally:
        await _close_async_client(redis_client)


@router.post("/trust/bundles/rotate")
async def rotate_trust_bundle(
    payload: TrustBundlePublishRequest,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    return await publish_trust_bundle(payload=payload, session=session)


@router.get("/trust/bundles/current")
async def get_current_trust_bundle() -> Dict[str, Any]:
    redis_client = await get_async_redis_client()
    try:
        snapshot = await replay_service.get_published_trust_bundle(redis_client=redis_client)
    finally:
        await _close_async_client(redis_client)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No trust bundle has been published")
    return snapshot


@router.get("/trust/bundles/{bundle_id}")
async def get_trust_bundle_by_id(bundle_id: str) -> Dict[str, Any]:
    redis_client = await get_async_redis_client()
    try:
        snapshot = await replay_service.get_published_trust_bundle(bundle_id=bundle_id, redis_client=redis_client)
    finally:
        await _close_async_client(redis_client)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Trust bundle not found")
    return snapshot


@router.get("/trust/bundles/current/signed")
async def get_current_signed_trust_bundle() -> Dict[str, Any]:
    return await get_current_trust_bundle()


@router.get("/trust/bundles/{bundle_id}/signed")
async def get_signed_trust_bundle_by_id(bundle_id: str) -> Dict[str, Any]:
    return await get_trust_bundle_by_id(bundle_id=bundle_id)


@router.get("/trust/{public_id}", response_model=TrustPageProjection)
async def get_public_trust_projection(
    public_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session),
) -> TrustPageProjection:
    reference, redis_client = await _resolve_public_reference_or_http(public_id)
    try:
        _, _, replay = await replay_service.assemble_replay_record(session, audit_id=reference.audit_id)
    except ReplayServiceError as exc:
        await _close_async_client(redis_client)
        _raise_http_from_service_error(exc)
    await _close_async_client(redis_client)

    payload = replay_service.project_record(replay, ReplayProjectionKind.PUBLIC)
    urls = _public_urls(request, public_id)
    payload["trust_page_id"] = public_id
    payload["public_jsonld_ref"] = urls["jsonld_url"]
    payload["public_certificate_ref"] = urls["certificate_url"]
    return TrustPageProjection(**payload)


@router.get("/trust/{public_id}/jsonld")
async def get_public_trust_jsonld(
    public_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
) -> Dict[str, Any]:
    reference, redis_client = await _resolve_public_reference_or_http(public_id)
    try:
        _, _, replay = await replay_service.assemble_replay_record(session, audit_id=reference.audit_id)
    except ReplayServiceError as exc:
        await _close_async_client(redis_client)
        _raise_http_from_service_error(exc)
    await _close_async_client(redis_client)
    return replay_service.build_jsonld_export(
        replay,
        public_id=public_id,
        projection=ReplayProjectionKind.PUBLIC,
    )


@router.get("/trust/{public_id}/certificate", response_model=TrustCertificate)
async def get_public_trust_certificate(
    public_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
) -> TrustCertificate:
    reference, redis_client = await _resolve_public_reference_or_http(public_id)
    try:
        _, _, replay = await replay_service.assemble_replay_record(session, audit_id=reference.audit_id)
        certificate = await replay_service.build_trust_certificate(
            replay,
            public_id=public_id,
            expires_at=reference.expires_at,
        )
    except ReplayServiceError as exc:
        await _close_async_client(redis_client)
        _raise_http_from_service_error(exc)
    await _close_async_client(redis_client)
    return certificate


@router.get("/verify/{reference_id}", response_model=VerificationResult)
async def verify_reference(
    reference_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session),
) -> VerificationResult:
    redis_client = await get_async_redis_client()
    result = await replay_service.verify_reference(
        session,
        reference_id=reference_id,
        redis_client=redis_client,
    )
    await _close_async_client(redis_client)
    if result.reference_type == "trust_token":
        urls = _public_urls(request, reference_id)
        result = result.model_copy(
            update={
                "trust_url": urls["trust_url"],
                "public_jsonld_ref": urls["jsonld_url"],
            }
        )
    return result


@router.post("/verify", response_model=VerificationResult)
async def verify_reference_post(
    payload: VerifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session),
) -> VerificationResult:
    provided = [
        bool(payload.reference_id and payload.reference_id.strip()),
        bool(payload.public_id and payload.public_id.strip()),
        bool(payload.audit_id and payload.audit_id.strip()),
        bool(payload.subject_id and payload.subject_id.strip()),
    ]
    if sum(provided) != 1:
        raise HTTPException(status_code=422, detail="Provide exactly one of reference_id, public_id, audit_id, or subject_id")

    redis_client = await get_async_redis_client()
    try:
        result = await replay_service.verify_reference(
            session,
            reference_id=payload.reference_id,
            public_id=payload.public_id,
            audit_id=payload.audit_id,
            subject_id=payload.subject_id,
            subject_type=payload.subject_type,
            redis_client=redis_client,
        )
    except ReplayServiceError as exc:
        await _close_async_client(redis_client)
        _raise_http_from_service_error(exc)
    await _close_async_client(redis_client)

    trust_reference = payload.reference_id or payload.public_id
    if trust_reference:
        urls = _public_urls(request, trust_reference)
        result = result.model_copy(
            update={
                "trust_url": urls["trust_url"],
                "public_jsonld_ref": urls["jsonld_url"],
            }
        )
    return result
