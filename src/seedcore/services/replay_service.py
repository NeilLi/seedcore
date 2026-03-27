from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import String, select, text

from seedcore.coordinator.dao import (
    AssetCustodyStateDAO,
    CustodyDisputeDAO,
    CustodyTransitionDAO,
    DigitalTwinDAO,
    GovernedExecutionAuditDAO,
)
from seedcore.integrations.rust_kernel import (
    mint_execution_token_with_rust,
    seal_replay_bundle_with_rust,
    verify_approval_transition_history_with_rust,
    verify_replay_bundle_with_rust,
)
from seedcore.hal.custody.transition_receipts import verify_transition_receipt_result
from seedcore.models import DatabaseTask as Task
from seedcore.models.evidence_bundle import TrustBundle, TrustBundleKey, TrustBundleTransparencyConfig
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
from seedcore.ops.evidence.policy import build_policy_summary, canonical_json, sha256_hex
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
DEFAULT_TRUST_BUNDLE_SCHEMA_VERSION = os.getenv("SEEDCORE_TRUST_BUNDLE_SCHEMA_VERSION", "phase_a_v1")


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
            record=record,
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
        proof_payload = {
            "type": "SeedCoreReplayProof",
            "verification_status": replay.verification_status.model_dump(mode="json"),
            "trust_reference": public_id,
            "signer_chain": [
                self._sanitize_signer_entry(item, include_key_ref=kind in {ReplayProjectionKind.INTERNAL, ReplayProjectionKind.AUDITOR})
                for item in replay.signer_chain
            ],
        }
        approval_context = self._approval_context(replay)
        transition_history = (
            list(approval_context.get("approval_transition_history"))
            if isinstance(approval_context.get("approval_transition_history"), list)
            else []
        )
        transition_head = (
            str(approval_context.get("approval_transition_head")).strip()
            if approval_context.get("approval_transition_head") is not None and str(approval_context.get("approval_transition_head")).strip()
            else None
        )
        if transition_history:
            if kind in {ReplayProjectionKind.INTERNAL, ReplayProjectionKind.AUDITOR}:
                chain_events = [dict(item) for item in transition_history if isinstance(item, dict)]
            else:
                chain_events = [
                    {
                        "event_hash": item.get("event_hash"),
                        "previous_event_hash": item.get("previous_event_hash"),
                        "occurred_at": item.get("occurred_at"),
                        "transition_type": item.get("transition_type"),
                        "envelope_version": item.get("envelope_version"),
                    }
                    for item in transition_history
                    if isinstance(item, dict)
                ]
            proof_payload["approval_transition_chain"] = {
                "head": transition_head,
                "count": len(chain_events),
                "events": chain_events,
            }
        payload["proof"] = proof_payload
        if kind in {ReplayProjectionKind.PUBLIC, ReplayProjectionKind.BUYER}:
            signer_metadata = payload.get("signer_metadata")
            if isinstance(signer_metadata, dict):
                signer_metadata.pop("key_ref", None)
        return payload

    async def publish_trust_bundle(
        self,
        session,
        *,
        task_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        audit_id: Optional[str] = None,
        bundle_version: Optional[str] = None,
        promote_current: bool = True,
        revoked_keys: Optional[Sequence[str]] = None,
        revoked_nodes: Optional[Sequence[str]] = None,
        revocation_cutoffs: Optional[Mapping[str, Any]] = None,
        redis_client: Any = None,
    ) -> Dict[str, Any]:
        replay: Optional[ReplayRecord] = None
        lookup_key: Optional[str] = None
        lookup_value: Optional[str] = None
        if any(isinstance(value, str) and value.strip() for value in (task_id, intent_id, audit_id)):
            lookup_key, lookup_value, replay = await self.assemble_replay_record(
                session,
                task_id=task_id,
                intent_id=intent_id,
                audit_id=audit_id,
            )

        bundle = self.build_trust_bundle(
            replay=replay,
            bundle_version=bundle_version,
            revoked_keys=revoked_keys,
            revoked_nodes=revoked_nodes,
            revocation_cutoffs=revocation_cutoffs,
        )
        bundle_id = f"tb-{self._utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        published_at = self._utcnow().isoformat()
        snapshot: Dict[str, Any] = {
            "bundle_id": bundle_id,
            "published_at": published_at,
            "lookup_key": lookup_key,
            "lookup_value": lookup_value,
            "subject_id": replay.subject_id if replay is not None else None,
            "subject_type": replay.subject_type if replay is not None else None,
            "trust_bundle": bundle.model_dump(mode="json"),
        }
        signed_envelope = self._build_signed_trust_bundle_envelope(snapshot)
        snapshot["payload_hash"] = signed_envelope["payload_hash"]
        snapshot["signature_envelope"] = signed_envelope["signature_envelope"]
        snapshot["trust_proof"] = signed_envelope.get("trust_proof")
        self._persist_trust_bundle_snapshot(snapshot, promote_current=promote_current)
        if redis_client is not None:
            await self._cache_trust_bundle_snapshot(snapshot=snapshot, promote_current=promote_current, redis_client=redis_client)
        return snapshot

    async def get_published_trust_bundle(
        self,
        *,
        bundle_id: Optional[str] = None,
        redis_client: Any = None,
    ) -> Optional[Dict[str, Any]]:
        resolved_id = str(bundle_id).strip() if isinstance(bundle_id, str) and bundle_id.strip() else None
        if resolved_id is None and redis_client is not None:
            getter = getattr(redis_client, "get", None)
            if callable(getter):
                try:
                    current = await getter("seedcore:trust_bundle:current")
                    if isinstance(current, bytes):
                        current = current.decode("utf-8", errors="ignore")
                    if isinstance(current, str) and current.strip():
                        resolved_id = current.strip()
                except Exception:
                    resolved_id = None
        if resolved_id is None:
            resolved_id = self._load_current_trust_bundle_id_from_disk()
        if resolved_id is None:
            return None

        if redis_client is not None:
            getter = getattr(redis_client, "get", None)
            if callable(getter):
                try:
                    cached = await getter(f"seedcore:trust_bundle:{resolved_id}")
                    if isinstance(cached, bytes):
                        cached = cached.decode("utf-8", errors="ignore")
                    if isinstance(cached, str) and cached.strip():
                        parsed = json.loads(cached)
                        if isinstance(parsed, dict):
                            return parsed
                except Exception:
                    pass
        return self._load_trust_bundle_snapshot_from_disk(resolved_id)

    def build_trust_bundle(
        self,
        *,
        replay: Optional[ReplayRecord] = None,
        bundle_version: Optional[str] = None,
        revoked_keys: Optional[Sequence[str]] = None,
        revoked_nodes: Optional[Sequence[str]] = None,
        revocation_cutoffs: Optional[Mapping[str, Any]] = None,
    ) -> TrustBundle:
        configured_keys = self._configured_trust_key_registry()
        key_entries: Dict[str, Dict[str, Any]] = {
            key_ref: dict(entry) for key_ref, entry in configured_keys.items()
        }

        endpoint_bindings: Dict[str, str] = {}
        node_bindings: Dict[str, str] = {}
        missing_public_keys: List[str] = []
        attestation_roots: Dict[str, str] = self._load_json_object_env("SEEDCORE_TRUST_ATTESTATION_ROOTS_JSON")

        for key_ref, entry in key_entries.items():
            endpoint_id = self._optional_str(entry.get("endpoint_id"))
            node_id = self._optional_str(entry.get("node_id"))
            if endpoint_id:
                endpoint_bindings[endpoint_id] = key_ref
            if node_id:
                node_bindings[node_id] = key_ref
            attestation_root = self._optional_str(entry.get("attestation_root"))
            if attestation_root:
                attestation_roots[attestation_root] = self._optional_str(entry.get("attestation_root_value")) or "configured"

        if replay is not None:
            for artifact_type, payload in self._iter_replay_artifacts_for_bundle(replay):
                signer_metadata = payload.get("signer_metadata") if isinstance(payload.get("signer_metadata"), Mapping) else {}
                trust_proof = payload.get("trust_proof") if isinstance(payload.get("trust_proof"), Mapping) else {}
                key_ref = self._optional_str(trust_proof.get("key_ref")) or self._optional_str(signer_metadata.get("key_ref"))
                if not key_ref:
                    continue
                entry = key_entries.setdefault(key_ref, {"key_ref": key_ref})
                entry.setdefault("signer_profile", self._signer_profile_for_artifact_type(artifact_type))
                entry.setdefault(
                    "key_algorithm",
                    self._optional_str(trust_proof.get("key_algorithm"))
                    or self._optional_str(signer_metadata.get("signing_scheme"))
                    or "unknown",
                )
                entry.setdefault(
                    "trust_anchor_type",
                    self._optional_str(trust_proof.get("trust_anchor_type")) or "software",
                )
                entry.setdefault(
                    "revocation_id",
                    self._optional_str(trust_proof.get("revocation_id")),
                )
                entry.setdefault("endpoint_id", self._artifact_endpoint_id(payload, trust_proof))
                entry.setdefault("node_id", self._artifact_node_id(signer_metadata, trust_proof))
                attestation = trust_proof.get("attestation") if isinstance(trust_proof.get("attestation"), Mapping) else {}
                ak_key_ref = self._optional_str(attestation.get("ak_key_ref"))
                if ak_key_ref:
                    entry.setdefault("attestation_root", ak_key_ref)
                    attestation_roots.setdefault(ak_key_ref, "replay")
                if not self._optional_str(entry.get("public_key")):
                    missing_public_keys.append(key_ref)
                endpoint_id = self._optional_str(entry.get("endpoint_id"))
                node_id = self._optional_str(entry.get("node_id"))
                if endpoint_id:
                    endpoint_bindings[endpoint_id] = key_ref
                if node_id:
                    node_bindings[node_id] = key_ref

        trusted_keys: Dict[str, TrustBundleKey] = {}
        for key_ref, entry in key_entries.items():
            public_key = self._optional_str(entry.get("public_key"))
            if not public_key:
                continue
            trusted_keys[key_ref] = TrustBundleKey(
                key_ref=key_ref,
                key_algorithm=self._optional_str(entry.get("key_algorithm")) or "unknown",
                public_key=public_key,
                trust_anchor_type=self._optional_str(entry.get("trust_anchor_type")) or "software",
                signer_profile=self._optional_str(entry.get("signer_profile")),
                endpoint_id=self._optional_str(entry.get("endpoint_id")),
                node_id=self._optional_str(entry.get("node_id")),
                revocation_id=self._optional_str(entry.get("revocation_id")),
                attestation_root=self._optional_str(entry.get("attestation_root")),
                metadata=dict(entry.get("metadata") or {}),
            )

        revoked_key_set = set(self._load_string_set_env("SEEDCORE_TRUST_REVOKED_KEY_REFS_JSON"))
        revoked_key_set.update(self._normalized_str_set(revoked_keys))
        revoked_node_set = set(self._load_string_set_env("SEEDCORE_TRUST_REVOKED_NODE_IDS_JSON"))
        revoked_node_set.update(self._normalized_str_set(revoked_nodes))
        revocation_cutoff_map = {
            key: str(value)
            for key, value in self._load_json_object_env("SEEDCORE_TRUST_REVOKED_BEFORE_JSON").items()
            if self._optional_str(key) and value is not None
        }
        for key, value in dict(revocation_cutoffs or {}).items():
            normalized_key = self._optional_str(key)
            if not normalized_key or value is None:
                continue
            revocation_cutoff_map[normalized_key] = str(value)

        accepted_anchors = self._split_csv_env(
            "SEEDCORE_TRUST_ACCEPTED_ANCHORS",
            default=("tpm2", "kms", "vtpm"),
        )
        transparency = TrustBundleTransparencyConfig(
            enabled=self._env_flag("SEEDCORE_TRANSPARENCY_ENABLED", default=False),
            log_url=self._optional_str(os.getenv("SEEDCORE_TRANSPARENCY_LOG_URL")),
            public_key=self._optional_str(os.getenv("SEEDCORE_TRANSPARENCY_PUBLIC_KEY")),
            metadata={},
        )
        metadata: Dict[str, Any] = {
            "generated_at": self._utcnow().isoformat(),
            "source": "replay_service.publish_trust_bundle",
            "missing_public_keys": sorted(set(missing_public_keys)),
        }
        if replay is not None:
            metadata["audit_id"] = replay.audit_record_id
            metadata["subject_id"] = replay.subject_id
            metadata["subject_type"] = replay.subject_type

        return TrustBundle(
            version=self._optional_str(bundle_version) or DEFAULT_TRUST_BUNDLE_SCHEMA_VERSION,
            trusted_keys=trusted_keys,
            endpoint_bindings=endpoint_bindings,
            node_bindings=node_bindings,
            accepted_trust_anchor_types=accepted_anchors,
            attestation_roots=attestation_roots,
            revoked_keys=sorted(revoked_key_set),
            revoked_nodes=sorted(revoked_node_set),
            revocation_cutoffs=revocation_cutoff_map,
            transparency=transparency,
            metadata=metadata,
        )

    def _build_signed_trust_bundle_envelope(self, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        trust_bundle = snapshot.get("trust_bundle")
        if not isinstance(trust_bundle, Mapping):
            raise ReplayServiceError("invalid_trust_bundle", "Trust bundle snapshot payload is missing trust_bundle")
        payload = dict(trust_bundle)
        payload_hash = sha256_hex(canonical_json(payload))
        signing_material = f"sha256:{payload_hash}"
        secret = self._trust_bundle_signing_secret()
        signature = hmac.new(
            secret.encode("utf-8"),
            signing_material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signer_id = os.getenv("SEEDCORE_TRUST_BUNDLE_SIGNER_ID", "seedcore-trust-bundle-signer")
        return {
            "payload_hash": payload_hash,
            "signature_envelope": {
                "signer_type": "service",
                "signer_id": signer_id,
                "signing_scheme": "hmac_sha256",
                "key_ref": self._trust_bundle_signing_key_ref(),
                "attestation_level": "baseline",
                "signature": signature,
            },
            "trust_proof": None,
        }

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
        payload_hash, signer_metadata, signature, _trust_proof = build_signed_artifact(
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
        record: Mapping[str, Any],
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
        approval_context = self._approval_context_from_record(record)
        approval_history_events = (
            list(approval_context.get("approval_transition_history"))
            if isinstance(approval_context.get("approval_transition_history"), list)
            else []
        )
        if approval_history_events:
            approval_history_payload = {
                "events": approval_history_events,
                "chain_head": approval_context.get("approval_transition_head"),
            }
            history_result = verify_approval_transition_history_with_rust(approval_history_payload)
            artifact_results["approval_transition_history"] = history_result
            if not bool(history_result.get("valid")):
                issues.append(
                    f"approval_transition_history:{history_result.get('error_code') or 'invalid'}"
                )
        rust_replay_artifacts = self._build_rust_replay_artifacts(
            record=record,
            policy_receipt=policy_receipt,
            evidence_bundle=evidence_bundle,
            transition_receipts=transition_receipts,
            approval_context=approval_context,
        )
        expected_allow_chain = self._normalize_disposition(
            (
                policy_receipt.get("decision", {}).get("disposition")
                if isinstance(policy_receipt.get("decision"), dict)
                else None
            )
            or policy_receipt.get("authz_disposition")
            or (
                record.get("policy_decision", {}).get("disposition")
                if isinstance(record.get("policy_decision"), dict)
                else None
            )
        ) == "allow"
        if rust_replay_artifacts:
            sealed_bundle = seal_replay_bundle_with_rust(rust_replay_artifacts)
            if isinstance(sealed_bundle.get("artifacts"), list) and sealed_bundle.get("artifacts"):
                rust_chain_result = verify_replay_bundle_with_rust(sealed_bundle)
                rust_chain_result["artifact_count"] = len(sealed_bundle["artifacts"])
                rust_chain_result["artifact_ids"] = [
                    str(item.get("artifact_id"))
                    for item in sealed_bundle["artifacts"]
                    if isinstance(item, dict) and item.get("artifact_id") is not None
                ]
            else:
                rust_chain_result = {
                    "verified": False,
                    "error_code": str(sealed_bundle.get("error_code") or "rust_replay_bundle_seal_failed"),
                    "details": list(sealed_bundle.get("details") or []),
                    "artifact_reports": [],
                    "chain_checks": [],
                }
            if expected_allow_chain:
                reports = (
                    list(rust_chain_result.get("artifact_reports"))
                    if isinstance(rust_chain_result.get("artifact_reports"), list)
                    else []
                )
                token_report = next(
                    (
                        item
                        for item in reports
                        if isinstance(item, dict) and item.get("artifact_type") == "execution_token"
                    ),
                    None,
                )
                rust_chain_result["execution_token_required"] = True
                rust_chain_result["execution_token_present"] = token_report is not None
                rust_chain_result["execution_token_verified"] = bool(
                    isinstance(token_report, dict) and token_report.get("verified")
                )
                if token_report is None:
                    rust_chain_result["verified"] = False
                    if rust_chain_result.get("error_code") is None:
                        rust_chain_result["error_code"] = "allow_missing_execution_token"
                    issues.append("rust_replay_chain:allow_missing_execution_token")
                elif not bool(token_report.get("verified")):
                    rust_chain_result["verified"] = False
                    if rust_chain_result.get("error_code") is None:
                        rust_chain_result["error_code"] = "allow_invalid_execution_token"
                    issues.append("rust_replay_chain:allow_invalid_execution_token")
            artifact_results["rust_replay_chain"] = rust_chain_result
            if not bool(rust_chain_result.get("verified")):
                issues.append(f"rust_replay_chain:{rust_chain_result.get('error_code') or 'invalid'}")

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
        action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        approval_context = parameters.get("approval_context") if isinstance(parameters.get("approval_context"), dict) else {}
        approval_history = approval_context.get("approval_transition_history")
        if isinstance(approval_history, list):
            for item in approval_history:
                if not isinstance(item, dict):
                    continue
                occurred_at = item.get("occurred_at")
                if not isinstance(occurred_at, str) or not occurred_at.strip():
                    continue
                previous_status = str(item.get("previous_status") or "").strip()
                next_status = str(item.get("next_status") or "").strip()
                summary = "Approval transition applied for governed transfer."
                if previous_status and next_status:
                    summary = f"Approval transition applied: {previous_status} -> {next_status}."
                events.append(
                    ReplayTimelineEvent(
                        event_id=str(item.get("event_id") or item.get("event_hash") or f"approval-transition:{uuid.uuid4()}"),
                        event_type="approval_transition_applied",
                        timestamp=occurred_at,
                        summary=summary,
                        artifact_ref=str(item.get("event_hash") or ""),
                        details={
                            "transition_type": item.get("transition_type"),
                            "envelope_id": item.get("envelope_id"),
                            "event_hash": item.get("event_hash"),
                            "previous_event_hash": item.get("previous_event_hash"),
                        },
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

    def _approval_context_from_record(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        approval_context = parameters.get("approval_context")
        return dict(approval_context) if isinstance(approval_context, dict) else {}

    def _build_rust_replay_artifacts(
        self,
        *,
        record: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
        evidence_bundle: Mapping[str, Any],
        transition_receipts: Sequence[Mapping[str, Any]],
        approval_context: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        policy_artifact = self._rust_policy_receipt_artifact(record=record, policy_receipt=policy_receipt)
        if not policy_artifact:
            return []

        artifacts: List[Dict[str, Any]] = []
        action_intent_artifact = self._rust_action_intent_artifact(
            record=record,
            policy_receipt=policy_receipt,
            transition_receipts=transition_receipts,
            evidence_bundle=evidence_bundle,
        )
        if action_intent_artifact:
            artifacts.append(action_intent_artifact)
        policy_decision_artifact = self._rust_policy_decision_artifact(
            record=record,
            policy_receipt=policy_receipt,
            action_intent_id=(
                str(action_intent_artifact.get("artifact_id"))
                if isinstance(action_intent_artifact, dict)
                and action_intent_artifact.get("artifact_id") is not None
                else str(policy_receipt.get("intent_id") or record.get("intent_id") or "")
            ),
        )
        if policy_decision_artifact:
            artifacts.append(policy_decision_artifact)
        artifacts.append(policy_artifact)
        execution_token_artifact = self._rust_execution_token_artifact(
            record=record,
            policy_receipt=policy_receipt,
            transition_receipts=transition_receipts,
            evidence_bundle=evidence_bundle,
        )
        if execution_token_artifact:
            artifacts.append(execution_token_artifact)
        approval_history = (
            list(approval_context.get("approval_transition_history"))
            if isinstance(approval_context.get("approval_transition_history"), list)
            else []
        )
        if approval_history:
            artifacts.append(
                {
                    "artifact_id": f"approval-transition-history:{policy_artifact['artifact_id']}",
                    "artifact_type": "approval_transition_history",
                    "artifact": {
                        "events": [dict(item) for item in approval_history if isinstance(item, dict)],
                        "chain_head": approval_context.get("approval_transition_head"),
                    },
                }
            )

        for receipt in transition_receipts:
            converted = self._rust_transition_receipt_artifact(record=record, transition_receipt=receipt)
            if converted:
                artifacts.append(converted)

        evidence_artifact = self._rust_evidence_bundle_artifact(
            record=record,
            evidence_bundle=evidence_bundle,
            policy_receipt_id=policy_artifact["artifact_id"],
            transition_receipts=transition_receipts,
        )
        if evidence_artifact:
            artifacts.append(evidence_artifact)
        return artifacts

    def _rust_action_intent_artifact(
        self,
        *,
        record: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
        transition_receipts: Sequence[Mapping[str, Any]],
        evidence_bundle: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
        principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), dict) else {}
        environment = action_intent.get("environment") if isinstance(action_intent.get("environment"), dict) else {}
        fingerprint = (
            evidence_bundle.get("asset_fingerprint")
            if isinstance(evidence_bundle.get("asset_fingerprint"), dict)
            else {}
        )
        capture_context = (
            fingerprint.get("capture_context")
            if isinstance(fingerprint.get("capture_context"), dict)
            else {}
        )

        intent_id = str(action_intent.get("intent_id") or record.get("intent_id") or "").strip()
        if not intent_id:
            return None
        target_zone = (
            action.get("target_zone")
            or parameters.get("target_zone")
            or (transition_receipts[0].get("to_zone") if transition_receipts else None)
        )
        endpoint_id = (
            action.get("endpoint_id")
            or parameters.get("endpoint_id")
            or (transition_receipts[0].get("endpoint_id") if transition_receipts else None)
        )
        asset_ref = (
            resource.get("asset_ref")
            or resource.get("asset_id")
            or policy_receipt.get("asset_ref")
            or capture_context.get("asset_id")
            or f"asset:{intent_id}"
        )
        role_refs = principal.get("role_refs")
        if not isinstance(role_refs, list):
            role_refs = []

        environment_attributes = (
            {
                str(key): str(value)
                for key, value in environment.get("attributes", {}).items()
                if str(key).strip()
            }
            if isinstance(environment.get("attributes"), dict)
            else {}
        )

        timestamp = str(
            action_intent.get("timestamp")
            or policy_receipt.get("timestamp")
            or record.get("recorded_at")
            or self._utcnow().isoformat()
        )
        valid_until = str(action_intent.get("valid_until") or timestamp)
        return {
            "artifact_id": intent_id,
            "artifact_type": "action_intent",
            "artifact": {
                "intent_id": intent_id,
                "timestamp": timestamp,
                "valid_until": valid_until,
                "principal": {
                    "principal_ref": str(
                        principal.get("principal_ref")
                        or action_intent.get("subject_ref")
                        or record.get("actor_agent_id")
                        or "principal:unknown"
                    ),
                    "organization_ref": (
                        str(principal.get("organization_ref"))
                        if principal.get("organization_ref") is not None and str(principal.get("organization_ref")).strip()
                        else str(record.get("actor_organ_id"))
                        if record.get("actor_organ_id") is not None and str(record.get("actor_organ_id")).strip()
                        else None
                    ),
                    "role_refs": [str(item) for item in role_refs if item is not None and str(item).strip()],
                },
                "action": {
                    "action_type": str(action.get("type") or action.get("action_type") or "TRANSFER_CUSTODY"),
                    "target_zone": target_zone,
                    "endpoint_id": endpoint_id,
                },
                "resource": {
                    "asset_ref": str(asset_ref),
                    "lot_id": resource.get("lot_id"),
                },
                "environment": {
                    "source_registration_id": (
                        environment.get("source_registration_id")
                        or parameters.get("source_registration_id")
                    ),
                    "registration_decision_id": (
                        environment.get("registration_decision_id")
                        or parameters.get("registration_decision_id")
                    ),
                    "attributes": environment_attributes,
                },
            },
        }

    def _rust_policy_decision_artifact(
        self,
        *,
        record: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
        action_intent_id: str,
    ) -> Optional[Dict[str, Any]]:
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        authz_graph = policy_decision.get("authz_graph") if isinstance(policy_decision.get("authz_graph"), dict) else {}
        governed_receipt = (
            policy_decision.get("governed_receipt")
            if isinstance(policy_decision.get("governed_receipt"), dict)
            else {}
        )
        disposition = self._normalize_disposition(
            policy_decision.get("disposition")
            or policy_receipt.get("authz_disposition")
            or authz_graph.get("disposition")
            or governed_receipt.get("disposition")
        )
        intent_id = str(policy_receipt.get("intent_id") or record.get("intent_id") or "").strip()
        if not intent_id:
            return None
        policy_decision_id = str(
            policy_receipt.get("policy_decision_id")
            or policy_decision.get("policy_decision_id")
            or f"decision:{intent_id}"
        ).strip()
        if not policy_decision_id:
            return None
        policy_snapshot_ref = str(
            record.get("policy_snapshot")
            or policy_receipt.get("policy_version")
            or "snapshot:unknown"
        )
        allowed_value = policy_decision.get("allowed")
        allowed = bool(allowed_value) if isinstance(allowed_value, bool) else disposition == "allow"
        trust_gap_codes = self._trust_gap_codes(
            replay_authz_graph=authz_graph,
            replay_governed_receipt=governed_receipt,
        )
        reason = (
            str(policy_decision.get("reason")).strip()
            if policy_decision.get("reason") is not None and str(policy_decision.get("reason")).strip()
            else str(authz_graph.get("reason")).strip()
            if authz_graph.get("reason") is not None and str(authz_graph.get("reason")).strip()
            else str(governed_receipt.get("reason")).strip()
            if governed_receipt.get("reason") is not None and str(governed_receipt.get("reason")).strip()
            else None
        )
        return {
            "artifact_id": policy_decision_id,
            "artifact_type": "policy_decision",
            "artifact": {
                "policy_decision_id": policy_decision_id,
                "allowed": allowed,
                "disposition": disposition,
                "reason": reason,
                "policy_snapshot_ref": policy_snapshot_ref,
                "explanation": {
                    "disposition": disposition,
                    "matched_policy_refs": self._string_list(authz_graph.get("matched_policy_refs")),
                    "authority_path_summary": self._string_list(authz_graph.get("authority_path_summary")),
                    "missing_prerequisites": self._string_list(authz_graph.get("missing_prerequisites")),
                    "trust_gaps": trust_gap_codes,
                    "minted_artifacts": self._minted_artifact_refs(authz_graph.get("minted_artifacts")),
                    "obligations": self._obligation_entries(authz_graph.get("obligations")),
                },
                "governed_decision_artifact": {
                    "decision_id": policy_decision_id,
                    "action_intent_ref": action_intent_id or intent_id,
                    "policy_snapshot_ref": policy_snapshot_ref,
                    "disposition": disposition,
                    "asset_ref": str(
                        policy_receipt.get("asset_ref")
                        or authz_graph.get("asset_ref")
                        or governed_receipt.get("asset_ref")
                        or f"asset:{intent_id}"
                    ),
                },
                "execution_token": None,
            },
        }

    def _rust_execution_token_artifact(
        self,
        *,
        record: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
        transition_receipts: Sequence[Mapping[str, Any]],
        evidence_bundle: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        disposition = self._normalize_disposition(
            (
                policy_receipt.get("decision", {}).get("disposition")
                if isinstance(policy_receipt.get("decision"), dict)
                else None
            )
            or policy_receipt.get("authz_disposition")
            or policy_decision.get("disposition")
        )
        if disposition != "allow":
            return None

        existing = policy_decision.get("execution_token")
        if isinstance(existing, Mapping):
            required = {
                "token_id",
                "intent_id",
                "issued_at",
                "valid_until",
                "contract_version",
                "constraints",
                "artifact_hash",
                "signature",
            }
            if required.issubset(set(existing.keys())):
                token_id = str(existing.get("token_id") or "").strip()
                if token_id:
                    return {
                        "artifact_id": token_id,
                        "artifact_type": "execution_token",
                        "artifact": dict(existing),
                    }

        action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
        environment = action_intent.get("environment") if isinstance(action_intent.get("environment"), dict) else {}
        principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), dict) else {}
        decision = policy_receipt.get("decision") if isinstance(policy_receipt.get("decision"), dict) else {}

        issued_dt = self._parse_datetime(
            str(
                policy_receipt.get("timestamp")
                or record.get("recorded_at")
                or self._utcnow().isoformat()
            )
        )
        valid_until_dt = issued_dt + timedelta(minutes=1)
        intent_id = str(policy_receipt.get("intent_id") or record.get("intent_id") or "").strip()
        if not intent_id:
            return None
        token_id = str(
            record.get("token_id")
            or evidence_bundle.get("execution_token_id")
            or f"token:{intent_id}"
        ).strip()
        action_type = str(action.get("type") or action.get("action_type") or "TRANSFER_CUSTODY")
        target_zone = (
            action.get("target_zone")
            or parameters.get("target_zone")
            or (transition_receipts[0].get("to_zone") if transition_receipts else None)
        )
        endpoint_id = (
            action.get("endpoint_id")
            or parameters.get("endpoint_id")
            or (transition_receipts[0].get("endpoint_id") if transition_receipts else None)
        )
        asset_id = (
            resource.get("asset_id")
            or resource.get("asset_ref")
            or policy_receipt.get("asset_ref")
            or f"asset:{intent_id}"
        )
        minted = mint_execution_token_with_rust(
            {
                "token_id": token_id,
                "intent_id": intent_id,
                "issued_at": issued_dt.isoformat().replace("+00:00", "Z"),
                "valid_until": valid_until_dt.isoformat().replace("+00:00", "Z"),
                "contract_version": str(
                    policy_receipt.get("policy_version")
                    or record.get("policy_snapshot")
                    or "transfer-v1"
                ),
                "constraints": {
                    "action_type": action_type,
                    "target_zone": target_zone,
                    "asset_id": asset_id,
                    "principal_agent_id": (
                        principal.get("principal_ref")
                        or principal.get("agent_id")
                        or record.get("actor_agent_id")
                    ),
                    "source_registration_id": (
                        environment.get("source_registration_id")
                        or parameters.get("source_registration_id")
                    ),
                    "registration_decision_id": (
                        environment.get("registration_decision_id")
                        or parameters.get("registration_decision_id")
                    ),
                    "endpoint_id": endpoint_id,
                    "authz_disposition": str(decision.get("disposition") or disposition),
                },
            }
        )
        if not isinstance(minted, Mapping) or minted.get("token_id") is None:
            return None
        return {
            "artifact_id": str(minted.get("token_id")),
            "artifact_type": "execution_token",
            "artifact": dict(minted),
        }

    def _rust_policy_receipt_artifact(
        self,
        *,
        record: Mapping[str, Any],
        policy_receipt: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        policy_receipt_id = str(policy_receipt.get("policy_receipt_id") or "").strip()
        intent_id = str(policy_receipt.get("intent_id") or record.get("intent_id") or "").strip()
        if not policy_receipt_id or not intent_id:
            return None

        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        decision = policy_receipt.get("decision") if isinstance(policy_receipt.get("decision"), dict) else {}
        authz_graph = policy_decision.get("authz_graph") if isinstance(policy_decision.get("authz_graph"), dict) else {}
        governed_receipt = policy_decision.get("governed_receipt") if isinstance(policy_decision.get("governed_receipt"), dict) else {}
        disposition = self._normalize_disposition(
            decision.get("disposition")
            or policy_receipt.get("authz_disposition")
            or policy_decision.get("disposition")
            or authz_graph.get("disposition")
            or governed_receipt.get("disposition")
        )
        trust_gap_codes = self._trust_gap_codes(
            replay_authz_graph=authz_graph,
            replay_governed_receipt=governed_receipt,
        )

        return {
            "artifact_id": policy_receipt_id,
            "artifact_type": "policy_receipt",
            "artifact": {
                "policy_receipt_id": policy_receipt_id,
                "policy_decision_id": str(
                    policy_receipt.get("policy_decision_id") or f"decision:{intent_id}"
                ),
                "intent_id": intent_id,
                "policy_snapshot_ref": str(
                    record.get("policy_snapshot")
                    or policy_receipt.get("policy_version")
                    or "snapshot:unknown"
                ),
                "disposition": disposition,
                "explanation": {
                    "disposition": disposition,
                    "matched_policy_refs": self._string_list(authz_graph.get("matched_policy_refs")),
                    "authority_path_summary": self._string_list(authz_graph.get("authority_path_summary")),
                    "missing_prerequisites": self._string_list(authz_graph.get("missing_prerequisites")),
                    "trust_gaps": trust_gap_codes,
                    "minted_artifacts": self._minted_artifact_refs(authz_graph.get("minted_artifacts")),
                    "obligations": self._obligation_entries(authz_graph.get("obligations")),
                },
                "governed_receipt_hash": self._artifact_hash_object(
                    policy_receipt.get("governed_receipt_hash")
                    or governed_receipt.get("decision_hash")
                    or f"governed_receipt:{policy_receipt_id}",
                    fallback_seed=f"governed_receipt:{policy_receipt_id}",
                ),
                "signer": self._signature_envelope(policy_receipt, artifact_type="policy_receipt"),
                "timestamp": str(
                    policy_receipt.get("timestamp")
                    or record.get("recorded_at")
                    or self._utcnow().isoformat()
                ),
                "trust_proof": self._trust_proof_payload(policy_receipt),
            },
        }

    def _rust_transition_receipt_artifact(
        self,
        *,
        record: Mapping[str, Any],
        transition_receipt: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        transition_receipt_id = str(transition_receipt.get("transition_receipt_id") or "").strip()
        if not transition_receipt_id:
            return None
        intent_id = str(transition_receipt.get("intent_id") or record.get("intent_id") or "").strip()
        execution_token_id = str(
            transition_receipt.get("execution_token_id")
            or record.get("token_id")
            or f"token:{intent_id or 'unknown'}"
        )
        endpoint_id = str(transition_receipt.get("endpoint_id") or "seedcore://endpoint/unknown")
        hardware_uuid = str(transition_receipt.get("hardware_uuid") or "hardware:unknown")
        executed_at = str(
            transition_receipt.get("executed_at")
            or record.get("recorded_at")
            or self._utcnow().isoformat()
        )

        return {
            "artifact_id": transition_receipt_id,
            "artifact_type": "transition_receipt",
            "artifact": {
                "transition_receipt_id": transition_receipt_id,
                "intent_id": intent_id,
                "execution_token_id": execution_token_id,
                "endpoint_id": endpoint_id,
                "workflow_type": transition_receipt.get("workflow_type"),
                "hardware_uuid": hardware_uuid,
                "actuator_result_hash": self._artifact_hash_object(
                    transition_receipt.get("actuator_result_hash"),
                    fallback_seed=f"actuator_result:{transition_receipt_id}",
                ),
                "from_zone": transition_receipt.get("from_zone"),
                "to_zone": transition_receipt.get("to_zone"),
                "executed_at": executed_at,
                "receipt_nonce": str(
                    transition_receipt.get("receipt_nonce")
                    or f"nonce:{transition_receipt_id}"
                ),
                "payload_hash": self._artifact_hash_object(
                    transition_receipt.get("payload_hash"),
                    fallback_seed=f"payload:{transition_receipt_id}",
                ),
                "signer": self._signature_envelope(
                    transition_receipt,
                    artifact_type="transition_receipt",
                ),
                "trust_proof": self._trust_proof_payload(transition_receipt),
            },
        }

    def _rust_evidence_bundle_artifact(
        self,
        *,
        record: Mapping[str, Any],
        evidence_bundle: Mapping[str, Any],
        policy_receipt_id: str,
        transition_receipts: Sequence[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        evidence_bundle_id = str(evidence_bundle.get("evidence_bundle_id") or "").strip()
        intent_id = str(evidence_bundle.get("intent_id") or record.get("intent_id") or "").strip()
        if not evidence_bundle_id or not intent_id:
            return None
        created_at = str(
            evidence_bundle.get("created_at")
            or record.get("recorded_at")
            or self._utcnow().isoformat()
        )
        transition_ids = [
            str(item.get("transition_receipt_id"))
            for item in transition_receipts
            if isinstance(item, Mapping) and item.get("transition_receipt_id") is not None
        ]
        if not transition_ids:
            transition_ids = [
                str(item)
                for item in (evidence_bundle.get("transition_receipt_ids") or [])
                if item is not None and str(item).strip()
            ]

        telemetry_refs_raw = evidence_bundle.get("telemetry_refs")
        telemetry_refs = []
        if isinstance(telemetry_refs_raw, list):
            for index, item in enumerate(telemetry_refs_raw):
                if not isinstance(item, Mapping):
                    continue
                telemetry_id = str(
                    item.get("telemetry_id")
                    or item.get("id")
                    or item.get("kind")
                    or f"telemetry:{evidence_bundle_id}:{index}"
                )
                captured_at = str(item.get("captured_at") or created_at)
                telemetry_hash = self._artifact_hash_object(
                    item.get("hash") or item.get("sha256"),
                    fallback_seed=f"telemetry:{evidence_bundle_id}:{index}",
                )
                telemetry_refs.append(
                    {
                        "telemetry_id": telemetry_id,
                        "captured_at": captured_at,
                        "hash": telemetry_hash,
                    }
                )

        media_refs_raw = evidence_bundle.get("media_refs")
        media_refs = []
        if isinstance(media_refs_raw, list):
            for index, item in enumerate(media_refs_raw):
                if not isinstance(item, Mapping):
                    continue
                media_id = str(
                    item.get("media_id")
                    or item.get("id")
                    or item.get("uri")
                    or item.get("source")
                    or f"media:{evidence_bundle_id}:{index}"
                )
                media_type = str(item.get("media_type") or item.get("kind") or "unknown")
                media_hash = self._artifact_hash_object(
                    item.get("hash") or item.get("sha256"),
                    fallback_seed=f"media:{evidence_bundle_id}:{index}",
                )
                media_refs.append(
                    {
                        "media_id": media_id,
                        "media_type": media_type,
                        "hash": media_hash,
                    }
                )

        return {
            "artifact_id": evidence_bundle_id,
            "artifact_type": "evidence_bundle",
            "artifact": {
                "evidence_bundle_id": evidence_bundle_id,
                "intent_id": intent_id,
                "execution_token_id": evidence_bundle.get("execution_token_id"),
                "policy_receipt_id": (
                    evidence_bundle.get("policy_receipt_id")
                    or policy_receipt_id
                ),
                "transition_receipt_ids": transition_ids,
                "telemetry_refs": telemetry_refs,
                "media_refs": media_refs,
                "signer": self._signature_envelope(
                    evidence_bundle,
                    artifact_type="evidence_bundle",
                ),
                "created_at": created_at,
                "trust_proof": self._trust_proof_payload(evidence_bundle),
            },
        }

    def _normalize_disposition(self, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"allow", "deny", "quarantine", "escalate"}:
            return normalized
        return "deny"

    def _trust_proof_payload(self, payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        proof = payload.get("trust_proof")
        if not isinstance(proof, Mapping):
            return None
        return dict(proof)

    def _string_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        output: List[str] = []
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    output.append(candidate)
        return output

    def _artifact_hash_object(self, value: Any, *, fallback_seed: str) -> Dict[str, str]:
        if isinstance(value, Mapping):
            algorithm = str(value.get("algorithm") or "").strip()
            hash_value = str(value.get("value") or "").strip()
            if algorithm and hash_value:
                return {"algorithm": algorithm, "value": hash_value}
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                if ":" in candidate:
                    algorithm, hash_value = candidate.split(":", 1)
                    algorithm = algorithm.strip()
                    hash_value = hash_value.strip()
                    if algorithm and hash_value:
                        return {"algorithm": algorithm, "value": hash_value}
                return {"algorithm": "sha256", "value": candidate}
        return {"algorithm": "sha256", "value": hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()}

    def _signature_envelope(self, payload: Mapping[str, Any], *, artifact_type: str) -> Dict[str, Any]:
        metadata = payload.get("signer_metadata") if isinstance(payload.get("signer_metadata"), dict) else {}
        signature = payload.get("signature")
        signature_value = (
            str(signature).strip()
            if signature is not None and str(signature).strip()
            else f"sha256:{hashlib.sha256(f'{artifact_type}:signature'.encode('utf-8')).hexdigest()}"
        )
        key_ref_raw = metadata.get("key_ref")
        key_ref = str(key_ref_raw).strip() if isinstance(key_ref_raw, str) and key_ref_raw.strip() else None
        return {
            "signer_type": str(metadata.get("signer_type") or "service"),
            "signer_id": str(metadata.get("signer_id") or f"seedcore:{artifact_type}"),
            "signing_scheme": str(metadata.get("signing_scheme") or "debug_hash_v1"),
            "key_ref": key_ref,
            "attestation_level": str(metadata.get("attestation_level") or "baseline"),
            "signature": signature_value,
        }

    def _minted_artifact_refs(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        refs: List[str] = []
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    refs.append(candidate)
                continue
            if isinstance(item, dict):
                kind = str(item.get("kind") or "").strip()
                ref = str(item.get("ref") or "").strip()
                if kind and ref:
                    refs.append(f"{kind}:{ref}")
                elif ref:
                    refs.append(ref)
                elif kind:
                    refs.append(kind)
        return refs

    def _obligation_entries(self, value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        obligations: List[Dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            obligation_type = str(item.get("obligation_type") or item.get("code") or "").strip()
            if not obligation_type:
                continue
            reference = (
                str(item.get("reference")).strip()
                if item.get("reference") is not None and str(item.get("reference")).strip()
                else str(item.get("ref")).strip()
                if item.get("ref") is not None and str(item.get("ref")).strip()
                else None
            )
            details_raw = item.get("details")
            details = (
                {
                    str(key): str(val)
                    for key, val in details_raw.items()
                    if str(key).strip()
                }
                if isinstance(details_raw, dict)
                else {}
            )
            obligations.append(
                {
                    "obligation_type": obligation_type,
                    "reference": reference,
                    "details": details,
                }
            )
        return obligations

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
        approval_context = self._approval_context(replay)
        transition_head = (
            str(approval_context.get("approval_transition_head")).strip()
            if approval_context.get("approval_transition_head") is not None and str(approval_context.get("approval_transition_head")).strip()
            else None
        )
        transition_history = approval_context.get("approval_transition_history")
        if isinstance(transition_history, list):
            claims.append(
                {
                    "claim": "approval_transition_chain_available",
                    "value": bool(transition_history),
                    "source": transition_head or replay.audit_record_id,
                }
            )
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

    async def _cache_trust_bundle_snapshot(
        self,
        *,
        snapshot: Mapping[str, Any],
        promote_current: bool,
        redis_client: Any,
    ) -> None:
        setter = getattr(redis_client, "set", None)
        if not callable(setter):
            return
        bundle_id = self._optional_str(snapshot.get("bundle_id"))
        if not bundle_id:
            return
        payload = json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"))
        try:
            await setter(f"seedcore:trust_bundle:{bundle_id}", payload)
            if promote_current:
                await setter("seedcore:trust_bundle:current", bundle_id)
        except Exception:
            return

    def _persist_trust_bundle_snapshot(self, snapshot: Mapping[str, Any], *, promote_current: bool) -> None:
        bundle_id = self._optional_str(snapshot.get("bundle_id"))
        if not bundle_id:
            raise ReplayServiceError("invalid_trust_bundle", "Trust bundle snapshot is missing bundle_id")
        bundle_dir = self._trust_bundle_dir()
        bundle_dir.mkdir(parents=True, exist_ok=True)
        target = self._trust_bundle_snapshot_path(bundle_id)
        temp_path = target.with_suffix(f"{target.suffix}.tmp")
        payload = json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(target)
        if promote_current:
            current_payload = {
                "bundle_id": bundle_id,
                "published_at": snapshot.get("published_at"),
            }
            current_target = self._trust_bundle_current_pointer_path()
            current_tmp = current_target.with_suffix(f"{current_target.suffix}.tmp")
            current_tmp.write_text(
                json.dumps(current_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
            current_tmp.replace(current_target)

    def _load_trust_bundle_snapshot_from_disk(self, bundle_id: str) -> Optional[Dict[str, Any]]:
        path = self._trust_bundle_snapshot_path(bundle_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return dict(payload) if isinstance(payload, dict) else None

    def _load_current_trust_bundle_id_from_disk(self) -> Optional[str]:
        pointer_path = self._trust_bundle_current_pointer_path()
        if not pointer_path.exists():
            return None
        try:
            payload = json.loads(pointer_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return self._optional_str(payload.get("bundle_id"))

    def _trust_bundle_dir(self) -> Path:
        configured = os.getenv("SEEDCORE_TRUST_BUNDLE_DIR", "/tmp/seedcore-trust-bundles")
        return Path(configured).expanduser()

    def _trust_bundle_snapshot_path(self, bundle_id: str) -> Path:
        return self._trust_bundle_dir() / f"{bundle_id}.json"

    def _trust_bundle_current_pointer_path(self) -> Path:
        return self._trust_bundle_dir() / "current.json"

    def _iter_replay_artifacts_for_bundle(self, replay: ReplayRecord) -> List[Tuple[str, Mapping[str, Any]]]:
        artifacts: List[Tuple[str, Mapping[str, Any]]] = []
        if isinstance(replay.policy_receipt, Mapping) and replay.policy_receipt:
            artifacts.append(("policy_receipt", replay.policy_receipt))
        if isinstance(replay.evidence_bundle, Mapping) and replay.evidence_bundle:
            artifacts.append(("evidence_bundle", replay.evidence_bundle))
        for item in replay.transition_receipts:
            if isinstance(item, Mapping):
                artifacts.append(("transition_receipt", item))
        return artifacts

    def _configured_trust_key_registry(self) -> Dict[str, Dict[str, Any]]:
        entries: Dict[str, Dict[str, Any]] = {}
        for key_ref, value in self._load_json_object_env("SEEDCORE_TRUST_BUNDLE_KEYS_JSON").items():
            self._ingest_trust_registry_entry(entries, source_key=key_ref, raw_entry=value)
        for env_name in ("SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON", "SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON"):
            for key_ref, value in self._load_json_object_env(env_name).items():
                self._ingest_trust_registry_entry(entries, source_key=key_ref, raw_entry=value)

        tpm_key_ref = self._optional_str(os.getenv("SEEDCORE_TPM2_KEY_ID"))
        tpm_public_key = self._optional_str(os.getenv("SEEDCORE_TPM2_PUBLIC_KEY_B64"))
        if tpm_key_ref and tpm_public_key:
            entries[tpm_key_ref] = {
                **entries.get(tpm_key_ref, {}),
                "key_ref": tpm_key_ref,
                "public_key": tpm_public_key,
                "key_algorithm": entries.get(tpm_key_ref, {}).get("key_algorithm") or "ecdsa_p256_sha256",
                "trust_anchor_type": entries.get(tpm_key_ref, {}).get("trust_anchor_type") or "tpm2",
                "signer_profile": entries.get(tpm_key_ref, {}).get("signer_profile") or "receipt",
                "revocation_id": entries.get(tpm_key_ref, {}).get("revocation_id") or f"tpm2:{tpm_key_ref}",
                "endpoint_id": entries.get(tpm_key_ref, {}).get("endpoint_id") or self._optional_str(os.getenv("SEEDCORE_TPM2_ENDPOINT_ID")),
                "node_id": entries.get(tpm_key_ref, {}).get("node_id") or self._optional_str(os.getenv("SEEDCORE_TPM2_NODE_ID")),
                "attestation_root": entries.get(tpm_key_ref, {}).get("attestation_root") or self._optional_str(os.getenv("SEEDCORE_TPM2_AK_KEY_REF")),
                "metadata": dict(entries.get(tpm_key_ref, {}).get("metadata") or {}),
            }
        return entries

    def _ingest_trust_registry_entry(
        self,
        entries: Dict[str, Dict[str, Any]],
        *,
        source_key: str,
        raw_entry: Any,
    ) -> None:
        source_id = self._optional_str(source_key)
        if not source_id:
            return
        if isinstance(raw_entry, str):
            entries[source_id] = {
                **entries.get(source_id, {}),
                "key_ref": source_id,
                "public_key": raw_entry.strip(),
            }
            return
        if not isinstance(raw_entry, Mapping):
            return
        key_ref = (
            self._optional_str(raw_entry.get("key_ref"))
            or self._optional_str(raw_entry.get("key_id"))
            or source_id
        )
        if not key_ref:
            return
        entry = dict(entries.get(key_ref, {}))
        entry["key_ref"] = key_ref
        public_key = self._optional_str(raw_entry.get("public_key"))
        if public_key:
            entry["public_key"] = public_key
        for field in (
            "key_algorithm",
            "trust_anchor_type",
            "signer_profile",
            "endpoint_id",
            "node_id",
            "revocation_id",
            "attestation_root",
        ):
            value = self._optional_str(raw_entry.get(field))
            if value:
                entry[field] = value
        metadata = raw_entry.get("metadata")
        if isinstance(metadata, Mapping):
            entry["metadata"] = {str(key): value for key, value in metadata.items()}
        entries[key_ref] = entry

    def _artifact_endpoint_id(self, payload: Mapping[str, Any], trust_proof: Mapping[str, Any]) -> Optional[str]:
        attestation = trust_proof.get("attestation")
        if isinstance(attestation, Mapping):
            summary = attestation.get("summary")
            if isinstance(summary, Mapping):
                endpoint_id = self._optional_str(summary.get("endpoint_id"))
                if endpoint_id:
                    return endpoint_id
        return self._optional_str(payload.get("endpoint_id"))

    def _artifact_node_id(self, signer_metadata: Mapping[str, Any], trust_proof: Mapping[str, Any]) -> Optional[str]:
        attestation = trust_proof.get("attestation")
        if isinstance(attestation, Mapping):
            summary = attestation.get("summary")
            if isinstance(summary, Mapping):
                node_id = self._optional_str(summary.get("node_id"))
                if node_id:
                    return node_id
        return self._optional_str(signer_metadata.get("node_id"))

    def _signer_profile_for_artifact_type(self, artifact_type: str) -> str:
        if artifact_type == "policy_receipt":
            return "pdp"
        if artifact_type == "transition_receipt":
            return "receipt"
        return "execution"

    def _load_json_object_env(self, name: str) -> Dict[str, Any]:
        raw = os.getenv(name, "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _load_string_set_env(self, name: str) -> set[str]:
        raw = os.getenv(name, "").strip()
        if not raw:
            return set()
        try:
            payload = json.loads(raw)
        except Exception:
            return set()
        if not isinstance(payload, list):
            return set()
        return self._normalized_str_set(payload)

    def _normalized_str_set(self, values: Optional[Sequence[Any]]) -> set[str]:
        output: set[str] = set()
        for value in list(values or []):
            normalized = self._optional_str(value)
            if normalized:
                output.add(normalized)
        return output

    def _split_csv_env(self, name: str, *, default: Sequence[str]) -> List[str]:
        raw = os.getenv(name, "").strip()
        if not raw:
            return [item for item in default if item]
        values = [segment.strip() for segment in raw.split(",") if segment.strip()]
        return values or [item for item in default if item]

    def _optional_str(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        return None

    def _env_flag(self, name: str, *, default: bool = False) -> bool:
        raw = os.getenv(name, "true" if default else "false").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _trust_bundle_signing_secret(self) -> str:
        return (
            self._optional_str(os.getenv("SEEDCORE_TRUST_BUNDLE_SIGNING_SECRET"))
            or self._optional_str(os.getenv("SEEDCORE_TRUST_SIGNING_SECRET"))
            or self._optional_str(os.getenv("SEEDCORE_EVIDENCE_SIGNING_SECRET"))
            or "seedcore-dev-evidence-secret"
        )

    def _trust_bundle_signing_key_ref(self) -> str:
        return (
            self._optional_str(os.getenv("SEEDCORE_TRUST_BUNDLE_SIGNING_KEY_REF"))
            or "seedcore-trust-bundle-hmac"
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
