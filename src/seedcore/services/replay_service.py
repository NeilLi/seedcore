from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import String, select, text

from seedcore.coordinator.dao import (
    AssetCustodyStateDAO,
    CustodyDisputeDAO,
    CustodyTransitionDAO,
    DigitalTwinDAO,
    GovernedExecutionAuditDAO,
)
from seedcore.hal.custody.transition_receipts import verify_transition_receipt_result
from seedcore.models import DatabaseTask as Task
from seedcore.models.replay import (
    PublicTrustReference,
    ReplayProjectionKind,
    ReplayRecord,
    ReplayTimelineEvent,
    ReplayVerificationStatus,
    TrustCertificate,
    TrustPageProjection,
    VerificationResult,
)
from seedcore.ops.evidence.materializer import materialize_seedcore_custody_event_payload
from seedcore.ops.evidence.policy import build_policy_summary
from seedcore.ops.evidence.verification import (
    build_signed_artifact,
    verify_artifact_signature,
    verify_evidence_bundle_result,
    verify_policy_receipt_result,
)
from seedcore.services.custody_graph_service import CustodyGraphService


TRUST_TOKEN_PREFIX = "stp1"
DEFAULT_TRUST_REFERENCE_TTL_HOURS = int(os.getenv("SEEDCORE_TRUST_REFERENCE_TTL_HOURS", "168"))
TRUST_PROJECTION_VERSION = os.getenv("SEEDCORE_TRUST_PROJECTION_VERSION", "v1")


class ReplayServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReplayService:
    def __init__(
        self,
        *,
        governance_audit_dao: Optional[GovernedExecutionAuditDAO] = None,
        digital_twin_dao: Optional[DigitalTwinDAO] = None,
        asset_custody_dao: Optional[AssetCustodyStateDAO] = None,
        custody_transition_dao: Optional[CustodyTransitionDAO] = None,
        custody_dispute_dao: Optional[CustodyDisputeDAO] = None,
    ) -> None:
        self._governance_audit_dao = governance_audit_dao or GovernedExecutionAuditDAO()
        self._digital_twin_dao = digital_twin_dao or DigitalTwinDAO()
        self._asset_custody_dao = asset_custody_dao or AssetCustodyStateDAO()
        self._custody_graph_service = CustodyGraphService(
            transition_dao=custody_transition_dao,
            dispute_dao=custody_dispute_dao,
            digital_twin_dao=self._digital_twin_dao,
        )

    async def resolve_lookup_record(
        self,
        session,
        *,
        task_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        audit_id: Optional[str] = None,
    ) -> tuple[str, str, Dict[str, Any]]:
        provided = [("task_id", task_id), ("intent_id", intent_id), ("audit_id", audit_id)]
        provided = [(key, value.strip()) for key, value in provided if isinstance(value, str) and value.strip()]
        if len(provided) != 1:
            raise ReplayServiceError(
                "invalid_lookup",
                "Provide exactly one retrieval key: task_id, intent_id, or audit_id",
            )

        key, value = provided[0]
        if key == "task_id":
            resolved_task_id = await self._resolve_task_id(session, value)
            record = await self._governance_audit_dao.get_latest_for_task(session, task_id=resolved_task_id)
            lookup_value = resolved_task_id
        elif key == "intent_id":
            record = await self._governance_audit_dao.get_latest_for_intent(session, intent_id=value)
            lookup_value = value
        else:
            try:
                lookup_value = str(uuid.UUID(value))
            except ValueError as exc:
                raise ReplayServiceError("invalid_audit_id", "Invalid audit_id format") from exc
            record = await self._governance_audit_dao.get_by_entry_id(session, entry_id=lookup_value)

        if record is None:
            raise ReplayServiceError("record_not_found", "Governed audit record not found")
        return key, lookup_value, record

    async def resolve_subject_record(
        self,
        session,
        *,
        subject_id: str,
        subject_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized_subject_id = str(subject_id).strip()
        normalized_subject_type = str(subject_type).strip().lower() if isinstance(subject_type, str) and subject_type.strip() else None

        if not normalized_subject_id:
            return None
        if normalized_subject_type in (None, "asset"):
            row = await self._get_latest_for_asset_subject(session, subject_id=normalized_subject_id)
            if row is not None:
                return row
            if normalized_subject_type == "asset":
                return None
        if normalized_subject_type in (None, "transaction"):
            intent_id = normalized_subject_id.split(":", 1)[1] if normalized_subject_id.startswith("transaction:") else normalized_subject_id
            return await self._governance_audit_dao.get_latest_for_intent(session, intent_id=intent_id)
        return None

    async def assemble_replay_record(
        self,
        session,
        *,
        task_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        audit_id: Optional[str] = None,
        audit_record: Optional[Mapping[str, Any]] = None,
    ) -> tuple[str, str, ReplayRecord]:
        if audit_record is not None:
            record = dict(audit_record)
            lookup_key = "audit_id"
            lookup_value = str(record.get("id") or "")
        else:
            lookup_key, lookup_value, record = await self.resolve_lookup_record(
                session,
                task_id=task_id,
                intent_id=intent_id,
                audit_id=audit_id,
            )

        evidence_bundle = record.get("evidence_bundle") if isinstance(record.get("evidence_bundle"), dict) else {}
        if not evidence_bundle:
            raise ReplayServiceError(
                "missing_evidence_bundle",
                "Audit record exists but has no evidence_bundle to materialize",
            )

        policy_receipt = record.get("policy_receipt") if isinstance(record.get("policy_receipt"), dict) else {}
        authz_graph = self._extract_authz_graph(record=record)
        governed_receipt = self._extract_governed_receipt(record=record)
        transition_receipts = self._extract_transition_receipts(evidence_bundle=evidence_bundle)
        subject_type, subject_id = self._derive_subject(record=record, evidence_bundle=evidence_bundle, policy_receipt=policy_receipt)
        asset_custody_state = await self._load_asset_custody_state(session, subject_type=subject_type, subject_id=subject_id)
        custody_transition_refs = await self._load_custody_transition_refs(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        digital_twin_history_refs = await self._load_digital_twin_history(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            intent_id=str(record.get("intent_id") or ""),
        )
        dispute_refs = await self._load_dispute_refs(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            custody_transition_refs=custody_transition_refs,
        )
        signer_chain = self._build_signer_chain(policy_receipt=policy_receipt, evidence_bundle=evidence_bundle, transition_receipts=transition_receipts)
        verification_status = self._build_verification_status(
            policy_receipt=policy_receipt,
            evidence_bundle=evidence_bundle,
            transition_receipts=transition_receipts,
        )
        replay_timeline = self._build_replay_timeline(
            record=record,
            authz_graph=authz_graph,
            governed_receipt=governed_receipt,
            policy_receipt=policy_receipt,
            evidence_bundle=evidence_bundle,
            transition_receipts=transition_receipts,
            custody_transition_refs=custody_transition_refs,
            digital_twin_history_refs=digital_twin_history_refs,
            dispute_refs=dispute_refs,
        )

        replay = ReplayRecord(
            replay_id=f"replay:{record['id']}",
            subject_type=subject_type,
            subject_id=subject_id,
            task_id=str(record.get("task_id") or ""),
            intent_id=str(record.get("intent_id") or ""),
            audit_record_id=str(record.get("id") or ""),
            authz_graph=authz_graph,
            governed_receipt=governed_receipt,
            policy_receipt=policy_receipt,
            evidence_bundle=evidence_bundle,
            transition_receipts=transition_receipts,
            custody_transition_refs=custody_transition_refs,
            digital_twin_history_refs=digital_twin_history_refs,
            dispute_refs=dispute_refs,
            signer_chain=signer_chain,
            verification_status=verification_status,
            replay_timeline=replay_timeline,
            audit_record=record,
            asset_custody_state=asset_custody_state,
        )
        replay.jsonld_export = self.build_jsonld_export(replay)
        replay.public_projection = self.project_record(replay, ReplayProjectionKind.PUBLIC)
        replay.buyer_projection = self.project_record(replay, ReplayProjectionKind.BUYER)
        replay.auditor_projection = self.project_record(replay, ReplayProjectionKind.AUDITOR)
        replay.internal_projection = self.project_record(replay, ReplayProjectionKind.INTERNAL)
        return lookup_key, lookup_value, replay

    def project_record(
        self,
        replay: ReplayRecord,
        projection: ReplayProjectionKind | str,
    ) -> Dict[str, Any]:
        kind = self._coerce_projection(projection)
        if kind == ReplayProjectionKind.INTERNAL:
            return {
                "replay_id": replay.replay_id,
                "subject_type": replay.subject_type,
                "subject_id": replay.subject_id,
                "task_id": replay.task_id,
                "intent_id": replay.intent_id,
                "audit_record_id": replay.audit_record_id,
                "authz_graph": replay.authz_graph,
                "governed_receipt": replay.governed_receipt,
                "verification_status": replay.verification_status.model_dump(mode="json"),
                "policy_receipt": replay.policy_receipt,
                "evidence_bundle": replay.evidence_bundle,
                "transition_receipts": replay.transition_receipts,
                "asset_custody_state": replay.asset_custody_state,
                "custody_transition_refs": replay.custody_transition_refs,
                "dispute_refs": replay.dispute_refs,
                "digital_twin_history_refs": replay.digital_twin_history_refs,
                "signer_chain": replay.signer_chain,
                "replay_timeline": [item.model_dump(mode="json") for item in replay.replay_timeline],
                "audit_record": replay.audit_record,
            }
        if kind == ReplayProjectionKind.AUDITOR:
            return {
                "replay_id": replay.replay_id,
                "subject_type": replay.subject_type,
                "subject_id": replay.subject_id,
                "task_id": replay.task_id,
                "intent_id": replay.intent_id,
                "audit_record_id": replay.audit_record_id,
                "authz_graph": replay.authz_graph,
                "governed_receipt": replay.governed_receipt,
                "verification_status": replay.verification_status.model_dump(mode="json"),
                "policy_receipt": replay.policy_receipt,
                "evidence_bundle": self._auditor_safe_evidence_bundle(replay.evidence_bundle),
                "transition_receipts": replay.transition_receipts,
                "asset_custody_state": replay.asset_custody_state,
                "custody_transition_refs": replay.custody_transition_refs,
                "dispute_refs": replay.dispute_refs,
                "digital_twin_history_refs": replay.digital_twin_history_refs,
                "signer_chain": replay.signer_chain,
                "replay_timeline": [item.model_dump(mode="json") for item in replay.replay_timeline],
            }
        trust_projection = self._build_trust_page_projection(replay=replay, audience=kind)
        payload = trust_projection.model_dump(mode="json")
        if kind == ReplayProjectionKind.BUYER:
            payload["signer_chain"] = [self._sanitize_signer_entry(item, include_key_ref=False) for item in replay.signer_chain]
            payload["replay_available"] = True
        return payload

    def build_jsonld_export(
        self,
        replay: ReplayRecord,
        *,
        public_id: Optional[str] = None,
        projection: ReplayProjectionKind | str = ReplayProjectionKind.INTERNAL,
    ) -> Dict[str, Any]:
        kind = self._coerce_projection(projection)
        payload = materialize_seedcore_custody_event_payload(audit_record=replay.audit_record)
        payload["seedcore:subject_type"] = replay.subject_type
        payload["seedcore:subject_id"] = replay.subject_id
        payload["proof"] = {
            "type": "SeedCoreReplayProof",
            "verification_status": replay.verification_status.model_dump(mode="json"),
            "trust_reference": public_id,
            "signer_chain": [
                self._sanitize_signer_entry(item, include_key_ref=kind in {ReplayProjectionKind.INTERNAL, ReplayProjectionKind.AUDITOR})
                for item in replay.signer_chain
            ],
        }
        if kind in {ReplayProjectionKind.PUBLIC, ReplayProjectionKind.BUYER}:
            signer_metadata = payload.get("signer_metadata")
            if isinstance(signer_metadata, dict):
                signer_metadata.pop("key_ref", None)
        return payload

    def build_public_reference(
        self,
        *,
        lookup_key: str,
        lookup_value: str,
        replay: ReplayRecord,
        ttl_hours: Optional[int] = None,
    ) -> tuple[PublicTrustReference, str]:
        issued_at = self._utcnow().isoformat()
        ttl = max(1, int(ttl_hours or DEFAULT_TRUST_REFERENCE_TTL_HOURS))
        expires_at = (self._utcnow() + timedelta(hours=ttl)).isoformat()
        reference = PublicTrustReference(
            jti=str(uuid.uuid4()),
            lookup_key=lookup_key,
            lookup_value=lookup_value,
            audit_id=replay.audit_record_id,
            subject_type=replay.subject_type,
            subject_id=replay.subject_id,
            issued_at=issued_at,
            expires_at=expires_at,
            projection_version=TRUST_PROJECTION_VERSION,
        )
        return reference, self.encode_public_reference(reference)

    def encode_public_reference(self, reference: PublicTrustReference) -> str:
        payload_segment = self._b64url_encode(
            json.dumps(reference.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature_segment = self._sign_reference_payload(payload_segment)
        return f"{TRUST_TOKEN_PREFIX}.{payload_segment}.{signature_segment}"

    def decode_public_reference(self, public_id: str) -> PublicTrustReference:
        parts = str(public_id).split(".")
        if len(parts) != 3 or parts[0] != TRUST_TOKEN_PREFIX:
            raise ReplayServiceError("invalid_public_id", "Invalid public trust reference")
        payload_segment, signature_segment = parts[1], parts[2]
        expected_signature = self._sign_reference_payload(payload_segment)
        if not hmac.compare_digest(signature_segment, expected_signature):
            raise ReplayServiceError("invalid_signature", "Public trust reference signature is invalid")
        try:
            payload = json.loads(self._b64url_decode(payload_segment).decode("utf-8"))
        except Exception as exc:
            raise ReplayServiceError("invalid_public_id", "Public trust reference payload is invalid") from exc
        return PublicTrustReference(**payload)

    async def verify_reference(
        self,
        session,
        *,
        reference_id: Optional[str] = None,
        public_id: Optional[str] = None,
        audit_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        redis_client: Any = None,
    ) -> VerificationResult:
        verification_time = self._utcnow().isoformat()
        if isinstance(public_id, str) and public_id.strip():
            reference_id = public_id.strip()

        if isinstance(reference_id, str) and reference_id.strip():
            return await self._verify_public_reference(
                session,
                reference_id=reference_id.strip(),
                verification_time=verification_time,
                redis_client=redis_client,
            )

        if isinstance(audit_id, str) and audit_id.strip():
            try:
                _, _, replay = await self.assemble_replay_record(session, audit_id=audit_id.strip())
            except ReplayServiceError as exc:
                return self._failed_verification_result(
                    reference_type="audit_id",
                    reference_id=audit_id.strip(),
                    verification_time=verification_time,
                    reason=exc.code,
                )
            return self._verification_result_from_replay(
                replay=replay,
                reference_type="audit_id",
                reference_id=audit_id.strip(),
                verification_time=verification_time,
            )

        if isinstance(subject_id, str) and subject_id.strip():
            record = await self.resolve_subject_record(session, subject_id=subject_id.strip(), subject_type=subject_type)
            if record is None:
                return self._failed_verification_result(
                    reference_type="subject_id",
                    reference_id=subject_id.strip(),
                    verification_time=verification_time,
                    reason="record_not_found",
                    subject_id=subject_id.strip(),
                    subject_type=subject_type,
                )
            _, _, replay = await self.assemble_replay_record(session, audit_record=record)
            return self._verification_result_from_replay(
                replay=replay,
                reference_type="subject_id",
                reference_id=subject_id.strip(),
                verification_time=verification_time,
            )

        raise ReplayServiceError("invalid_verification_request", "Provide reference_id, public_id, audit_id, or subject_id")

    async def build_trust_certificate(
        self,
        replay: ReplayRecord,
        *,
        public_id: str,
        expires_at: Optional[str],
    ) -> TrustCertificate:
        issued_at = self._utcnow().isoformat()
        projection = self._build_trust_page_projection(replay=replay, audience=ReplayProjectionKind.PUBLIC)
        certificate_payload = {
            "certificate_id": str(uuid.uuid4()),
            "public_id": public_id,
            "subject_type": replay.subject_type,
            "subject_id": replay.subject_id,
            "verification_status": replay.verification_status.model_dump(mode="json"),
            "trust_assertions": projection.verifiable_claims,
            "public_claims": projection.verifiable_claims,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        payload_hash, signer_metadata, signature = build_signed_artifact(
            artifact_type="trust_certificate",
            payload=certificate_payload,
            endpoint_id=None,
            trust_level="baseline",
            node_id=None,
        )
        certificate_payload["payload_hash"] = payload_hash
        return TrustCertificate(
            certificate_id=certificate_payload["certificate_id"],
            public_id=public_id,
            subject_type=replay.subject_type,
            subject_id=replay.subject_id,
            verification_status=certificate_payload["verification_status"],
            trust_assertions=certificate_payload["trust_assertions"],
            public_claims=certificate_payload["public_claims"],
            issued_at=issued_at,
            expires_at=expires_at,
            signer_metadata=signer_metadata.model_dump(mode="json"),
            signature=signature,
        )

    async def reference_is_revoked(self, *, reference: PublicTrustReference, redis_client: Any = None) -> bool:
        if redis_client is None:
            return False
        getter = getattr(redis_client, "get", None)
        if not callable(getter):
            return False
        try:
            return bool(await getter(self._revocation_key(reference.jti)))
        except Exception:
            return False

    async def revoke_reference(self, *, public_id: str, redis_client: Any) -> Dict[str, Any]:
        if redis_client is None:
            raise ReplayServiceError("redis_unavailable", "Redis is required to revoke public trust references")
        reference = self.decode_public_reference(public_id)
        expires_at = self._parse_datetime(reference.expires_at)
        ttl_seconds = max(1, int((expires_at - self._utcnow()).total_seconds()))
        setter = getattr(redis_client, "set", None)
        if not callable(setter):
            raise ReplayServiceError("redis_unavailable", "Redis client does not support set()")
        await setter(self._revocation_key(reference.jti), self._utcnow().isoformat(), ex=ttl_seconds)
        return {
            "public_id": public_id,
            "revoked": True,
            "revoked_at": self._utcnow().isoformat(),
            "expires_at": reference.expires_at,
        }

    async def _verify_public_reference(
        self,
        session,
        *,
        reference_id: str,
        verification_time: str,
        redis_client: Any = None,
    ) -> VerificationResult:
        try:
            reference = self.decode_public_reference(reference_id)
        except ReplayServiceError as exc:
            return self._failed_verification_result(
                reference_type="trust_token",
                reference_id=reference_id,
                verification_time=verification_time,
                reason=exc.code,
                signature_valid=False,
                tamper_status="signature_invalid",
            )

        if self._parse_datetime(reference.expires_at) <= self._utcnow():
            return self._failed_verification_result(
                reference_type="trust_token",
                reference_id=reference_id,
                verification_time=verification_time,
                reason="expired_reference",
                subject_id=reference.subject_id,
                subject_type=reference.subject_type,
                signature_valid=True,
                tamper_status="expired",
            )

        if await self.reference_is_revoked(reference=reference, redis_client=redis_client):
            return self._failed_verification_result(
                reference_type="trust_token",
                reference_id=reference_id,
                verification_time=verification_time,
                reason="revoked_reference",
                subject_id=reference.subject_id,
                subject_type=reference.subject_type,
                signature_valid=True,
                tamper_status="revoked",
            )

        try:
            _, _, replay = await self.assemble_replay_record(session, audit_id=reference.audit_id)
        except ReplayServiceError as exc:
            return self._failed_verification_result(
                reference_type="trust_token",
                reference_id=reference_id,
                verification_time=verification_time,
                reason=exc.code,
                subject_id=reference.subject_id,
                subject_type=reference.subject_type,
                signature_valid=True,
            )
        return self._verification_result_from_replay(
            replay=replay,
            reference_type="trust_token",
            reference_id=reference_id,
            verification_time=verification_time,
        )

    async def _load_asset_custody_state(
        self,
        session,
        *,
        subject_type: str,
        subject_id: str,
    ) -> Optional[Dict[str, Any]]:
        if subject_type != "asset":
            return None
        try:
            return await self._asset_custody_dao.get_snapshot(session, asset_id=subject_id)
        except Exception:
            return None

    async def _load_digital_twin_history(
        self,
        session,
        *,
        subject_type: str,
        subject_id: str,
        intent_id: str,
    ) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        twin_queries: List[tuple[str, str]] = []
        if subject_type == "asset":
            twin_queries.append(("asset", f"asset:{subject_id}"))
        twin_queries.append(("transaction", f"transaction:{intent_id}"))
        seen_queries: set[tuple[str, str]] = set()
        index = 0
        while index < len(twin_queries):
            twin_type, twin_id = twin_queries[index]
            index += 1
            if not twin_type or not twin_id or (twin_type, twin_id) in seen_queries:
                continue
            seen_queries.add((twin_type, twin_id))
            try:
                rows = await self._digital_twin_dao.list_history(session, twin_type=twin_type, twin_id=twin_id, limit=25)
            except Exception:
                rows = []
            for row in rows:
                refs.append({**row, "twin_ref": twin_id})
                snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
                lineage_refs = snapshot.get("lineage_refs") if isinstance(snapshot.get("lineage_refs"), list) else []
                for ref in lineage_refs:
                    if not isinstance(ref, str) or ":" not in ref:
                        continue
                    lineage_type = ref.split(":", 1)[0]
                    if lineage_type in {"batch", "product"} and (lineage_type, ref) not in seen_queries:
                        twin_queries.append((lineage_type, ref))
        refs.sort(key=lambda item: item.get("recorded_at") or "")
        return refs

    async def _load_custody_transition_refs(
        self,
        session,
        *,
        subject_type: str,
        subject_id: str,
    ) -> List[Dict[str, Any]]:
        if subject_type != "asset":
            return []
        try:
            return await self._custody_graph_service.get_asset_transitions(session, asset_id=subject_id, limit=50)
        except Exception:
            return []

    async def _load_dispute_refs(
        self,
        session,
        *,
        subject_type: str,
        subject_id: str,
        custody_transition_refs: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        try:
            if subject_type == "asset":
                return await self._custody_graph_service.disputes_for_asset(session, asset_id=subject_id)
            dispute_refs: List[Dict[str, Any]] = []
            for item in custody_transition_refs:
                transition_event_id = item.get("transition_event_id")
                if not transition_event_id:
                    continue
                dispute_refs.extend(
                    await self._custody_graph_service.disputes_for_transition(session, transition_event_id=str(transition_event_id))
                )
            deduped = {item["dispute_id"]: item for item in dispute_refs if isinstance(item, dict) and item.get("dispute_id")}
            return list(deduped.values())
        except Exception:
            return []

    async def _get_latest_for_asset_subject(self, session, *, subject_id: str) -> Optional[Dict[str, Any]]:
        stmt = text(
            """
            SELECT
                id,
                task_id,
                record_type,
                intent_id,
                token_id,
                policy_snapshot,
                policy_decision,
                action_intent,
                policy_case,
                policy_receipt,
                evidence_bundle,
                actor_agent_id,
                actor_organ_id,
                input_hash,
                evidence_hash,
                recorded_at
            FROM governed_execution_audit
            WHERE COALESCE(policy_receipt->>'asset_ref', action_intent->'resource'->>'asset_id') = :subject_id
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """
        )
        result = await session.execute(stmt, {"subject_id": str(subject_id)})
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._governance_audit_dao._mapping_to_dict(row)

    async def _resolve_task_id(self, session, task_id_or_prefix: str) -> str:
        try:
            return str(uuid.UUID(task_id_or_prefix))
        except ValueError:
            query = select(Task.id).where(Task.id.cast(String).like(f"{task_id_or_prefix}%")).limit(2)
            rows = (await session.execute(query)).all()
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise ReplayServiceError("ambiguous_task_id", "Ambiguous task ID prefix")
            raise ReplayServiceError("record_not_found", "Task ID not found")

    def _derive_subject(
        self,
        *,
        record: Mapping[str, Any],
        evidence_bundle: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
    ) -> tuple[str, str]:
        resource = (
            record.get("action_intent", {}).get("resource")
            if isinstance(record.get("action_intent"), dict)
            and isinstance(record.get("action_intent", {}).get("resource"), dict)
            else {}
        )
        capture_context = (
            evidence_bundle.get("asset_fingerprint", {}).get("capture_context")
            if isinstance(evidence_bundle.get("asset_fingerprint"), dict)
            and isinstance(evidence_bundle.get("asset_fingerprint", {}).get("capture_context"), dict)
            else {}
        )
        asset_id = None
        for candidate in (
            policy_receipt.get("asset_ref"),
            resource.get("asset_id"),
            capture_context.get("asset_id"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                asset_id = candidate.strip()
                break
        if asset_id:
            return "asset", asset_id
        intent_id = str(record.get("intent_id") or "")
        return "transaction", f"transaction:{intent_id}" if intent_id else "transaction:unknown"

    def _extract_transition_receipts(self, *, evidence_bundle: Mapping[str, Any]) -> List[Dict[str, Any]]:
        evidence_inputs = evidence_bundle.get("evidence_inputs") if isinstance(evidence_bundle.get("evidence_inputs"), dict) else {}
        receipts = evidence_inputs.get("transition_receipts") if isinstance(evidence_inputs.get("transition_receipts"), list) else []
        return [dict(item) for item in receipts if isinstance(item, dict)]

    def _extract_authz_graph(self, *, record: Mapping[str, Any]) -> Dict[str, Any]:
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        authz_graph = policy_decision.get("authz_graph")
        return dict(authz_graph) if isinstance(authz_graph, dict) else {}

    def _extract_governed_receipt(self, *, record: Mapping[str, Any]) -> Dict[str, Any]:
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        governed_receipt = policy_decision.get("governed_receipt")
        return dict(governed_receipt) if isinstance(governed_receipt, dict) else {}

    def _build_signer_chain(
        self,
        *,
        policy_receipt: Mapping[str, Any],
        evidence_bundle: Mapping[str, Any],
        transition_receipts: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        chain: List[Dict[str, Any]] = []
        if policy_receipt:
            chain.append(
                {
                    "artifact_type": "policy_receipt",
                    "artifact_id": policy_receipt.get("policy_receipt_id"),
                    "signature": policy_receipt.get("signature"),
                    "signer_metadata": dict(policy_receipt.get("signer_metadata") or {}),
                }
            )
        if evidence_bundle:
            chain.append(
                {
                    "artifact_type": "evidence_bundle",
                    "artifact_id": evidence_bundle.get("evidence_bundle_id"),
                    "signature": evidence_bundle.get("signature"),
                    "signer_metadata": dict(evidence_bundle.get("signer_metadata") or {}),
                }
            )
        for receipt in transition_receipts:
            chain.append(
                {
                    "artifact_type": "transition_receipt",
                    "artifact_id": receipt.get("transition_receipt_id"),
                    "signature": receipt.get("signature"),
                    "signer_metadata": dict(receipt.get("signer_metadata") or {}),
                }
            )
        return chain

    def _build_verification_status(
        self,
        *,
        policy_receipt: Mapping[str, Any],
        evidence_bundle: Mapping[str, Any],
        transition_receipts: Sequence[Mapping[str, Any]],
    ) -> ReplayVerificationStatus:
        issues: List[str] = []
        artifact_results: Dict[str, Any] = {}
        signer_policy: Dict[str, Any] = {
            "policy_receipt": build_policy_summary(artifact_type="policy_receipt"),
            "evidence_bundle": build_policy_summary(
                artifact_type="evidence_bundle",
                endpoint_id=str(evidence_bundle.get("node_id")) if evidence_bundle.get("node_id") is not None else None,
                trust_level=(
                    "attested"
                    if evidence_bundle.get("signer_metadata", {}).get("attestation_level") == "attested"
                    else "baseline"
                ),
            ),
            "transition_receipt": build_policy_summary(
                artifact_type="transition_receipt",
                endpoint_id=str(transition_receipts[0].get("endpoint_id")) if transition_receipts else None,
                trust_level="attested" if transition_receipts else None,
            ),
        }
        if not policy_receipt:
            issues.append("missing_policy_receipt")
            artifact_results["policy_receipt"] = {
                "artifact_type": "policy_receipt",
                "verified": False,
                "error": "missing_policy_receipt",
                "policy": signer_policy["policy_receipt"],
            }
        else:
            policy_result = verify_policy_receipt_result(policy_receipt)
            artifact_results["policy_receipt"] = policy_result
            if policy_result.get("error") is not None:
                issues.append(f"policy_receipt:{policy_result['error']}")
        evidence_result = verify_evidence_bundle_result(evidence_bundle)
        artifact_results["evidence_bundle"] = evidence_result
        if evidence_result.get("error") is not None:
            issues.append(f"evidence_bundle:{evidence_result['error']}")
        transition_results: List[Dict[str, Any]] = []
        for receipt in transition_receipts:
            transition_result = verify_transition_receipt_result(dict(receipt))
            transition_results.append(transition_result)
            if transition_result.get("error") is not None:
                issues.append(
                    f"transition_receipt:{receipt.get('transition_receipt_id')}:{transition_result['error']}"
                )
        artifact_results["transition_receipts"] = transition_results

        signature_valid = not any(
            marker in issue
            for issue in issues
            for marker in ("signature_mismatch", "payload_hash_mismatch", "missing_public_key", "invalid_signature", "unsupported_signing_scheme")
        )
        if issues:
            if any("payload_hash_mismatch" in issue for issue in issues):
                tamper_status = "payload_mismatch"
            elif any("signature" in issue or "public_key" in issue for issue in issues):
                tamper_status = "signature_invalid"
            else:
                tamper_status = "incomplete"
        else:
            tamper_status = "clear"
        policy_trace_available = bool(policy_receipt)
        evidence_trace_available = bool(evidence_bundle) and bool(transition_receipts or evidence_bundle.get("evidence_inputs"))
        return ReplayVerificationStatus(
            verified=signature_valid and policy_trace_available and evidence_trace_available and tamper_status == "clear",
            signature_valid=signature_valid,
            policy_trace_available=policy_trace_available,
            evidence_trace_available=evidence_trace_available,
            tamper_status=tamper_status,
            issues=issues,
            verified_at=self._utcnow().isoformat(),
            artifact_results=artifact_results,
            signer_policy=signer_policy,
        )

    def _build_replay_timeline(
        self,
        *,
        record: Mapping[str, Any],
        authz_graph: Mapping[str, Any],
        governed_receipt: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
        evidence_bundle: Mapping[str, Any],
        transition_receipts: Sequence[Mapping[str, Any]],
        custody_transition_refs: Sequence[Mapping[str, Any]],
        digital_twin_history_refs: Sequence[Mapping[str, Any]],
        dispute_refs: Sequence[Mapping[str, Any]],
    ) -> List[ReplayTimelineEvent]:
        events: List[ReplayTimelineEvent] = []
        if authz_graph and (policy_receipt.get("timestamp") or governed_receipt.get("generated_at") or record.get("recorded_at")):
            disposition = str(authz_graph.get("disposition") or governed_receipt.get("disposition") or "unknown")
            summary = "Authorization graph evaluated transition for governed action"
            if disposition == "quarantine":
                summary = "Authorization graph quarantined asset transition pending trust-gap resolution"
            elif disposition == "deny":
                summary = "Authorization graph denied asset transition"
            elif disposition == "allow":
                summary = "Authorization graph authorized asset transition"
            events.append(
                ReplayTimelineEvent(
                    event_id=str(governed_receipt.get("decision_hash") or policy_receipt.get("policy_decision_id") or "authz_transition"),
                    event_type="authz_transition_evaluated",
                    timestamp=str(policy_receipt.get("timestamp") or governed_receipt.get("generated_at") or record.get("recorded_at")),
                    summary=summary,
                    artifact_ref=str(governed_receipt.get("decision_hash") or ""),
                    details={
                        "disposition": disposition,
                        "reason": authz_graph.get("reason") or governed_receipt.get("reason"),
                        "asset_ref": governed_receipt.get("asset_ref") or authz_graph.get("asset_ref"),
                        "resource_ref": governed_receipt.get("resource_ref") or authz_graph.get("resource_ref"),
                        "trust_gap_codes": self._trust_gap_codes(replay_authz_graph=authz_graph, replay_governed_receipt=governed_receipt),
                    },
                )
            )
        if policy_receipt.get("timestamp"):
            events.append(
                ReplayTimelineEvent(
                    event_id=str(policy_receipt.get("policy_receipt_id") or "policy_receipt"),
                    event_type="policy_receipt_issued",
                    timestamp=str(policy_receipt.get("timestamp")),
                    summary="Policy receipt recorded for governed action",
                    artifact_ref=str(policy_receipt.get("policy_receipt_id") or ""),
                    details={
                        "policy_decision_id": policy_receipt.get("policy_decision_id"),
                        "policy_version": policy_receipt.get("policy_version"),
                    },
                )
            )
        if record.get("recorded_at"):
            events.append(
                ReplayTimelineEvent(
                    event_id=str(record.get("id") or "audit_record"),
                    event_type="audit_recorded",
                    timestamp=str(record.get("recorded_at")),
                    summary="Governed audit record appended",
                    artifact_ref=str(record.get("id") or ""),
                    details={"record_type": record.get("record_type")},
                )
            )
        for receipt in transition_receipts:
            if receipt.get("executed_at"):
                events.append(
                    ReplayTimelineEvent(
                        event_id=str(receipt.get("transition_receipt_id") or f"transition:{uuid.uuid4()}"),
                        event_type="transition_executed",
                        timestamp=str(receipt.get("executed_at")),
                        summary="Controlled transition receipt captured",
                        artifact_ref=str(receipt.get("transition_receipt_id") or ""),
                        details={
                            "from_zone": receipt.get("from_zone"),
                            "to_zone": receipt.get("to_zone"),
                            "endpoint_id": receipt.get("endpoint_id"),
                        },
                    )
                )
        if evidence_bundle.get("created_at"):
            events.append(
                ReplayTimelineEvent(
                    event_id=str(evidence_bundle.get("evidence_bundle_id") or "evidence_bundle"),
                    event_type="evidence_materialized",
                    timestamp=str(evidence_bundle.get("created_at")),
                    summary="Evidence bundle sealed for replay",
                    artifact_ref=str(evidence_bundle.get("evidence_bundle_id") or ""),
                    details={"node_id": evidence_bundle.get("node_id")},
                )
            )
        for twin_event in digital_twin_history_refs:
            recorded_at = twin_event.get("recorded_at")
            if not recorded_at:
                continue
            events.append(
                ReplayTimelineEvent(
                    event_id=str(twin_event.get("id") or f"twin:{uuid.uuid4()}"),
                    event_type="digital_twin_updated",
                    timestamp=str(recorded_at),
                    summary="Authoritative digital twin history recorded",
                    artifact_ref=str(twin_event.get("twin_ref") or ""),
                    details={
                        "twin_type": twin_event.get("twin_type"),
                        "state_version": twin_event.get("state_version"),
                        "authority_source": twin_event.get("authority_source"),
                    },
                )
            )
        for transition_event in custody_transition_refs:
            recorded_at = transition_event.get("recorded_at")
            if not recorded_at:
                continue
            events.append(
                ReplayTimelineEvent(
                    event_id=str(transition_event.get("transition_event_id") or f"custody-transition:{uuid.uuid4()}"),
                    event_type="custody_lineage_recorded",
                    timestamp=str(recorded_at),
                    summary="Custody lineage chain updated",
                    artifact_ref=str(transition_event.get("transition_event_id") or ""),
                    details={
                        "transition_seq": transition_event.get("transition_seq"),
                        "lineage_status": transition_event.get("lineage_status"),
                    },
                )
            )
        for dispute in dispute_refs:
            recorded_at = dispute.get("recorded_at") or dispute.get("updated_at")
            if not recorded_at:
                continue
            events.append(
                ReplayTimelineEvent(
                    event_id=str(dispute.get("dispute_id") or f"dispute:{uuid.uuid4()}"),
                    event_type="custody_dispute_linked",
                    timestamp=str(recorded_at),
                    summary="Custody dispute linked to replay subject",
                    artifact_ref=str(dispute.get("dispute_id") or ""),
                    details={"status": dispute.get("status"), "title": dispute.get("title")},
                )
            )
        return sorted(events, key=lambda item: self._parse_datetime(item.timestamp))

    def _build_trust_page_projection(
        self,
        *,
        replay: ReplayRecord,
        audience: ReplayProjectionKind,
    ) -> TrustPageProjection:
        workflow_type = self._workflow_type(replay)
        workflow_status = self._workflow_status(replay)
        custody_summary = self._build_custody_summary(replay)
        fingerprint_summary = self._build_fingerprint_summary(replay)
        policy_summary = self._build_policy_summary(replay)
        approvals = self._build_approval_summary(replay)
        authorization = self._build_authorization_summary(replay)
        dispute_summary = self._build_dispute_summary(replay)
        timeline_summary = [
            {
                "event_type": item.event_type,
                "timestamp": item.timestamp,
                "summary": item.summary,
            }
            for item in replay.replay_timeline
        ]
        claims = self._build_verifiable_claims(replay)
        media_refs = self._public_media_refs(replay.evidence_bundle)
        subject_label = "Asset" if replay.subject_type == "asset" else "Transaction"
        if workflow_status == "quarantined":
            subject_summary = f"{subject_label} {replay.subject_id} is restricted pending trust-gap resolution, with governed evidence preserved."
        elif workflow_status == "pending_approval":
            subject_summary = f"{subject_label} {replay.subject_id} is awaiting required approvals before governed transfer can proceed."
        elif workflow_status == "review_required":
            subject_summary = f"{subject_label} {replay.subject_id} requires governed review before transfer can proceed."
        elif workflow_status == "rejected":
            subject_summary = f"{subject_label} {replay.subject_id} was rejected by the governed transfer policy path."
        elif audience == ReplayProjectionKind.BUYER:
            subject_summary = f"{subject_label} {replay.subject_id} has a governed replay record with trust-safe evidence."
        else:
            subject_summary = f"{subject_label} {replay.subject_id} can be verified from governed policy and evidence records."
        return TrustPageProjection(
            workflow_type=workflow_type,
            status=workflow_status,
            subject_title=f"{subject_label} {replay.subject_id}",
            subject_summary=subject_summary,
            verification_status=replay.verification_status.model_dump(mode="json"),
            approvals=approvals,
            authorization=authorization,
            custody_summary=custody_summary,
            fingerprint_summary=fingerprint_summary,
            policy_summary=policy_summary,
            dispute_summary=dispute_summary,
            timeline_summary=timeline_summary,
            verifiable_claims=claims,
            public_media_refs=media_refs,
        )

    def _build_custody_summary(self, replay: ReplayRecord) -> Dict[str, Any]:
        asset_state = replay.asset_custody_state or {}
        transition = replay.transition_receipts[-1] if replay.transition_receipts else {}
        trust_gap_codes = self._trust_gap_codes(
            replay_authz_graph=replay.authz_graph,
            replay_governed_receipt=replay.governed_receipt,
        )
        return {
            "current_zone": asset_state.get("current_zone") or transition.get("to_zone") or transition.get("target_zone"),
            "previous_zone": transition.get("from_zone"),
            "quarantined": bool(asset_state.get("is_quarantined")) or replay.governed_receipt.get("disposition") == "quarantine",
            "authority_source": asset_state.get("authority_source"),
            "last_transition_seq": asset_state.get("last_transition_seq"),
            "lineage_events": len(replay.custody_transition_refs),
            "linked_disputes": len(replay.dispute_refs),
            "current_custodian": replay.authz_graph.get("current_custodian"),
            "custody_proof_count": len(replay.governed_receipt.get("custody_proof") or []),
            "trust_gap_codes": trust_gap_codes,
        }

    def _build_fingerprint_summary(self, replay: ReplayRecord) -> Dict[str, Any]:
        fingerprint = replay.evidence_bundle.get("asset_fingerprint") if isinstance(replay.evidence_bundle.get("asset_fingerprint"), dict) else {}
        modality_map = fingerprint.get("modality_map") if isinstance(fingerprint.get("modality_map"), dict) else {}
        return {
            "fingerprint_id": fingerprint.get("fingerprint_id"),
            "fingerprint_hash": fingerprint.get("fingerprint_hash"),
            "modalities": sorted(modality_map.keys()),
        }

    def _build_policy_summary(self, replay: ReplayRecord) -> Dict[str, Any]:
        receipt = replay.policy_receipt
        decision = receipt.get("decision") if isinstance(receipt.get("decision"), dict) else {}
        trust_gap_codes = self._trust_gap_codes(
            replay_authz_graph=replay.authz_graph,
            replay_governed_receipt=replay.governed_receipt,
        )
        return {
            "policy_receipt_id": receipt.get("policy_receipt_id"),
            "policy_decision_id": receipt.get("policy_decision_id"),
            "policy_version": receipt.get("policy_version"),
            "disposition": decision.get("disposition"),
            "allowed": decision.get("allowed"),
            "timestamp": receipt.get("timestamp"),
            "authz_reason": replay.authz_graph.get("reason") or replay.governed_receipt.get("reason"),
            "governed_receipt_hash": replay.governed_receipt.get("decision_hash"),
            "trust_gap_codes": trust_gap_codes,
            "restricted_token_recommended": bool(replay.authz_graph.get("restricted_token_recommended")),
            "custody_proof_count": len(replay.governed_receipt.get("custody_proof") or []),
            "workflow_status": self._workflow_status(replay),
            "authority_path_summary": list(replay.authz_graph.get("authority_path_summary") or []),
            "minted_artifacts": list(replay.authz_graph.get("minted_artifacts") or []),
            "obligations": list(replay.authz_graph.get("obligations") or []),
        }

    def _build_dispute_summary(self, replay: ReplayRecord) -> Dict[str, Any]:
        disputes = replay.dispute_refs or []
        return {
            "count": len(disputes),
            "open_count": sum(1 for item in disputes if item.get("status") in {"OPEN", "UNDER_REVIEW"}),
            "statuses": sorted({str(item.get("status")) for item in disputes if item.get("status")}),
            "linked_dispute_ids": [item.get("dispute_id") for item in disputes if item.get("dispute_id")],
        }

    def _policy_decision_payload(self, replay: ReplayRecord) -> Dict[str, Any]:
        record = replay.audit_record if isinstance(replay.audit_record, dict) else {}
        payload = record.get("policy_decision")
        return dict(payload) if isinstance(payload, dict) else {}

    def _action_intent_payload(self, replay: ReplayRecord) -> Dict[str, Any]:
        record = replay.audit_record if isinstance(replay.audit_record, dict) else {}
        payload = record.get("action_intent")
        return dict(payload) if isinstance(payload, dict) else {}

    def _approval_context(self, replay: ReplayRecord) -> Dict[str, Any]:
        action_intent = self._action_intent_payload(replay)
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        approval_context = parameters.get("approval_context")
        return dict(approval_context) if isinstance(approval_context, dict) else {}

    def _workflow_type(self, replay: ReplayRecord) -> Optional[str]:
        workflow_type = replay.authz_graph.get("workflow_type")
        if isinstance(workflow_type, str) and workflow_type.strip():
            return workflow_type.strip()
        approval_context = self._approval_context(replay)
        if approval_context:
            return "custody_transfer"
        action_intent = self._action_intent_payload(replay)
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        action_type = str(action.get("type") or "").strip().upper()
        if action_type == "TRANSFER_CUSTODY":
            return "custody_transfer"
        return None

    def _workflow_status(self, replay: ReplayRecord) -> Optional[str]:
        policy_decision = self._policy_decision_payload(replay)
        required_approvals = policy_decision.get("required_approvals") if isinstance(policy_decision.get("required_approvals"), list) else []
        disposition = str(
            replay.authz_graph.get("disposition")
            or replay.governed_receipt.get("disposition")
            or policy_decision.get("disposition")
            or ""
        ).strip().lower()
        if not disposition:
            return None
        if disposition == "allow":
            return "verified"
        if disposition == "quarantine":
            return "quarantined"
        if disposition == "deny":
            return "rejected"
        if disposition == "escalate":
            return "pending_approval" if required_approvals else "review_required"
        return None

    def _build_approval_summary(self, replay: ReplayRecord) -> Dict[str, Any]:
        policy_decision = self._policy_decision_payload(replay)
        approval_context = self._approval_context(replay)
        required = policy_decision.get("required_approvals") if isinstance(policy_decision.get("required_approvals"), list) else []
        completed_by = (
            replay.authz_graph.get("approved_by")
            if isinstance(replay.authz_graph.get("approved_by"), list)
            else approval_context.get("approved_by")
            if isinstance(approval_context.get("approved_by"), list)
            else []
        )
        return {
            "required": list(required),
            "completed_by": list(completed_by),
            "approval_envelope_id": (
                replay.authz_graph.get("approval_envelope_id")
                or replay.governed_receipt.get("approval_envelope_id")
                or approval_context.get("approval_envelope_id")
            ),
            "approval_transition_head": (
                replay.authz_graph.get("approval_transition_head")
                or replay.governed_receipt.get("approval_transition_head")
                or approval_context.get("approval_transition_head")
            ),
            "approval_transition_count": (
                replay.authz_graph.get("approval_transition_count")
                if isinstance(replay.authz_graph.get("approval_transition_count"), int)
                else replay.governed_receipt.get("approval_transition_count")
                if isinstance(replay.governed_receipt.get("approval_transition_count"), int)
                else len(approval_context.get("approval_transition_history"))
                if isinstance(approval_context.get("approval_transition_history"), list)
                else 0
            ),
        }

    def _build_authorization_summary(self, replay: ReplayRecord) -> Dict[str, Any]:
        return {
            "disposition": replay.authz_graph.get("disposition") or replay.governed_receipt.get("disposition"),
            "governed_receipt_hash": replay.governed_receipt.get("decision_hash"),
            "policy_receipt_id": replay.policy_receipt.get("policy_receipt_id"),
            "execution_token_id": (
                replay.audit_record.get("token_id")
                if isinstance(replay.audit_record, dict)
                else None
            ) or replay.evidence_bundle.get("execution_token_id"),
        }

    def _build_verifiable_claims(self, replay: ReplayRecord) -> List[Dict[str, Any]]:
        governed_receipt_hash = replay.governed_receipt.get("decision_hash")
        claims = [
            {
                "claim": "governed_policy_verified",
                "value": bool((replay.policy_receipt.get("decision") or {}).get("allowed", replay.verification_status.policy_trace_available)),
                "source": replay.policy_receipt.get("policy_receipt_id"),
            },
            {
                "claim": "evidence_bundle_available",
                "value": bool(replay.evidence_bundle),
                "source": replay.evidence_bundle.get("evidence_bundle_id"),
            },
            {
                "claim": "signature_chain_valid",
                "value": replay.verification_status.signature_valid,
                "source": replay.audit_record_id,
            },
        ]
        if governed_receipt_hash:
            claims.append(
                {
                    "claim": "governed_receipt_available",
                    "value": True,
                    "source": governed_receipt_hash,
                }
            )
        if replay.subject_type == "asset":
            claims.append(
                {
                    "claim": "custody_trace_available",
                    "value": bool(replay.transition_receipts or replay.asset_custody_state or replay.custody_transition_refs),
                    "source": replay.audit_record_id,
                }
            )
        trust_gap_codes = self._trust_gap_codes(
            replay_authz_graph=replay.authz_graph,
            replay_governed_receipt=replay.governed_receipt,
        )
        if trust_gap_codes:
            claims.append(
                {
                    "claim": "trust_gap_detected",
                    "value": True,
                    "source": governed_receipt_hash or replay.audit_record_id,
                }
            )
        return claims

    def _trust_gap_codes(
        self,
        *,
        replay_authz_graph: Mapping[str, Any],
        replay_governed_receipt: Mapping[str, Any],
    ) -> List[str]:
        codes: List[str] = []
        receipt_codes = replay_governed_receipt.get("trust_gap_codes")
        if isinstance(receipt_codes, list):
            for code in receipt_codes:
                if isinstance(code, str) and code.strip() and code not in codes:
                    codes.append(code.strip())
        trust_gaps = replay_authz_graph.get("trust_gaps")
        if isinstance(trust_gaps, list):
            for item in trust_gaps:
                if not isinstance(item, dict):
                    continue
                code = item.get("code")
                if isinstance(code, str) and code.strip() and code not in codes:
                    codes.append(code.strip())
        return codes

    def _public_media_refs(self, evidence_bundle: Mapping[str, Any]) -> List[Dict[str, Any]]:
        refs = evidence_bundle.get("media_refs") if isinstance(evidence_bundle.get("media_refs"), list) else []
        public_refs: List[Dict[str, Any]] = []
        for item in refs:
            if not isinstance(item, dict):
                continue
            sanitized = {key: value for key, value in item.items() if key in {"kind", "source", "sha256", "content_type", "uri", "captured_at"}}
            if sanitized:
                public_refs.append(sanitized)
        return public_refs

    def _auditor_safe_evidence_bundle(self, evidence_bundle: Mapping[str, Any]) -> Dict[str, Any]:
        result = dict(evidence_bundle)
        signer_metadata = result.get("signer_metadata")
        if isinstance(signer_metadata, dict):
            result["signer_metadata"] = dict(signer_metadata)
        return result

    def _sanitize_signer_entry(self, item: Mapping[str, Any], *, include_key_ref: bool) -> Dict[str, Any]:
        signer_metadata = dict(item.get("signer_metadata") or {})
        if not include_key_ref:
            signer_metadata.pop("key_ref", None)
        return {
            "artifact_type": item.get("artifact_type"),
            "artifact_id": item.get("artifact_id"),
            "signer_metadata": signer_metadata,
        }

    def _verification_result_from_replay(
        self,
        *,
        replay: ReplayRecord,
        reference_type: str,
        reference_id: str,
        verification_time: str,
    ) -> VerificationResult:
        projection = self._build_trust_page_projection(replay=replay, audience=ReplayProjectionKind.PUBLIC)
        return VerificationResult(
            verification_id=str(uuid.uuid4()),
            reference_type=reference_type,
            reference_id=reference_id,
            subject_id=replay.subject_id,
            subject_type=replay.subject_type,
            verified=replay.verification_status.verified,
            signature_valid=replay.verification_status.signature_valid,
            policy_trace_available=replay.verification_status.policy_trace_available,
            evidence_trace_available=replay.verification_status.evidence_trace_available,
            tamper_status=replay.verification_status.tamper_status,
            verification_time=verification_time,
            public_claims=projection.verifiable_claims,
            reason=None if replay.verification_status.verified else "verification_failed",
        )

    def _failed_verification_result(
        self,
        *,
        reference_type: str,
        reference_id: str,
        verification_time: str,
        reason: str,
        subject_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        signature_valid: bool = True,
        tamper_status: str = "unknown",
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=str(uuid.uuid4()),
            reference_type=reference_type,
            reference_id=reference_id,
            subject_id=subject_id,
            subject_type=subject_type,
            verified=False,
            signature_valid=signature_valid,
            policy_trace_available=False,
            evidence_trace_available=False,
            tamper_status=tamper_status,
            verification_time=verification_time,
            public_claims=[],
            reason=reason,
        )

    def _revocation_key(self, jti: str) -> str:
        return f"seedcore:trust:revoked:{jti}"

    def _sign_reference_payload(self, payload_segment: str) -> str:
        secret = os.getenv(
            "SEEDCORE_TRUST_SIGNING_SECRET",
            os.getenv("SEEDCORE_EVIDENCE_SIGNING_SECRET", "seedcore-dev-evidence-secret"),
        )
        digest = hmac.new(secret.encode("utf-8"), payload_segment.encode("utf-8"), hashlib.sha256).digest()
        return self._b64url_encode(digest)

    def _coerce_projection(self, projection: ReplayProjectionKind | str) -> ReplayProjectionKind:
        if isinstance(projection, ReplayProjectionKind):
            return projection
        return ReplayProjectionKind(str(projection).strip().lower())

    def _b64url_encode(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _b64url_decode(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _parse_datetime(self, value: str) -> datetime:
        normalized = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
