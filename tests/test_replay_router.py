from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import importlib
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import seedcore.api.routers.replay_router as replay_router_module
from seedcore.hal.custody.transition_receipts import (
    build_transition_receipt,
    verify_transition_receipt_result,
)
from seedcore.services.replay_service import ReplayService

sys.modules.pop("seedcore.api.routers.tasks_router", None)
tasks_router_module = importlib.import_module("seedcore.api.routers.tasks_router")

from test_replay_service import (
    _DummySession,
    _apply_transfer_workflow_metadata,
    _apply_transition_metadata,
    _build_audit_record,
)


class _FakeRedis:
    def __init__(self) -> None:
        self._values: Dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._values[key] = {"value": value, "ex": ex}
        return True

    async def aclose(self) -> None:
        return None


class _TaskGovernanceSession(_DummySession):
    def __init__(self, task: Any) -> None:
        self._task = task

    async def get(self, model, key):
        return self._task if getattr(self._task, "id", None) == key else None


def _build_service(record: Dict[str, Any]) -> ReplayService:
    return ReplayService(
        governance_audit_dao=type(
            "DAO",
            (),
            {
                "get_by_entry_id": AsyncMock(return_value=record),
                "get_latest_for_intent": AsyncMock(return_value=record),
                "get_latest_for_task": AsyncMock(return_value=record),
                "_mapping_to_dict": staticmethod(lambda row: dict(row)),
            },
        )(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-1", "current_zone": "vault-a"})})(),
    )


def _make_client(
    record: Dict[str, Any],
    redis_client: _FakeRedis | None = None,
    *,
    session: Any | None = None,
    governance_entries: list[Dict[str, Any]] | None = None,
    governance_search_entries: list[Dict[str, Any]] | None = None,
    governance_search_facets: Dict[str, Any] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(replay_router_module.router)
    app.include_router(tasks_router_module.router)

    session = session or _DummySession()

    async def override_replay_session():
        return session

    async def override_tasks_session():
        return session

    app.dependency_overrides[replay_router_module.get_async_pg_session] = override_replay_session
    app.dependency_overrides[tasks_router_module.get_async_pg_session] = override_tasks_session

    replay_router_module.replay_service = _build_service(record)
    tasks_router_module.replay_service = replay_router_module.replay_service
    tasks_router_module.governance_audit_dao = SimpleNamespace(
        list_for_task=AsyncMock(return_value=list(governance_entries or [record])),
        search_transition_records=AsyncMock(return_value=list(governance_search_entries or governance_entries or [record])),
        summarize_transition_records=AsyncMock(
            return_value=dict(
                governance_search_facets
                or {
                    "total": len(list(governance_search_entries or governance_entries or [record])),
                    "restricted_count": 1,
                    "dispositions": [{"value": "allow", "count": 0}, {"value": "deny", "count": 0}, {"value": "quarantine", "count": 1}],
                    "trust_gap_codes": [{"value": "stale_telemetry", "count": 1}],
                }
            )
        ),
    )

    async def fake_get_async_redis_client():
        return redis_client

    replay_router_module.get_async_redis_client = fake_get_async_redis_client
    return TestClient(app)


def test_publish_trust_reference_and_fetch_projection_and_verify() -> None:
    record = _build_audit_record(task_id="task-router-1", intent_id="intent-router-1", asset_id="asset-1")
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    assert publish.status_code == 200
    public_id = publish.json()["public_id"]

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 200
    assert trust.json()["subject_title"] == "Asset asset-1"
    assert trust.json()["public_jsonld_ref"].endswith(f"/trust/{public_id}/jsonld")

    certificate = client.get(f"/trust/{public_id}/certificate")
    assert certificate.status_code == 200
    certificate_body = certificate.json()
    assert certificate_body["public_id"] == public_id
    assert isinstance(certificate_body.get("trust_gap_codes"), list)
    assert isinstance(certificate_body.get("trust_gap_details"), list)
    assert isinstance(certificate_body.get("owner_context"), dict)

    verify = client.get(f"/verify/{public_id}")
    assert verify.status_code == 200
    assert verify.json()["verified"] is True
    assert verify.json()["trust_url"].endswith(f"/trust/{public_id}")


def test_replay_lookup_by_subject_id_returns_asset_projection() -> None:
    record = _build_audit_record(task_id="task-router-subject-1", intent_id="intent-router-subject-1", asset_id="asset-lookup-1")
    class _AssetLookupResult:
        def __init__(self, row: Dict[str, Any]) -> None:
            self._row = row

        def mappings(self):
            return self

        def one_or_none(self):
            return self._row

    class _AssetLookupSession(_DummySession):
        def __init__(self, row: Dict[str, Any]) -> None:
            self._row = row

        async def execute(self, *args, **kwargs):
            return _AssetLookupResult(self._row)

    client = _make_client(record, session=_AssetLookupSession(record))

    replay = client.get("/replay", params={"subject_id": "asset-lookup-1", "subject_type": "asset", "projection": "internal"})
    assert replay.status_code == 200
    body = replay.json()
    assert body["lookup_key"] == "subject_id"
    assert body["lookup_value"] == "asset-lookup-1"
    assert body["view"]["subject_id"] == "asset-lookup-1"


def test_revoke_trust_reference_returns_gone_for_trust_surface() -> None:
    record = _build_audit_record(task_id="task-router-2", intent_id="intent-router-2", asset_id="asset-1")
    redis_client = _FakeRedis()
    client = _make_client(record, redis_client=redis_client)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    public_id = publish.json()["public_id"]

    revoke = client.post("/trust/revoke", json={"public_id": public_id})
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 410

    verify = client.get(f"/verify/{public_id}")
    assert verify.status_code == 200
    assert verify.json()["verified"] is False
    assert verify.json()["reason"] == "revoked_reference"


def test_publish_trust_bundle_from_env_registry_and_fetch_current() -> None:
    record = _build_audit_record(task_id="task-router-bundle-1", intent_id="intent-router-bundle-1", asset_id="asset-1")
    redis_client = _FakeRedis()
    client = _make_client(record, redis_client=redis_client)
    bundle_keys = {
        "tpm-phase-a-key-01": {
            "key_ref": "tpm-phase-a-key-01",
            "key_algorithm": "ecdsa_p256_sha256",
            "public_key": "BD2Ln1bf8fbp5LMDFFuNjKDNPw29UyTJ1PK3QkwlRRnXGtA+3PXiA0EUtdLWlylqxGt6fTQ8bpcAmVhO8pl09LU=",
            "trust_anchor_type": "tpm2",
            "signer_profile": "receipt",
            "endpoint_id": "hal://phase-a-edge-01",
            "node_id": "hal://phase-a-edge-01",
            "revocation_id": "tpm2:tpm-phase-a-key-01",
            "attestation_root": "ak-phase-a-01",
        }
    }
    old_dir = os.getenv("SEEDCORE_TRUST_BUNDLE_DIR")
    old_keys = os.getenv("SEEDCORE_TRUST_BUNDLE_KEYS_JSON")
    with tempfile.TemporaryDirectory(prefix="seedcore-trust-bundle-") as tmpdir:
        os.environ["SEEDCORE_TRUST_BUNDLE_DIR"] = tmpdir
        os.environ["SEEDCORE_TRUST_BUNDLE_KEYS_JSON"] = json.dumps(bundle_keys)
        try:
            publish = client.post("/trust/bundles/publish", json={"bundle_version": "phase_a_v1"})
            assert publish.status_code == 200
            body = publish.json()
            assert body["bundle_id"].startswith("tb-")
            assert isinstance(body.get("payload_hash"), str) and body["payload_hash"]
            assert isinstance(body.get("signature_envelope"), dict)
            assert body["signature_envelope"]["signature"]
            trusted = body["trust_bundle"]["trusted_keys"]["tpm-phase-a-key-01"]
            assert trusted["trust_anchor_type"] == "tpm2"
            assert trusted["endpoint_id"] == "hal://phase-a-edge-01"

            current = client.get("/trust/bundles/current")
            assert current.status_code == 200
            assert current.json()["bundle_id"] == body["bundle_id"]
            assert current.json()["signature_envelope"]["signature"] == body["signature_envelope"]["signature"]

            current_signed = client.get("/trust/bundles/current/signed")
            assert current_signed.status_code == 200
            assert current_signed.json()["bundle_id"] == body["bundle_id"]

            by_id = client.get(f"/trust/bundles/{body['bundle_id']}")
            assert by_id.status_code == 200
            assert by_id.json()["bundle_id"] == body["bundle_id"]
            by_id_signed = client.get(f"/trust/bundles/{body['bundle_id']}/signed")
            assert by_id_signed.status_code == 200
            assert by_id_signed.json()["bundle_id"] == body["bundle_id"]
        finally:
            if old_dir is None:
                os.environ.pop("SEEDCORE_TRUST_BUNDLE_DIR", None)
            else:
                os.environ["SEEDCORE_TRUST_BUNDLE_DIR"] = old_dir
            if old_keys is None:
                os.environ.pop("SEEDCORE_TRUST_BUNDLE_KEYS_JSON", None)
            else:
                os.environ["SEEDCORE_TRUST_BUNDLE_KEYS_JSON"] = old_keys


def test_rotate_trust_bundle_promotes_new_snapshot_and_preserves_prior_snapshot() -> None:
    record = _build_audit_record(task_id="task-router-bundle-2", intent_id="intent-router-bundle-2", asset_id="asset-1")
    redis_client = _FakeRedis()
    client = _make_client(record, redis_client=redis_client)
    bundle_keys = {
        "tpm-phase-a-key-02": {
            "key_ref": "tpm-phase-a-key-02",
            "key_algorithm": "ecdsa_p256_sha256",
            "public_key": "BD2Ln1bf8fbp5LMDFFuNjKDNPw29UyTJ1PK3QkwlRRnXGtA+3PXiA0EUtdLWlylqxGt6fTQ8bpcAmVhO8pl09LU=",
            "trust_anchor_type": "tpm2",
        }
    }
    old_dir = os.getenv("SEEDCORE_TRUST_BUNDLE_DIR")
    old_keys = os.getenv("SEEDCORE_TRUST_BUNDLE_KEYS_JSON")
    with tempfile.TemporaryDirectory(prefix="seedcore-trust-bundle-rotate-") as tmpdir:
        os.environ["SEEDCORE_TRUST_BUNDLE_DIR"] = tmpdir
        os.environ["SEEDCORE_TRUST_BUNDLE_KEYS_JSON"] = json.dumps(bundle_keys)
        try:
            first = client.post(
                "/trust/bundles/publish",
                json={"bundle_version": "phase_a_v1", "revoked_keys": ["legacy-key-01"]},
            )
            assert first.status_code == 200
            first_id = first.json()["bundle_id"]
            assert "legacy-key-01" in first.json()["trust_bundle"]["revoked_keys"]

            rotated = client.post(
                "/trust/bundles/rotate",
                json={"bundle_version": "phase_a_v2", "revoked_keys": ["tpm-phase-a-key-02"]},
            )
            assert rotated.status_code == 200
            rotated_id = rotated.json()["bundle_id"]
            assert rotated_id != first_id

            current = client.get("/trust/bundles/current")
            assert current.status_code == 200
            assert current.json()["bundle_id"] == rotated_id
            assert "tpm-phase-a-key-02" in current.json()["trust_bundle"]["revoked_keys"]
            assert current.json()["payload_hash"]
            assert current.json()["signature_envelope"]["signature"]

            first_snapshot = client.get(f"/trust/bundles/{first_id}")
            assert first_snapshot.status_code == 200
            assert "legacy-key-01" in first_snapshot.json()["trust_bundle"]["revoked_keys"]
        finally:
            if old_dir is None:
                os.environ.pop("SEEDCORE_TRUST_BUNDLE_DIR", None)
            else:
                os.environ["SEEDCORE_TRUST_BUNDLE_DIR"] = old_dir
            if old_keys is None:
                os.environ.pop("SEEDCORE_TRUST_BUNDLE_KEYS_JSON", None)
            else:
                os.environ["SEEDCORE_TRUST_BUNDLE_KEYS_JSON"] = old_keys


def test_ops_closure_drill_rejects_stolen_node_after_bundle_rotation() -> None:
    record = _build_audit_record(
        task_id="task-router-bundle-drill-1",
        intent_id="intent-router-bundle-drill-1",
        asset_id="asset-1",
    )
    redis_client = _FakeRedis()
    client = _make_client(record, redis_client=redis_client)
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    ).decode("ascii")
    endpoint_id = "hal://stolen-node-01"
    key_ref = "tpm-stolen-node-k1"

    old_env = {name: os.getenv(name) for name in (
        "SEEDCORE_TRUST_BUNDLE_DIR",
        "SEEDCORE_TRUST_BUNDLE_KEYS_JSON",
        "SEEDCORE_SIGNER_PROVIDER_RECEIPT",
        "SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR",
        "SEEDCORE_TPM2_REQUIRE_HARDWARE",
        "SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK",
        "SEEDCORE_TPM2_KEY_ID",
        "SEEDCORE_TPM2_PUBLIC_KEY_B64",
        "SEEDCORE_TPM2_SOFTWARE_FALLBACK_PRIVATE_KEY_PEM",
        "SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON",
        "SEEDCORE_TRUST_REVOKED_KEY_REFS_JSON",
        "SEEDCORE_TRUST_REVOKED_NODE_IDS_JSON",
        "SEEDCORE_TRUST_REVOKED_REVOCATION_IDS_JSON",
        "SEEDCORE_TRUST_REVOKED_BEFORE_JSON",
    )}
    with tempfile.TemporaryDirectory(prefix="seedcore-trust-bundle-drill-") as tmpdir:
        os.environ["SEEDCORE_TRUST_BUNDLE_DIR"] = tmpdir
        os.environ["SEEDCORE_TRUST_BUNDLE_KEYS_JSON"] = json.dumps({
            key_ref: {
                "key_ref": key_ref,
                "key_algorithm": "ecdsa_p256_sha256",
                "public_key": public_b64,
                "trust_anchor_type": "tpm2",
                "signer_profile": "receipt",
                "endpoint_id": endpoint_id,
                "node_id": endpoint_id,
                "revocation_id": f"tpm2:{key_ref}",
                "attestation_root": "ak-drill-01",
            }
        })
        os.environ["SEEDCORE_SIGNER_PROVIDER_RECEIPT"] = "tpm2"
        os.environ["SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR"] = "tpm2"
        os.environ["SEEDCORE_TPM2_REQUIRE_HARDWARE"] = "false"
        os.environ["SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK"] = "true"
        os.environ["SEEDCORE_TPM2_KEY_ID"] = key_ref
        os.environ["SEEDCORE_TPM2_PUBLIC_KEY_B64"] = public_b64
        os.environ["SEEDCORE_TPM2_SOFTWARE_FALLBACK_PRIVATE_KEY_PEM"] = private_pem
        os.environ["SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON"] = json.dumps({key_ref: {"public_key": public_b64}})

        try:
            receipt = build_transition_receipt(
                intent_id="intent-drill-01",
                token_id="token-drill-01",
                actuator_endpoint=endpoint_id,
                hardware_uuid="edge-drill-01",
                actuator_result_hash="hash-drill-01",
                from_zone="vault_a",
                to_zone="handoff_bay_9",
                workflow_type="custody_transfer",
            )
            pre_result = verify_transition_receipt_result(receipt)
            assert pre_result["verified"] is True

            publish = client.post("/trust/bundles/publish", json={"bundle_version": "phase_a_v1"})
            assert publish.status_code == 200
            rotate = client.post(
                "/trust/bundles/rotate",
                json={"bundle_version": "phase_a_v1", "revoked_nodes": [endpoint_id]},
            )
            assert rotate.status_code == 200
            rotated_bundle = rotate.json()["trust_bundle"]

            os.environ["SEEDCORE_TRUST_REVOKED_KEY_REFS_JSON"] = json.dumps(rotated_bundle.get("revoked_keys") or [])
            os.environ["SEEDCORE_TRUST_REVOKED_NODE_IDS_JSON"] = json.dumps(rotated_bundle.get("revoked_nodes") or [])
            os.environ["SEEDCORE_TRUST_REVOKED_REVOCATION_IDS_JSON"] = json.dumps([])
            os.environ["SEEDCORE_TRUST_REVOKED_BEFORE_JSON"] = json.dumps(rotated_bundle.get("revocation_cutoffs") or {})
            post_result = verify_transition_receipt_result(receipt)
            assert post_result["verified"] is False
            assert post_result["error"] == "revoked_signer"
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_verify_post_requires_exactly_one_lookup() -> None:
    record = _build_audit_record(task_id="task-router-3", intent_id="intent-router-3", asset_id="asset-1")
    client = _make_client(record)

    response = client.post("/verify", json={"audit_id": record["id"], "subject_id": "asset-1"})

    assert response.status_code == 422
    assert "exactly one" in response.json()["detail"]


def test_verify_by_audit_id_surfaces_owner_identity_mismatch() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(
            task_id="task-router-owner-mismatch-1",
            intent_id="intent-router-owner-mismatch-1",
            asset_id="asset-owner-mismatch-1",
        ),
        disposition="allow",
        reason="restricted_custody_transfer",
        trust_gap_codes=[],
    )
    record["action_intent"] = {
        "intent_id": "intent-router-owner-mismatch-1",
        "principal": {
            "agent_id": "did:seedcore:assistant:warehouse-bot-01",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
        },
        "action": {
            "type": "TRANSFER_CUSTODY",
            "parameters": {
                "gateway": {
                    "owner_id": "did:seedcore:owner:acme-001",
                    "delegation_ref": "delegation:owner-8841-transfer",
                }
            },
        },
    }
    record["policy_decision"]["governed_receipt"]["owner_context"] = {
        "owner_id": "did:seedcore:owner:other-999",
        "creator_profile_ref": {"owner_id": "did:seedcore:owner:other-999", "version": "v2"},
        "trust_preferences_ref": {"owner_id": "did:seedcore:owner:other-999", "trust_version": "v1"},
    }
    client = _make_client(record)

    response = client.post("/verify", json={"audit_id": record["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["verified"] is False
    assert body["reason"] == "owner_identity_mismatch"
    assert body["tamper_status"] == "authority_mismatch"


def test_materialized_custody_event_endpoint_uses_replay_service_jsonld() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-router-4", intent_id="intent-router-4", asset_id="asset-1")
    )
    client = _make_client(record)

    response = client.get("/governance/materialized-custody-event", params={"audit_id": record["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieval_key"] == "audit_id"
    assert body["audit_record"]["id"] == record["id"]
    assert body["custody_event_jsonld"]["@type"] == "seedcore:SeedCoreCustodyEvent"
    assert body["custody_event_jsonld"]["proof"]["type"] == "SeedCoreReplayProof"
    assert body["custody_event_jsonld"]["policy_verification"]["authz_disposition"] == "quarantine"
    assert body["custody_event_jsonld"]["policy_verification"]["governed_receipt_hash"] == "receipt-intent-router-4"
    assert body["custody_event_jsonld"]["policy_verification"]["trust_gap_codes"] == ["stale_telemetry"]


def test_replay_artifacts_include_authz_transition_metadata() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-router-5", intent_id="intent-router-5", asset_id="asset-1")
    )
    client = _make_client(record)

    response = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "internal"})

    assert response.status_code == 200
    body = response.json()
    assert body["authz_graph"]["reason"] == "trust_gap_quarantine"
    assert body["governed_receipt"]["decision_hash"] == "receipt-intent-router-5"
    assert body["governed_receipt"]["trust_gap_codes"] == ["stale_telemetry"]


def test_replay_artifacts_include_approval_transition_chain_for_transfer_flow() -> None:
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(
            task_id="task-router-transfer-chain-1",
            intent_id="intent-router-transfer-chain-1",
            asset_id="asset-transfer-chain-1",
        ),
        disposition="allow",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001", "principal:quality_insp_017"],
        approval_transition_history=[
            {
                "event_id": "approval-transition-event:sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72",
                "event_hash": "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72",
                "previous_event_hash": None,
                "occurred_at": "2026-04-02T08:00:30Z",
                "transition_type": "add_approval",
                "envelope_id": "approval-transfer-001",
                "previous_status": "PARTIALLY_APPROVED",
                "next_status": "APPROVED",
                "previous_binding_hash": None,
                "next_binding_hash": "sha256:fd6236849fc43a3d10c071da4a211964f652dcf83a91cf6a258cd6e3aabc4f9c",
                "envelope_version": 2,
            }
        ],
    )
    client = _make_client(record)

    internal = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "internal"})
    assert internal.status_code == 200
    internal_body = internal.json()
    assert internal_body["approval_transition_chain"]["count"] == 1
    assert internal_body["approval_transition_chain"]["head"] == "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72"
    assert internal_body["approval_transition_chain"]["events"][0]["previous_status"] == "PARTIALLY_APPROVED"

    public = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "public"})
    assert public.status_code == 200
    public_chain = public.json()["public_artifacts"]["approval_transition_chain"]
    assert public_chain["count"] == 1
    assert public_chain["head"] == "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72"
    assert "previous_status" not in public_chain["events"][0]


def test_trust_surface_exposes_pending_approval_status_for_transfer_flow() -> None:
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(task_id="task-router-transfer-1", intent_id="intent-router-transfer-1", asset_id="asset-transfer-1"),
        disposition="escalate",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001"],
    )
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    assert publish.status_code == 200
    public_id = publish.json()["public_id"]

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 200
    body = trust.json()
    assert body["workflow_type"] == "custody_transfer"
    assert body["status"] == "pending_approval"
    assert body["approvals"]["required"] == ["FACILITY_MANAGER", "QUALITY_INSPECTOR"]


def test_task_governance_endpoint_exposes_authz_transition_summary() -> None:
    task_id = uuid.UUID("00000000-0000-0000-0000-0000000000f5")
    record = _apply_transition_metadata(
        _build_audit_record(task_id=str(task_id), intent_id="intent-router-6", asset_id="asset-1")
    )
    session = _TaskGovernanceSession(task=SimpleNamespace(id=task_id, result=None))
    client = _make_client(record, session=session, governance_entries=[record])

    response = client.get(f"/tasks/{task_id}/governance")

    assert response.status_code == 200
    body = response.json()
    assert body["latest"]["authz_transition_summary"]["reason"] == "trust_gap_quarantine"
    assert body["latest"]["authz_transition_summary"]["governed_receipt_hash"] == "receipt-intent-router-6"
    assert body["entries"][0]["authz_transition_summary"]["trust_gap_codes"] == ["stale_telemetry"]


def test_governance_search_filters_quarantine_and_trust_gap_records() -> None:
    quarantine = _apply_transition_metadata(
        _build_audit_record(task_id="task-router-7", intent_id="intent-router-7", asset_id="asset-q-1"),
        disposition="quarantine",
        reason="trust_gap_quarantine",
        trust_gap_codes=["stale_telemetry"],
    )
    client = _make_client(
        quarantine,
        governance_search_entries=[quarantine],
    )

    response = client.get(
        "/governance/search",
        params={"disposition": "quarantine", "trust_gap_code": "stale_telemetry", "current_only": "true"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["facets"]["restricted_count"] == 1
    assert body["facets"]["dispositions"][-1] == {"value": "quarantine", "count": 1}
    assert body["facets"]["trust_gap_codes"] == [{"value": "stale_telemetry", "count": 1}]
    assert body["items"][0]["authz_transition_summary"]["governed_receipt_hash"] == "receipt-intent-router-7"
    assert body["items"][0]["authz_transition_summary"]["trust_gap_codes"] == ["stale_telemetry"]

    dao = tasks_router_module.governance_audit_dao
    dao.search_transition_records.assert_awaited_once()
    dao.summarize_transition_records.assert_awaited_once()
    _, kwargs = dao.search_transition_records.await_args
    assert kwargs["disposition"] == "quarantine"
    assert kwargs["trust_gap_code"] == "stale_telemetry"
    assert kwargs["current_only"] is True
    _, facet_kwargs = dao.summarize_transition_records.await_args
    assert facet_kwargs["disposition"] == "quarantine"
    assert facet_kwargs["trust_gap_code"] == "stale_telemetry"
    assert facet_kwargs["current_only"] is True


def test_governance_search_rejects_invalid_disposition() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-router-9", intent_id="intent-router-9", asset_id="asset-1")
    )
    client = _make_client(record)

    response = client.get("/governance/search", params={"disposition": "blocked"})

    assert response.status_code == 422
    assert "disposition" in response.json()["detail"]
