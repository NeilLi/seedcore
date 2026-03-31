from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.database import get_async_redis_client
from seedcore.models.action_intent import (
    ActionIntent,
    DelegatedAuthority,
    DelegationConstraint,
    OwnerTwin,
    TwinFreshness,
    TwinRevisionStage,
    TwinSnapshot,
)
from seedcore.models.fact import Fact
from seedcore.models.evidence_bundle import SignerMetadata
from seedcore.ops.evidence.policy import (
    canonical_json,
    load_ed25519_public_key,
    sha256_hex,
    verify_payload_signature,
)


IDENTITY_NAMESPACE = "identity"
DID_PREDICATE = "did_document"
DELEGATION_PREDICATE_PREFIX = "delegation:"
CREATOR_PROFILE_PREDICATE = "creator_profile"
TRUST_PREFERENCES_PREDICATE = "trust_preferences"
DEFAULT_EXTERNAL_INTENT_MAX_SKEW_SECONDS = 300
DEFAULT_EXTERNAL_INTENT_NONCE_TTL_SECONDS = 300
_NONCE_CACHE: dict[str, float] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DIDVerificationMethod(BaseModel):
    signing_scheme: Literal["ed25519", "hmac_sha256"] = "ed25519"
    public_key: Optional[str] = None
    key_ref: Optional[str] = None


class DIDDocumentRecord(BaseModel):
    did: str
    controller: Optional[str] = None
    display_name: Optional[str] = None
    status: Literal["ACTIVE", "REVOKED"] = "ACTIVE"
    verification_method: DIDVerificationMethod = Field(default_factory=DIDVerificationMethod)
    service_endpoints: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: isoformat(utcnow()))


class DelegationRecord(BaseModel):
    delegation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    assistant_id: str
    authority_level: str = "observer"
    scope: list[str] = Field(default_factory=list)
    constraints: DelegationConstraint = Field(default_factory=DelegationConstraint)
    requires_step_up: bool = True
    status: Literal["ACTIVE", "REVOKED"] = "ACTIVE"
    revoked_reason: Optional[str] = None
    created_at: str = Field(default_factory=lambda: isoformat(utcnow()))
    updated_at: str = Field(default_factory=lambda: isoformat(utcnow()))


class DIDRegistrationRequest(BaseModel):
    did: str
    controller: Optional[str] = None
    display_name: Optional[str] = None
    signing_scheme: Literal["ed25519", "hmac_sha256"] = "ed25519"
    public_key: Optional[str] = None
    key_ref: Optional[str] = None
    service_endpoints: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ACTIVE", "REVOKED"] = "ACTIVE"


class DIDUpdateRequest(BaseModel):
    controller: Optional[str] = None
    display_name: Optional[str] = None
    signing_scheme: Optional[Literal["ed25519", "hmac_sha256"]] = None
    public_key: Optional[str] = None
    key_ref: Optional[str] = None
    service_endpoints: Optional[dict[str, str]] = None
    metadata: Optional[dict[str, Any]] = None
    status: Optional[Literal["ACTIVE", "REVOKED"]] = None


class DelegationGrantRequest(BaseModel):
    owner_id: str
    assistant_id: str
    authority_level: Literal["observer", "contributor", "signer"] = "observer"
    scope: list[str] = Field(default_factory=list)
    constraints: DelegationConstraint = Field(default_factory=DelegationConstraint)
    requires_step_up: bool = True


class DelegationRevokeRequest(BaseModel):
    reason: Optional[str] = None


class SignedIntentSubmissionRequest(BaseModel):
    owner_id: Optional[str] = None
    action_intent: ActionIntent
    signature: str
    signer_did: Optional[str] = None
    signing_scheme: Literal["ed25519", "hmac_sha256"] = "ed25519"
    key_ref: Optional[str] = None
    nonce: str
    signed_at: str


class CreatorProfileRecord(BaseModel):
    owner_id: str
    version: str = "v1"
    status: Literal["ACTIVE", "SUPERSEDED", "REVOKED"] = "ACTIVE"
    display_name: Optional[str] = None
    brand_handles: dict[str, str] = Field(default_factory=dict)
    commerce_prefs: dict[str, Any] = Field(default_factory=dict)
    publish_prefs: dict[str, Any] = Field(default_factory=dict)
    risk_profile: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: isoformat(utcnow()))
    updated_by: str = "identity_router"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreatorProfileUpsertRequest(BaseModel):
    owner_id: str
    version: str = "v1"
    status: Literal["ACTIVE", "SUPERSEDED", "REVOKED"] = "ACTIVE"
    display_name: Optional[str] = None
    brand_handles: dict[str, str] = Field(default_factory=dict)
    commerce_prefs: dict[str, Any] = Field(default_factory=dict)
    publish_prefs: dict[str, Any] = Field(default_factory=dict)
    risk_profile: dict[str, Any] = Field(default_factory=dict)
    updated_by: str = "identity_router"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrustPreferencesRecord(BaseModel):
    owner_id: str
    trust_version: str = "v1"
    status: Literal["ACTIVE", "SUPERSEDED", "REVOKED"] = "ACTIVE"
    max_risk_score: Optional[float] = None
    merchant_allowlist: list[str] = Field(default_factory=list)
    required_provenance_level: Optional[str] = None
    required_evidence_modalities: list[str] = Field(default_factory=list)
    high_value_step_up_threshold_usd: Optional[float] = None
    updated_at: str = Field(default_factory=lambda: isoformat(utcnow()))
    updated_by: str = "identity_router"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrustPreferencesUpsertRequest(BaseModel):
    owner_id: str
    trust_version: str = "v1"
    status: Literal["ACTIVE", "SUPERSEDED", "REVOKED"] = "ACTIVE"
    max_risk_score: Optional[float] = None
    merchant_allowlist: list[str] = Field(default_factory=list)
    required_provenance_level: Optional[str] = None
    required_evidence_modalities: list[str] = Field(default_factory=list)
    high_value_step_up_threshold_usd: Optional[float] = None
    updated_by: str = "identity_router"
    metadata: dict[str, Any] = Field(default_factory=dict)


async def upsert_did_document(session: AsyncSession, payload: DIDRegistrationRequest | DIDDocumentRecord) -> DIDDocumentRecord:
    record = payload if isinstance(payload, DIDDocumentRecord) else DIDDocumentRecord(
        did=payload.did,
        controller=payload.controller,
        display_name=payload.display_name,
        status=payload.status,
        verification_method=DIDVerificationMethod(
            signing_scheme=payload.signing_scheme,
            public_key=payload.public_key,
            key_ref=payload.key_ref,
        ),
        service_endpoints=payload.service_endpoints,
        metadata=payload.metadata,
    )
    fact = await _get_did_fact(session, record.did)
    if fact is None:
        fact = Fact(
            text=f"DID document for {record.did}",
            tags=["identity", "did"],
            meta_data={"record_type": "did_document"},
            namespace=IDENTITY_NAMESPACE,
            subject=record.did,
            predicate=DID_PREDICATE,
            object_data=record.model_dump(mode="json"),
            created_by="identity_router",
        )
        session.add(fact)
    else:
        fact.text = f"DID document for {record.did}"
        fact.tags = ["identity", "did"]
        fact.meta_data = {"record_type": "did_document"}
        fact.object_data = record.model_dump(mode="json")
    await session.commit()
    return record


async def patch_did_document(session: AsyncSession, did: str, patch: DIDUpdateRequest) -> DIDDocumentRecord | None:
    current = await get_did_document(session, did)
    if current is None:
        return None
    payload = current.model_dump(mode="json")
    update_data = patch.model_dump(exclude_unset=True)
    verification_method = payload.get("verification_method", {})
    if "signing_scheme" in update_data:
        verification_method["signing_scheme"] = update_data.pop("signing_scheme")
    if "public_key" in update_data:
        verification_method["public_key"] = update_data.pop("public_key")
    if "key_ref" in update_data:
        verification_method["key_ref"] = update_data.pop("key_ref")
    payload.update(update_data)
    payload["verification_method"] = verification_method
    payload["updated_at"] = isoformat(utcnow())
    return await upsert_did_document(session, DIDDocumentRecord(**payload))


async def get_did_document(session: AsyncSession, did: str) -> DIDDocumentRecord | None:
    fact = await _get_did_fact(session, did)
    if fact is None or not isinstance(fact.object_data, dict):
        return None
    try:
        return DIDDocumentRecord(**fact.object_data)
    except Exception:
        return None


async def grant_delegation(session: AsyncSession, request: DelegationGrantRequest) -> DelegationRecord:
    delegation = DelegationRecord(
        owner_id=request.owner_id,
        assistant_id=request.assistant_id,
        authority_level=request.authority_level,
        scope=request.scope,
        constraints=request.constraints,
        requires_step_up=request.requires_step_up,
    )
    fact = Fact(
        text=f"Delegation {delegation.delegation_id} from {delegation.owner_id} to {delegation.assistant_id}",
        tags=["identity", "delegation", "active"],
        meta_data={"record_type": "delegation"},
        namespace=IDENTITY_NAMESPACE,
        subject=delegation.owner_id,
        predicate=f"{DELEGATION_PREDICATE_PREFIX}{delegation.delegation_id}",
        object_data=delegation.model_dump(mode="json"),
        created_by="identity_router",
    )
    session.add(fact)
    await session.commit()
    return delegation


async def revoke_delegation(
    session: AsyncSession,
    delegation_id: str,
    reason: Optional[str] = None,
) -> DelegationRecord | None:
    fact = await _get_delegation_fact(session, delegation_id)
    if fact is None or not isinstance(fact.object_data, dict):
        return None
    payload = dict(fact.object_data)
    payload["status"] = "REVOKED"
    payload["revoked_reason"] = reason
    payload["updated_at"] = isoformat(utcnow())
    fact.object_data = payload
    fact.tags = ["identity", "delegation", "revoked"]
    await session.commit()
    return DelegationRecord(**payload)


async def get_delegation(session: AsyncSession, delegation_id: str) -> DelegationRecord | None:
    fact = await _get_delegation_fact(session, delegation_id)
    if fact is None or not isinstance(fact.object_data, dict):
        return None
    try:
        return DelegationRecord(**fact.object_data)
    except Exception:
        return None


async def build_owner_twin_snapshot(session: AsyncSession, owner_id: str) -> TwinSnapshot:
    did_document = await get_did_document(session, owner_id)
    delegations = await _list_owner_delegations(session, owner_id)
    creator_profile = await get_creator_profile(session, owner_id)
    trust_preferences = await get_trust_preferences(session, owner_id)
    owner_twin = OwnerTwin(
        owner_id=owner_id,
        public_key_fingerprint=(
            did_document.verification_method.key_ref
            if did_document is not None
            else None
        ),
        delegations=[
            DelegatedAuthority(
                assistant_id=item.assistant_id,
                authority_level=item.authority_level,
                scope=item.scope,
                constraints=item.constraints,
                requires_step_up=item.requires_step_up,
            )
            for item in delegations
            if item.status == "ACTIVE"
        ],
        state="ACTIVE" if did_document is None else did_document.status,
    )
    return TwinSnapshot(
        twin_kind="owner",
        twin_id=owner_id,
        revision_stage=TwinRevisionStage.AUTHORITATIVE,
        freshness=TwinFreshness(
            status="fresh",
            observed_at=isoformat(utcnow()),
            max_age_seconds=DEFAULT_EXTERNAL_INTENT_NONCE_TTL_SECONDS,
        ),
        identity={
            "did": owner_id,
            "display_name": did_document.display_name if did_document else None,
            "controller": did_document.controller if did_document else None,
        },
        delegation={
            "delegations": [item.model_dump(mode="json") for item in owner_twin.delegations],
            "revoked": owner_twin.state == "REVOKED",
        },
        governance={"source": "identity_facts"},
        risk={
            "max_risk_score": trust_preferences.max_risk_score
            if trust_preferences is not None
            else None,
        },
        provenance={
            "creator_profile_ref": (
                {
                    "owner_id": owner_id,
                    "version": creator_profile.version,
                    "updated_at": creator_profile.updated_at,
                }
                if creator_profile is not None
                else None
            ),
            "trust_preferences_ref": (
                {
                    "owner_id": owner_id,
                    "trust_version": trust_preferences.trust_version,
                    "updated_at": trust_preferences.updated_at,
                }
                if trust_preferences is not None
                else None
            ),
        },
        telemetry={
            "owner_context": {
                "creator_profile": (
                    creator_profile.model_dump(mode="json")
                    if creator_profile is not None
                    else None
                ),
                "trust_preferences": (
                    trust_preferences.model_dump(mode="json")
                    if trust_preferences is not None
                    else None
                ),
            }
        },
    )


async def upsert_creator_profile(
    session: AsyncSession,
    payload: CreatorProfileUpsertRequest | CreatorProfileRecord,
) -> CreatorProfileRecord:
    record = payload if isinstance(payload, CreatorProfileRecord) else CreatorProfileRecord(
        owner_id=payload.owner_id,
        version=payload.version,
        status=payload.status,
        display_name=payload.display_name,
        brand_handles=payload.brand_handles,
        commerce_prefs=payload.commerce_prefs,
        publish_prefs=payload.publish_prefs,
        risk_profile=payload.risk_profile,
        updated_by=payload.updated_by,
        metadata=payload.metadata,
    )
    fact = await _get_owner_fact(session, owner_id=record.owner_id, predicate=CREATOR_PROFILE_PREDICATE)
    if fact is None:
        fact = Fact(
            text=f"Creator profile for {record.owner_id}",
            tags=["identity", "creator_profile"],
            meta_data={"record_type": "creator_profile"},
            namespace=IDENTITY_NAMESPACE,
            subject=record.owner_id,
            predicate=CREATOR_PROFILE_PREDICATE,
            object_data=record.model_dump(mode="json"),
            created_by=record.updated_by,
        )
        session.add(fact)
    else:
        fact.text = f"Creator profile for {record.owner_id}"
        fact.tags = ["identity", "creator_profile"]
        fact.meta_data = {"record_type": "creator_profile"}
        fact.object_data = record.model_dump(mode="json")
        fact.created_by = record.updated_by
    await session.commit()
    return record


async def get_creator_profile(session: AsyncSession, owner_id: str) -> CreatorProfileRecord | None:
    fact = await _get_owner_fact(session, owner_id=owner_id, predicate=CREATOR_PROFILE_PREDICATE)
    if fact is None or not isinstance(fact.object_data, dict):
        return None
    try:
        return CreatorProfileRecord(**fact.object_data)
    except Exception:
        return None


async def upsert_trust_preferences(
    session: AsyncSession,
    payload: TrustPreferencesUpsertRequest | TrustPreferencesRecord,
) -> TrustPreferencesRecord:
    record = payload if isinstance(payload, TrustPreferencesRecord) else TrustPreferencesRecord(
        owner_id=payload.owner_id,
        trust_version=payload.trust_version,
        status=payload.status,
        max_risk_score=payload.max_risk_score,
        merchant_allowlist=payload.merchant_allowlist,
        required_provenance_level=payload.required_provenance_level,
        required_evidence_modalities=payload.required_evidence_modalities,
        high_value_step_up_threshold_usd=payload.high_value_step_up_threshold_usd,
        updated_by=payload.updated_by,
        metadata=payload.metadata,
    )
    fact = await _get_owner_fact(session, owner_id=record.owner_id, predicate=TRUST_PREFERENCES_PREDICATE)
    if fact is None:
        fact = Fact(
            text=f"Trust preferences for {record.owner_id}",
            tags=["identity", "trust_preferences"],
            meta_data={"record_type": "trust_preferences"},
            namespace=IDENTITY_NAMESPACE,
            subject=record.owner_id,
            predicate=TRUST_PREFERENCES_PREDICATE,
            object_data=record.model_dump(mode="json"),
            created_by=record.updated_by,
        )
        session.add(fact)
    else:
        fact.text = f"Trust preferences for {record.owner_id}"
        fact.tags = ["identity", "trust_preferences"]
        fact.meta_data = {"record_type": "trust_preferences"}
        fact.object_data = record.model_dump(mode="json")
        fact.created_by = record.updated_by
    await session.commit()
    return record


async def get_trust_preferences(session: AsyncSession, owner_id: str) -> TrustPreferencesRecord | None:
    fact = await _get_owner_fact(session, owner_id=owner_id, predicate=TRUST_PREFERENCES_PREDICATE)
    if fact is None or not isinstance(fact.object_data, dict):
        return None
    try:
        return TrustPreferencesRecord(**fact.object_data)
    except Exception:
        return None


def build_external_intent_signing_payload(action_intent: ActionIntent, *, nonce: str, signed_at: str) -> dict[str, Any]:
    return {
        "action_intent": action_intent.model_dump(mode="json"),
        "nonce": nonce,
        "signed_at": signed_at,
    }


async def verify_signed_intent_submission(
    session: AsyncSession,
    submission: SignedIntentSubmissionRequest,
) -> tuple[bool, Optional[str], Optional[DIDDocumentRecord]]:
    did = submission.signer_did or submission.action_intent.principal.agent_id
    if did != submission.action_intent.principal.agent_id:
        return False, "signer_mismatch", None

    document = await get_did_document(session, did)
    if document is None:
        return False, "did_not_registered", None
    if document.status != "ACTIVE":
        return False, "did_not_active", None

    method = document.verification_method
    if submission.key_ref and method.key_ref and submission.key_ref != method.key_ref:
        return False, "key_ref_mismatch", document
    if submission.signing_scheme != method.signing_scheme:
        return False, "signing_scheme_mismatch", document

    signed_at = _parse_timestamp(submission.signed_at)
    if signed_at is None:
        return False, "invalid_signed_at", document
    max_skew = int(
        os.getenv(
            "SEEDCORE_EXTERNAL_INTENT_MAX_SKEW_SECONDS",
            str(DEFAULT_EXTERNAL_INTENT_MAX_SKEW_SECONDS),
        )
    )
    now = utcnow()
    if abs((now - signed_at).total_seconds()) > max_skew:
        return False, "stale_signed_at", document

    nonce_error = await _record_nonce_once(
        signer_did=did,
        nonce=submission.nonce,
        ttl_seconds=int(
            os.getenv(
                "SEEDCORE_EXTERNAL_INTENT_NONCE_TTL_SECONDS",
                str(DEFAULT_EXTERNAL_INTENT_NONCE_TTL_SECONDS),
            )
        ),
    )
    if nonce_error is not None:
        return False, nonce_error, document

    payload = build_external_intent_signing_payload(
        submission.action_intent,
        nonce=submission.nonce,
        signed_at=submission.signed_at,
    )
    verification = verify_payload_signature(
        artifact_type="external_signed_intent",
        payload=payload,
        signer_metadata=SignerMetadata(
            signer_type="external_principal",
            signer_id=did,
            signing_scheme=submission.signing_scheme,
            key_ref=submission.key_ref or method.key_ref,
            attestation_level="baseline",
            node_id=did,
            config_profile="external_signed_intent_verified",
        ),
        signature=submission.signature,
        public_key_resolver=lambda _metadata: (
            load_ed25519_public_key(method.public_key)
            if isinstance(method.public_key, str) and method.public_key.strip()
            else None
        ),
        secret_resolver=lambda _metadata: _resolve_external_hmac_secret(did, method.key_ref),
    )
    if verification.get("verified"):
        return True, None, document
    return False, str(verification.get("error") or "verification_failed"), document


async def _get_did_fact(session: AsyncSession, did: str) -> Fact | None:
    result = await session.execute(
        select(Fact).where(
            Fact.namespace == IDENTITY_NAMESPACE,
            Fact.subject == did,
            Fact.predicate == DID_PREDICATE,
        )
    )
    return result.scalar_one_or_none()


async def _get_delegation_fact(session: AsyncSession, delegation_id: str) -> Fact | None:
    result = await session.execute(
        select(Fact).where(
            Fact.namespace == IDENTITY_NAMESPACE,
            Fact.predicate == f"{DELEGATION_PREDICATE_PREFIX}{delegation_id}",
        )
    )
    return result.scalar_one_or_none()


async def _get_owner_fact(session: AsyncSession, owner_id: str, predicate: str) -> Fact | None:
    result = await session.execute(
        select(Fact).where(
            Fact.namespace == IDENTITY_NAMESPACE,
            Fact.subject == owner_id,
            Fact.predicate == predicate,
        )
    )
    return result.scalar_one_or_none()


async def _list_owner_delegations(session: AsyncSession, owner_id: str) -> list[DelegationRecord]:
    result = await session.execute(
        select(Fact).where(
            Fact.namespace == IDENTITY_NAMESPACE,
            Fact.subject == owner_id,
        )
    )
    delegations: list[DelegationRecord] = []
    for fact in result.scalars():
        if not isinstance(fact.predicate, str) or not fact.predicate.startswith(DELEGATION_PREDICATE_PREFIX):
            continue
        if not isinstance(fact.object_data, dict):
            continue
        try:
            delegations.append(DelegationRecord(**fact.object_data))
        except Exception:
            continue
    return delegations


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _resolve_external_hmac_secret(did: str, key_ref: Optional[str]) -> Optional[str]:
    raw = os.getenv("SEEDCORE_EXTERNAL_INTENT_HMAC_SECRETS_JSON", "").strip()
    if not raw:
        return None
    try:
        registry = json.loads(raw)
    except Exception:
        return None
    if not isinstance(registry, dict):
        return None
    for candidate in (did, key_ref):
        if isinstance(candidate, str) and candidate.strip():
            secret = registry.get(candidate.strip())
            if isinstance(secret, str) and secret.strip():
                return secret.strip()
    return None


async def _record_nonce_once(signer_did: str, nonce: str, ttl_seconds: int) -> Optional[str]:
    cache_key = f"seedcore:external-intent-nonce:{signer_did}:{nonce}"
    redis_client = await get_async_redis_client()
    if redis_client is not None:
        try:
            created = await redis_client.set(cache_key, "1", ex=ttl_seconds, nx=True)
            if not created:
                return "replayed_nonce"
            return None
        except Exception:
            pass

    now = time.time()
    expired = [key for key, expires_at in _NONCE_CACHE.items() if expires_at <= now]
    for key in expired:
        _NONCE_CACHE.pop(key, None)
    if cache_key in _NONCE_CACHE:
        return "replayed_nonce"
    _NONCE_CACHE[cache_key] = now + ttl_seconds
    return None
