from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from seedcore.database import get_async_pg_session_factory
from seedcore.coordinator.metrics.registry import get_global_metrics_tracker
from seedcore.coordinator.dao import (
    AssetCustodyStateDAO,
    CustodyDisputeDAO,
    CustodyGraphDAO,
    CustodyTransitionDAO,
    DigitalTwinDAO,
)
from seedcore.services.digital_twin_service import DigitalTwinService


DISPUTE_STATUSES = {"OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"}
ACTIVE_DISPUTE_STATUSES = {"OPEN", "UNDER_REVIEW"}


class CustodyGraphService:
    def __init__(
        self,
        *,
        session_factory: Any = None,
        transition_dao: Optional[CustodyTransitionDAO] = None,
        graph_dao: Optional[CustodyGraphDAO] = None,
        dispute_dao: Optional[CustodyDisputeDAO] = None,
        asset_custody_dao: Optional[AssetCustodyStateDAO] = None,
        digital_twin_dao: Optional[DigitalTwinDAO] = None,
        metrics_tracker: Any = None,
        clock: Optional[Callable[[], datetime]] = None,
        id_generator: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._transition_dao = transition_dao or CustodyTransitionDAO()
        self._graph_dao = graph_dao or CustodyGraphDAO()
        self._dispute_dao = dispute_dao or CustodyDisputeDAO()
        self._asset_custody_dao = asset_custody_dao or AssetCustodyStateDAO()
        self._digital_twin_dao = digital_twin_dao or DigitalTwinDAO()
        self._metrics = metrics_tracker or get_global_metrics_tracker()
        self._clock = clock
        self._id_generator = id_generator
        self._digital_twin_service = DigitalTwinService(
            session_factory=session_factory or get_async_pg_session_factory(),
            dao=self._digital_twin_dao,
        )

    async def record_governed_transition(
        self,
        session,
        *,
        record: Mapping[str, Any],
        governance_ctx: Mapping[str, Any],
        custody_update: Mapping[str, Any] | None,
    ) -> Optional[Dict[str, Any]]:
        transition_event = self._build_transition_event(record=record, governance_ctx=governance_ctx, custody_update=custody_update)
        if transition_event is None:
            return None
        prior = await self._transition_dao.get_latest_for_asset(session, asset_id=transition_event["asset_id"])
        transition_event["previous_transition_event_id"] = prior.get("transition_event_id") if prior else None
        transition_event["previous_receipt_hash"] = prior.get("receipt_hash") if prior else None
        persisted = await self._transition_dao.append_transition_event(session, **transition_event)
        projection = await self.project_transition(session, transition_event=persisted, record=record, governance_ctx=governance_ctx)
        return {
            "transition_event": persisted,
            "projection": projection,
        }

    async def project_transition(
        self,
        session,
        *,
        transition_event: Mapping[str, Any],
        record: Mapping[str, Any],
        governance_ctx: Mapping[str, Any],
    ) -> Dict[str, Any]:
        action_intent = governance_ctx.get("action_intent") if isinstance(governance_ctx.get("action_intent"), Mapping) else {}
        resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), Mapping) else {}
        principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), Mapping) else {}
        evidence_bundle = record.get("evidence_bundle") if isinstance(record.get("evidence_bundle"), Mapping) else {}
        policy_receipt = governance_ctx.get("policy_receipt") if isinstance(governance_ctx.get("policy_receipt"), Mapping) else {}

        asset_node_id = self.node_id("asset", transition_event["asset_id"])
        base_projection = self._transition_core_projection(transition_event)
        persisted_projection = await self._persist_projection(session, projection=base_projection)
        touched_nodes = set(persisted_projection["node_ids"])
        touched_edges: List[Dict[str, Any]] = list(persisted_projection["edges"])

        if principal.get("owner_id"):
            owner_node = self.node_id("owner", principal["owner_id"])
            touched_nodes.add(owner_node)
            await self._graph_dao.upsert_node(
                session,
                node_id=owner_node,
                node_kind="owner",
                subject_id=str(principal["owner_id"]),
                payload={"owner_id": principal["owner_id"]},
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("OWNED_BY", transition_event["asset_id"], principal["owner_id"]),
                    edge_kind="OWNED_BY",
                    from_node_id=asset_node_id,
                    to_node_id=owner_node,
                    source_ref=transition_event["transition_event_id"],
                    payload={},
                )
            )

        if principal.get("agent_id"):
            assistant_node = self.node_id("assistant", principal["agent_id"])
            touched_nodes.add(assistant_node)
            await self._graph_dao.upsert_node(
                session,
                node_id=assistant_node,
                node_kind="assistant",
                subject_id=str(principal["agent_id"]),
                payload={"agent_id": principal["agent_id"]},
            )
            if principal.get("owner_id"):
                touched_edges.append(
                    await self._graph_dao.append_edge(
                        session,
                        edge_id=self.edge_id("DELEGATED_TO", principal["owner_id"], principal["agent_id"]),
                        edge_kind="DELEGATED_TO",
                        from_node_id=self.node_id("owner", principal["owner_id"]),
                        to_node_id=assistant_node,
                        source_ref=transition_event["transition_event_id"],
                        payload={},
                    )
                )

        twin_refs = await self._load_twin_refs(
            session,
            asset_id=transition_event["asset_id"],
            intent_id=transition_event.get("intent_id"),
        )
        for twin_ref in twin_refs:
            node_id = self.node_id("digital_twin_revision", twin_ref["id"])
            touched_nodes.add(node_id)
            await self._graph_dao.upsert_node(
                session,
                node_id=node_id,
                node_kind="digital_twin_revision",
                subject_id=twin_ref["id"],
                payload=twin_ref,
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("DERIVED_FROM", transition_event["transition_event_id"], twin_ref["id"]),
                    edge_kind="DERIVED_FROM",
                    from_node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
                    to_node_id=node_id,
                    source_ref=transition_event["transition_event_id"],
                    payload={"twin_type": twin_ref.get("twin_type")},
                )
            )

        if isinstance(evidence_bundle.get("evidence_bundle_id"), str) and isinstance(policy_receipt.get("policy_receipt_id"), str):
            touched_nodes.add(self.node_id("evidence_bundle", evidence_bundle["evidence_bundle_id"]))

        return {
            "node_ids": sorted(touched_nodes),
            "edges": touched_edges,
        }

    async def get_asset_transitions(self, session, *, asset_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        transitions = await self._transition_dao.list_for_asset(session, asset_id=asset_id, limit=limit)
        dispute_map = await self._dispute_map_for_asset(session, asset_id=asset_id)
        return [self._attach_disputes(item, dispute_map) for item in transitions]

    async def get_asset_lineage(self, session, *, asset_id: str, limit: int = 100) -> Dict[str, Any]:
        transitions = await self.get_asset_transitions(session, asset_id=asset_id, limit=limit)
        twin_refs = await self._linked_twin_refs(session, asset_id=asset_id)
        artifacts = [
            {
                "transition_event_id": item["transition_event_id"],
                "intent_id": item.get("intent_id"),
                "token_id": item.get("token_id"),
                "evidence_bundle_id": item.get("evidence_bundle_id"),
                "policy_receipt_id": item.get("policy_receipt_id"),
                "transition_receipt_id": item.get("transition_receipt_id"),
                "audit_record_id": item.get("audit_record_id"),
            }
            for item in transitions
        ]
        return {
            "asset_id": asset_id,
            "transition_count": len(transitions),
            "transitions": transitions,
            "artifacts": artifacts,
            "twin_refs": twin_refs,
        }

    async def get_asset_graph(self, session, *, asset_id: str, limit: int = 100) -> Dict[str, Any]:
        transitions = await self._transition_dao.list_for_asset(session, asset_id=asset_id, limit=limit)
        twin_refs = await self._linked_twin_refs(session, asset_id=asset_id)
        node_ids = {
            self.node_id("asset", asset_id),
            *[self.node_id("transition_event", item["transition_event_id"]) for item in transitions],
        }
        for item in transitions:
            for kind, value in (
                ("zone", item.get("from_zone")),
                ("zone", item.get("to_zone")),
                ("intent", item.get("intent_id")),
                ("task", item.get("task_id")),
                ("execution_token", item.get("token_id")),
                ("evidence_bundle", item.get("evidence_bundle_id")),
                ("transition_receipt", item.get("transition_receipt_id")),
                ("source_registration", item.get("source_registration_id")),
            ):
                if value:
                    node_ids.add(self.node_id(kind, value))
        disputes = await self._dispute_dao.list_cases(session, asset_id=asset_id, limit=limit)
        for dispute in disputes:
            node_ids.add(self.node_id("dispute_case", dispute["dispute_id"]))
        nodes = await self._graph_dao.list_nodes(session, node_ids=sorted(node_ids))
        edges = await self._graph_dao.list_edges_for_nodes(session, node_ids=sorted(node_ids))
        return {
            "root_node_id": self.node_id("asset", asset_id),
            "nodes": nodes,
            "edges": edges,
            "twin_refs": twin_refs,
        }

    async def scan_asset_integrity(self, session, *, asset_id: str, limit: int = 500) -> Dict[str, Any]:
        transitions = await self._transition_dao.list_for_asset(session, asset_id=asset_id, limit=limit)
        asset_state = await self._asset_custody_dao.get_snapshot(session, asset_id=asset_id)
        issues: List[Dict[str, Any]] = []
        previous: Optional[Mapping[str, Any]] = None

        for index, transition in enumerate(transitions):
            seq = int(transition.get("transition_seq") or 0)
            if previous is None:
                if transition.get("previous_transition_event_id"):
                    issues.append(
                        {
                            "code": "unexpected_previous_transition_ref",
                            "transition_event_id": transition.get("transition_event_id"),
                            "expected": None,
                            "actual": transition.get("previous_transition_event_id"),
                        }
                    )
                if transition.get("previous_receipt_hash"):
                    issues.append(
                        {
                            "code": "unexpected_previous_receipt_hash",
                            "transition_event_id": transition.get("transition_event_id"),
                            "expected": None,
                            "actual": transition.get("previous_receipt_hash"),
                        }
                    )
            else:
                previous_seq = int(previous.get("transition_seq") or 0)
                if seq <= previous_seq:
                    issues.append(
                        {
                            "code": "non_monotonic_transition_seq",
                            "transition_event_id": transition.get("transition_event_id"),
                            "previous_transition_event_id": previous.get("transition_event_id"),
                            "previous_seq": previous_seq,
                            "actual_seq": seq,
                        }
                    )
                if seq != previous_seq + 1:
                    issues.append(
                        {
                            "code": "transition_seq_gap",
                            "transition_event_id": transition.get("transition_event_id"),
                            "previous_transition_event_id": previous.get("transition_event_id"),
                            "expected_seq": previous_seq + 1,
                            "actual_seq": seq,
                        }
                    )
                if transition.get("previous_transition_event_id") != previous.get("transition_event_id"):
                    issues.append(
                        {
                            "code": "previous_transition_mismatch",
                            "transition_event_id": transition.get("transition_event_id"),
                            "expected": previous.get("transition_event_id"),
                            "actual": transition.get("previous_transition_event_id"),
                        }
                    )
                if self._normalized_value(transition.get("previous_receipt_hash")) != self._normalized_value(previous.get("receipt_hash")):
                    issues.append(
                        {
                            "code": "previous_receipt_hash_mismatch",
                            "transition_event_id": transition.get("transition_event_id"),
                            "expected": previous.get("receipt_hash"),
                            "actual": transition.get("previous_receipt_hash"),
                        }
                    )
                previous_counter = previous.get("receipt_counter")
                current_counter = transition.get("receipt_counter")
                if previous_counter is not None and current_counter is not None and int(current_counter) <= int(previous_counter):
                    issues.append(
                        {
                            "code": "receipt_counter_not_increasing",
                            "transition_event_id": transition.get("transition_event_id"),
                            "previous_transition_event_id": previous.get("transition_event_id"),
                            "previous_counter": previous_counter,
                            "actual_counter": current_counter,
                        }
                    )
                previous_zone = previous.get("to_zone")
                current_from_zone = transition.get("from_zone")
                if previous_zone and current_from_zone and str(previous_zone) != str(current_from_zone):
                    issues.append(
                        {
                            "code": "zone_continuity_mismatch",
                            "transition_event_id": transition.get("transition_event_id"),
                            "previous_transition_event_id": previous.get("transition_event_id"),
                            "expected_from_zone": previous_zone,
                            "actual_from_zone": current_from_zone,
                        }
                    )
            previous = transition

        latest = transitions[-1] if transitions else None
        if latest is not None and asset_state is not None:
            if int(asset_state.get("last_transition_seq") or 0) != int(latest.get("transition_seq") or 0):
                issues.append(
                    {
                        "code": "asset_state_transition_seq_mismatch",
                        "expected": latest.get("transition_seq"),
                        "actual": asset_state.get("last_transition_seq"),
                    }
                )
            if self._normalized_value(asset_state.get("last_receipt_hash")) != self._normalized_value(latest.get("receipt_hash")):
                issues.append(
                    {
                        "code": "asset_state_receipt_hash_mismatch",
                        "expected": latest.get("receipt_hash"),
                        "actual": asset_state.get("last_receipt_hash"),
                    }
                )
            if self._normalized_value(asset_state.get("current_zone")) != self._normalized_value(latest.get("to_zone")):
                issues.append(
                    {
                        "code": "asset_state_zone_mismatch",
                        "expected": latest.get("to_zone"),
                        "actual": asset_state.get("current_zone"),
                    }
                )

        report = {
            "asset_id": asset_id,
            "transition_count": len(transitions),
            "verified": not issues,
            "issues": issues,
            "latest_transition_event_id": latest.get("transition_event_id") if isinstance(latest, Mapping) else None,
            "latest_transition_seq": latest.get("transition_seq") if isinstance(latest, Mapping) else None,
            "asset_custody_state": asset_state,
        }
        self._record_integrity_metrics(report)
        return report

    async def reconcile_asset_projection(
        self,
        session,
        *,
        asset_id: str,
        limit: int = 500,
        repair: bool = False,
    ) -> Dict[str, Any]:
        transitions = await self._transition_dao.list_for_asset(session, asset_id=asset_id, limit=limit)
        disputes = await self._dispute_dao.list_cases(session, asset_id=asset_id, limit=limit)
        asset_state = await self._asset_custody_dao.get_snapshot(session, asset_id=asset_id)

        expected_projection = self._asset_projection(
            asset_id=asset_id,
            transitions=transitions,
            disputes=disputes,
            asset_state=asset_state,
        )
        node_ids = sorted(expected_projection["nodes"])
        existing_nodes = {
            item["node_id"]: item for item in await self._graph_dao.list_nodes(session, node_ids=node_ids)
        }
        existing_edges = {
            item["edge_id"]: item for item in await self._graph_dao.list_edges_for_nodes(session, node_ids=node_ids)
        }
        issues: List[Dict[str, Any]] = []

        for node_id, expected in expected_projection["nodes"].items():
            actual = existing_nodes.get(node_id)
            if actual is None:
                issues.append(
                    {
                        "code": "missing_node",
                        "node_id": node_id,
                        "node_kind": expected.get("node_kind"),
                    }
                )
                continue
            drift = self._payload_drift(expected.get("payload"), actual.get("payload"))
            if expected.get("node_kind") != actual.get("node_kind") or expected.get("subject_id") != actual.get("subject_id"):
                issues.append(
                    {
                        "code": "node_identity_mismatch",
                        "node_id": node_id,
                        "expected": {
                            "node_kind": expected.get("node_kind"),
                            "subject_id": expected.get("subject_id"),
                        },
                        "actual": {
                            "node_kind": actual.get("node_kind"),
                            "subject_id": actual.get("subject_id"),
                        },
                    }
                )
            if drift["missing_keys"] or drift["changed_keys"] or drift["extra_keys"]:
                issues.append(
                    {
                        "code": "node_payload_drift",
                        "node_id": node_id,
                        "node_kind": expected.get("node_kind"),
                        **drift,
                    }
                )

        for edge_id, expected in expected_projection["edges"].items():
            actual = existing_edges.get(edge_id)
            if actual is None:
                issues.append(
                    {
                        "code": "missing_edge",
                        "edge_id": edge_id,
                        "edge_kind": expected.get("edge_kind"),
                    }
                )
                continue
            if (
                expected.get("edge_kind") != actual.get("edge_kind")
                or expected.get("from_node_id") != actual.get("from_node_id")
                or expected.get("to_node_id") != actual.get("to_node_id")
                or self._normalized_value(expected.get("source_ref")) != self._normalized_value(actual.get("source_ref"))
                or self._normalized_value(expected.get("payload")) != self._normalized_value(actual.get("payload"))
            ):
                issues.append(
                    {
                        "code": "edge_drift",
                        "edge_id": edge_id,
                        "expected": expected,
                        "actual": actual,
                    }
                )

        integrity = await self.scan_asset_integrity(session, asset_id=asset_id, limit=limit)
        repair_result = None
        if repair:
            repair_result = await self._persist_projection(
                session,
                projection=expected_projection,
                replace_payload=True,
            )

        report = {
            "asset_id": asset_id,
            "transition_count": len(transitions),
            "dispute_count": len(disputes),
            "expected_node_count": len(expected_projection["nodes"]),
            "expected_edge_count": len(expected_projection["edges"]),
            "drift_detected": bool(issues) or not integrity.get("verified", False),
            "issues": issues,
            "integrity": integrity,
            "repair_applied": bool(repair),
            "repair_result": repair_result,
        }
        self._record_reconcile_metrics(report)
        return report

    async def reproject_asset_projection(self, session, *, asset_id: str, limit: int = 500) -> Dict[str, Any]:
        result = await self.reconcile_asset_projection(
            session,
            asset_id=asset_id,
            limit=limit,
            repair=True,
        )
        result["reprojected"] = True
        try:
            self._metrics.increment_counter("custody_graph_reprojections_total")
        except Exception:
            pass
        return result

    async def list_asset_ids(self, session, *, limit: int = 100, offset: int = 0) -> List[str]:
        return await self._transition_dao.list_asset_ids(session, limit=limit, offset=offset)

    async def query(self, session, **filters: Any) -> Dict[str, Any]:
        dispute_status = filters.pop("dispute_status", None)
        transitions = await self._transition_dao.search(session, **filters)
        if dispute_status:
            relevant = await self._dispute_dao.list_cases(session, status=str(dispute_status), asset_id=filters.get("asset_id"), limit=200)
            dispute_ids = {item["dispute_id"] for item in relevant}
        else:
            relevant = await self._dispute_dao.list_cases(session, asset_id=filters.get("asset_id"), limit=200)
            dispute_ids = {item["dispute_id"] for item in relevant}
        summaries = []
        dispute_map = await self._dispute_map_for_asset(session, asset_id=filters.get("asset_id"))
        for item in transitions:
            attached = self._attach_disputes(item, dispute_map)
            if dispute_status and not any(dispute["status"] == dispute_status for dispute in attached.get("disputes", [])):
                continue
            summaries.append(
                {
                    "transition_event_id": attached["transition_event_id"],
                    "asset_id": attached["asset_id"],
                    "intent_id": attached.get("intent_id"),
                    "task_id": attached.get("task_id"),
                    "token_id": attached.get("token_id"),
                    "from_zone": attached.get("from_zone"),
                    "to_zone": attached.get("to_zone"),
                    "actor_agent_id": attached.get("actor_agent_id"),
                    "endpoint_id": attached.get("endpoint_id"),
                    "recorded_at": attached.get("recorded_at"),
                    "replay_lookup": {
                        "audit_id": attached.get("audit_record_id"),
                        "intent_id": attached.get("intent_id"),
                    },
                    "disputes": attached.get("disputes", []),
                }
            )
        return {
            "filters": {key: value for key, value in filters.items() if value is not None},
            "dispute_status": dispute_status,
            "results": summaries,
            "matched_dispute_ids": sorted(dispute_ids),
        }

    async def open_dispute(
        self,
        session,
        *,
        title: str,
        summary: Optional[str],
        opened_by: Optional[str],
        references: Mapping[str, Any],
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        asset_id = self._resolve_asset_id(references)
        dispute_id = f"dispute:{self._new_id()}"
        case = await self._dispute_dao.create_case(
            session,
            dispute_id=dispute_id,
            status="OPEN",
            title=title,
            summary=summary,
            asset_id=asset_id,
            opened_by=opened_by,
            references=dict(references),
            details=dict(metadata or {}),
        )
        await self._dispute_dao.append_event(
            session,
            dispute_id=dispute_id,
            event_type="OPENED",
            actor_id=opened_by,
            note=summary,
            payload={"references": dict(references)},
            status="OPEN",
        )
        await self._upsert_graph_node(
            session,
            node_id=self.node_id("dispute_case", dispute_id),
            node_kind="dispute_case",
            subject_id=dispute_id,
            payload=case,
            replace_payload=True,
        )
        for ref in self._iter_reference_nodes(references):
            await self._graph_dao.upsert_node(
                session,
                node_id=ref["node_id"],
                node_kind=ref["node_kind"],
                subject_id=ref["subject_id"],
                payload={ref["field"]: ref["subject_id"]},
            )
            await self._graph_dao.append_edge(
                session,
                edge_id=self.edge_id("DISPUTES", dispute_id, ref["subject_id"]),
                edge_kind="DISPUTES",
                from_node_id=self.node_id("dispute_case", dispute_id),
                to_node_id=ref["node_id"],
                source_ref=dispute_id,
                payload={"field": ref["field"]},
            )
        dispute = await self.get_dispute(session, dispute_id=dispute_id)
        if dispute is not None:
            await self._sync_dispute_twins(
                session,
                dispute=dispute,
                event_type="dispute_opened",
                authority_source="custody_dispute_case",
                change_reason="dispute_opened",
            )
        return dispute

    async def append_dispute_event(
        self,
        session,
        *,
        dispute_id: str,
        actor_id: Optional[str],
        note: Optional[str],
        payload: Optional[Mapping[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        next_status = self._normalize_status(status) if status is not None else None
        event = await self._dispute_dao.append_event(
            session,
            dispute_id=dispute_id,
            event_type="COMMENT" if next_status is None else "STATUS_UPDATED",
            actor_id=actor_id,
            note=note,
            payload=dict(payload or {}),
            status=next_status,
        )
        if next_status is not None:
            case = await self._dispute_dao.get_case(session, dispute_id=dispute_id)
            if case is not None:
                await self._upsert_graph_node(
                    session,
                    node_id=self.node_id("dispute_case", dispute_id),
                    node_kind="dispute_case",
                    subject_id=dispute_id,
                    payload=case,
                    replace_payload=True,
                )
        return event

    async def resolve_dispute(
        self,
        session,
        *,
        dispute_id: str,
        status: str,
        resolved_by: Optional[str],
        resolution: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        normalized_status = self._normalize_status(status)
        if normalized_status not in {"RESOLVED", "REJECTED"}:
            raise ValueError("status must be RESOLVED or REJECTED")
        case = await self._dispute_dao.resolve_case(
            session,
            dispute_id=dispute_id,
            status=normalized_status,
            resolved_by=resolved_by,
            resolution=resolution,
        )
        if case is None:
            return None
        await self._dispute_dao.append_event(
            session,
            dispute_id=dispute_id,
            event_type="RESOLVED",
            actor_id=resolved_by,
            note=resolution,
            payload={},
            status=normalized_status,
        )
        await self._upsert_graph_node(
            session,
            node_id=self.node_id("dispute_case", dispute_id),
            node_kind="dispute_case",
            subject_id=dispute_id,
            payload=case,
            replace_payload=True,
        )
        dispute = await self.get_dispute(session, dispute_id=dispute_id)
        if dispute is not None:
            await self._sync_dispute_twins(
                session,
                dispute=dispute,
                event_type="dispute_resolved",
                authority_source="custody_dispute_case",
                change_reason="dispute_resolved",
            )
        return dispute

    async def list_disputes(self, session, *, status: Optional[str] = None, asset_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        rows = await self._dispute_dao.list_cases(
            session,
            status=self._normalize_status(status) if status is not None else None,
            asset_id=asset_id,
            limit=limit,
        )
        results: List[Dict[str, Any]] = []
        for row in rows:
            dispute = await self.get_dispute(session, dispute_id=row["dispute_id"])
            if dispute is not None:
                results.append(dispute)
        return results

    async def list_active_disputes(self, session, *, asset_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        disputes = await self.list_disputes(session, asset_id=asset_id, limit=max(limit * 2, limit))
        active = [item for item in disputes if item.get("status") in ACTIVE_DISPUTE_STATUSES]
        return active[:limit]

    async def active_disputes_for_asset(self, session, *, asset_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return await self.list_active_disputes(session, asset_id=asset_id, limit=limit)

    async def get_dispute(self, session, *, dispute_id: str) -> Optional[Dict[str, Any]]:
        case = await self._dispute_dao.get_case(session, dispute_id=dispute_id)
        if case is None:
            return None
        events = await self._dispute_dao.list_events(session, dispute_id=dispute_id)
        return {**case, "events": events}

    async def disputes_for_asset(self, session, *, asset_id: str) -> List[Dict[str, Any]]:
        return await self.list_disputes(session, asset_id=asset_id, limit=200)

    async def disputes_for_transition(self, session, *, transition_event_id: str) -> List[Dict[str, Any]]:
        cases = await self._dispute_dao.list_cases(session, limit=200)
        return [
            {**case, "events": await self._dispute_dao.list_events(session, dispute_id=case["dispute_id"])}
            for case in cases
            if transition_event_id in self._reference_values(case.get("references", {}), "transition_event_id")
        ]

    @staticmethod
    def node_id(kind: str, subject_id: str) -> str:
        return f"{kind}:{subject_id}"

    @staticmethod
    def edge_id(kind: str, from_subject: str, to_subject: str) -> str:
        return f"{kind}:{from_subject}:{to_subject}"

    def _build_transition_event(
        self,
        *,
        record: Mapping[str, Any],
        governance_ctx: Mapping[str, Any],
        custody_update: Mapping[str, Any] | None,
    ) -> Optional[Dict[str, Any]]:
        action_intent = governance_ctx.get("action_intent") if isinstance(governance_ctx.get("action_intent"), Mapping) else {}
        resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), Mapping) else {}
        evidence_bundle = record.get("evidence_bundle") if isinstance(record.get("evidence_bundle"), Mapping) else {}
        evidence_inputs = evidence_bundle.get("evidence_inputs") if isinstance(evidence_bundle.get("evidence_inputs"), Mapping) else {}
        transition_receipts = evidence_inputs.get("transition_receipts") if isinstance(evidence_inputs.get("transition_receipts"), list) else []
        transition_receipt = next((item for item in transition_receipts if isinstance(item, Mapping)), None)
        asset_id = str(resource.get("asset_id") or (custody_update or {}).get("asset_id") or "").strip()
        if not asset_id:
            return None
        transition_receipt_id = (
            str(transition_receipt.get("transition_receipt_id"))
            if isinstance(transition_receipt, Mapping) and transition_receipt.get("transition_receipt_id") is not None
            else None
        )
        transition_event_id = transition_receipt_id or f"transition:{asset_id}:{(custody_update or {}).get('last_transition_seq') or 0}"
        policy_receipt = governance_ctx.get("policy_receipt") if isinstance(governance_ctx.get("policy_receipt"), Mapping) else {}
        execution_token = governance_ctx.get("execution_token") if isinstance(governance_ctx.get("execution_token"), Mapping) else {}
        return {
            "transition_event_id": transition_event_id,
            "asset_id": asset_id,
            "intent_id": action_intent.get("intent_id"),
            "task_id": record.get("task_id"),
            "token_id": execution_token.get("token_id"),
            "authority_source": (custody_update or {}).get("authority_source") or "governed_execution_receipt",
            "transition_seq": int((custody_update or {}).get("last_transition_seq") or 0),
            "from_zone": transition_receipt.get("from_zone") if isinstance(transition_receipt, Mapping) else None,
            "to_zone": (custody_update or {}).get("current_zone") or (transition_receipt.get("to_zone") if isinstance(transition_receipt, Mapping) else None),
            "actor_agent_id": record.get("agent_id") or record.get("actor_agent_id"),
            "actor_organ_id": record.get("organ_id") or record.get("actor_organ_id"),
            "endpoint_id": (custody_update or {}).get("last_endpoint_id") or (transition_receipt.get("endpoint_id") if isinstance(transition_receipt, Mapping) else None),
            "receipt_hash": (custody_update or {}).get("last_receipt_hash"),
            "receipt_nonce": (custody_update or {}).get("last_receipt_nonce"),
            "receipt_counter": (custody_update or {}).get("last_receipt_counter"),
            "evidence_bundle_id": evidence_bundle.get("evidence_bundle_id"),
            "policy_receipt_id": policy_receipt.get("policy_receipt_id"),
            "transition_receipt_id": transition_receipt_id,
            "lineage_status": "authoritative" if (custody_update or {}).get("authority_source") == "governed_transition_receipt" else "pending",
            "source_registration_id": resource.get("source_registration_id") or (custody_update or {}).get("source_registration_id"),
            "audit_record_id": record.get("entry_id"),
            "details": {
                "record_type": record.get("record_type"),
                "evidence_bundle_id": evidence_bundle.get("evidence_bundle_id"),
            },
        }

    async def _load_twin_refs(self, session, *, asset_id: str, intent_id: Optional[str]) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        twin_queries: List[tuple[str, str]] = [("asset", f"asset:{asset_id}")]
        if intent_id:
            twin_queries.append(("transaction", f"transaction:{intent_id}"))
        asset_snapshot = await self._get_authoritative_twin_snapshot(
            session,
            twin_type="asset",
            twin_id=f"asset:{asset_id}",
        )
        asset_payload = asset_snapshot.get("snapshot") if isinstance(asset_snapshot, dict) else {}
        lineage_refs = asset_payload.get("lineage_refs") if isinstance(asset_payload, dict) else []
        if isinstance(lineage_refs, list):
            for ref in lineage_refs:
                if not isinstance(ref, str) or ":" not in ref:
                    continue
                twin_type, twin_id = ref.split(":", 1)
                if twin_type in {"batch", "product"}:
                    twin_queries.append((twin_type, ref))
        batch_snapshot = None
        for twin_type, twin_ref in twin_queries:
            if twin_type == "batch":
                batch_snapshot = await self._get_authoritative_twin_snapshot(
                    session,
                    twin_type=twin_type,
                    twin_id=twin_ref,
                )
                batch_payload = batch_snapshot.get("snapshot") if isinstance(batch_snapshot, dict) else {}
                batch_lineage_refs = batch_payload.get("lineage_refs") if isinstance(batch_payload, dict) else []
                if isinstance(batch_lineage_refs, list):
                    for ref in batch_lineage_refs:
                        if isinstance(ref, str) and ref.startswith("product:"):
                            twin_queries.append(("product", ref))
        seen_queries: set[tuple[str, str]] = set()
        for twin_type, twin_id in twin_queries:
            if (twin_type, twin_id) in seen_queries:
                continue
            seen_queries.add((twin_type, twin_id))
            if not twin_type or not twin_id:
                continue
            rows = await self._digital_twin_dao.list_history(session, twin_type=twin_type, twin_id=twin_id, limit=5)
            refs.extend(rows[:1])
        return refs

    async def _linked_twin_refs(self, session, *, asset_id: str) -> Dict[str, str]:
        result: Dict[str, str] = {"asset": f"asset:{asset_id}"}
        asset_snapshot = await self._get_authoritative_twin_snapshot(
            session,
            twin_type="asset",
            twin_id=f"asset:{asset_id}",
        )
        snapshot = asset_snapshot.get("snapshot") if isinstance(asset_snapshot, dict) else {}
        lineage_refs = snapshot.get("lineage_refs") if isinstance(snapshot, dict) else []
        if isinstance(lineage_refs, list):
            for ref in lineage_refs:
                if isinstance(ref, str) and ref.startswith("batch:"):
                    result["batch"] = ref
        batch_ref = result.get("batch")
        if batch_ref:
            batch_snapshot = await self._get_authoritative_twin_snapshot(
                session,
                twin_type="batch",
                twin_id=batch_ref,
            )
            batch_payload = batch_snapshot.get("snapshot") if isinstance(batch_snapshot, dict) else {}
            batch_lineage_refs = batch_payload.get("lineage_refs") if isinstance(batch_payload, dict) else []
            if isinstance(batch_lineage_refs, list):
                for ref in batch_lineage_refs:
                    if isinstance(ref, str) and ref.startswith("product:"):
                        result["product"] = ref
        elif isinstance(snapshot, dict):
            custody = snapshot.get("custody") if isinstance(snapshot.get("custody"), dict) else {}
            product_id = custody.get("product_id")
            if isinstance(product_id, str) and product_id.strip():
                result["product"] = f"product:{product_id.strip()}"
        return result

    def _asset_projection(
        self,
        *,
        asset_id: str,
        transitions: Iterable[Mapping[str, Any]],
        disputes: Iterable[Mapping[str, Any]],
        asset_state: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        projection: Dict[str, Dict[str, Dict[str, Any]]] = {"nodes": {}, "edges": {}}
        for transition in transitions:
            self._merge_projection(projection, self._transition_core_projection(transition))
        if asset_state is not None:
            asset_node_id = self.node_id("asset", asset_id)
            self._merge_projection(
                projection,
                {
                    "nodes": {
                        asset_node_id: {
                            "node_id": asset_node_id,
                            "node_kind": "asset",
                            "subject_id": asset_id,
                            "payload": {
                                "asset_id": asset_id,
                                "source_registration_id": asset_state.get("source_registration_id"),
                            },
                        }
                    },
                    "edges": {},
                },
            )
        for dispute in disputes:
            self._merge_projection(projection, self._dispute_projection(dispute))
        return projection

    def _transition_core_projection(self, transition_event: Mapping[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
        projection: Dict[str, Dict[str, Dict[str, Any]]] = {"nodes": {}, "edges": {}}
        asset_id = str(transition_event["asset_id"])
        transition_event_id = str(transition_event["transition_event_id"])
        asset_node_id = self.node_id("asset", asset_id)
        transition_node_id = self.node_id("transition_event", transition_event_id)

        projection["nodes"][asset_node_id] = {
            "node_id": asset_node_id,
            "node_kind": "asset",
            "subject_id": asset_id,
            "payload": {
                "asset_id": asset_id,
                "source_registration_id": transition_event.get("source_registration_id"),
            },
        }
        projection["nodes"][transition_node_id] = {
            "node_id": transition_node_id,
            "node_kind": "transition_event",
            "subject_id": transition_event_id,
            "payload": dict(transition_event),
        }
        projection["edges"][self.edge_id("SETTLED_AS", transition_event_id, asset_id)] = {
            "edge_id": self.edge_id("SETTLED_AS", transition_event_id, asset_id),
            "edge_kind": "SETTLED_AS",
            "from_node_id": transition_node_id,
            "to_node_id": asset_node_id,
            "source_ref": transition_event_id,
            "payload": {"transition_seq": transition_event.get("transition_seq")},
        }

        previous_transition_event_id = transition_event.get("previous_transition_event_id")
        if previous_transition_event_id:
            previous_node_id = self.node_id("transition_event", str(previous_transition_event_id))
            projection["nodes"][previous_node_id] = {
                "node_id": previous_node_id,
                "node_kind": "transition_event",
                "subject_id": str(previous_transition_event_id),
                "payload": {"transition_event_id": str(previous_transition_event_id)},
            }
            projection["edges"][self.edge_id("DERIVED_FROM", transition_event_id, str(previous_transition_event_id))] = {
                "edge_id": self.edge_id("DERIVED_FROM", transition_event_id, str(previous_transition_event_id)),
                "edge_kind": "DERIVED_FROM",
                "from_node_id": transition_node_id,
                "to_node_id": previous_node_id,
                "source_ref": transition_event_id,
                "payload": {"previous_receipt_hash": transition_event.get("previous_receipt_hash")},
            }

        for zone_key, edge_kind in (("from_zone", "MOVED_FROM"), ("to_zone", "MOVED_TO")):
            zone = transition_event.get(zone_key)
            if not zone:
                continue
            zone_id = str(zone)
            zone_node_id = self.node_id("zone", zone_id)
            projection["nodes"][zone_node_id] = {
                "node_id": zone_node_id,
                "node_kind": "zone",
                "subject_id": zone_id,
                "payload": {"zone": zone_id},
            }
            projection["edges"][self.edge_id(edge_kind, transition_event_id, zone_id)] = {
                "edge_id": self.edge_id(edge_kind, transition_event_id, zone_id),
                "edge_kind": edge_kind,
                "from_node_id": transition_node_id,
                "to_node_id": zone_node_id,
                "source_ref": transition_event_id,
                "payload": {},
            }
            if zone_key == "to_zone":
                projection["edges"][self.edge_id("LOCATED_IN", asset_id, zone_id)] = {
                    "edge_id": self.edge_id("LOCATED_IN", asset_id, zone_id),
                    "edge_kind": "LOCATED_IN",
                    "from_node_id": asset_node_id,
                    "to_node_id": zone_node_id,
                    "source_ref": transition_event_id,
                    "payload": {"transition_seq": transition_event.get("transition_seq")},
                }

        for kind, ref_key, edge_kind in (
            ("intent", transition_event.get("intent_id"), "EXECUTED_VIA"),
            ("task", transition_event.get("task_id"), "EXECUTED_VIA"),
            ("execution_token", transition_event.get("token_id"), "AUTHORIZED_BY"),
            ("evidence_bundle", transition_event.get("evidence_bundle_id"), "HAS_EVIDENCE"),
            ("transition_receipt", transition_event.get("transition_receipt_id"), "SEALED_BY"),
        ):
            if not ref_key:
                continue
            subject_id = str(ref_key)
            node_id = self.node_id(kind, subject_id)
            payload = {f"{kind}_id": subject_id}
            if kind == "execution_token":
                payload["policy_receipt_id"] = transition_event.get("policy_receipt_id")
            projection["nodes"][node_id] = {
                "node_id": node_id,
                "node_kind": kind,
                "subject_id": subject_id,
                "payload": payload,
            }
            projection["edges"][self.edge_id(edge_kind, transition_event_id, subject_id)] = {
                "edge_id": self.edge_id(edge_kind, transition_event_id, subject_id),
                "edge_kind": edge_kind,
                "from_node_id": transition_node_id,
                "to_node_id": node_id,
                "source_ref": transition_event_id,
                "payload": {},
            }

        source_registration_id = transition_event.get("source_registration_id")
        if source_registration_id:
            registration_id = str(source_registration_id)
            registration_node_id = self.node_id("source_registration", registration_id)
            projection["nodes"][registration_node_id] = {
                "node_id": registration_node_id,
                "node_kind": "source_registration",
                "subject_id": registration_id,
                "payload": {"source_registration_id": registration_id},
            }
            projection["edges"][self.edge_id("REGISTERED_AS", asset_id, registration_id)] = {
                "edge_id": self.edge_id("REGISTERED_AS", asset_id, registration_id),
                "edge_kind": "REGISTERED_AS",
                "from_node_id": asset_node_id,
                "to_node_id": registration_node_id,
                "source_ref": transition_event_id,
                "payload": {},
            }

        return projection

    def _dispute_projection(self, dispute: Mapping[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
        dispute_id = str(dispute["dispute_id"])
        projection: Dict[str, Dict[str, Dict[str, Any]]] = {
            "nodes": {
                self.node_id("dispute_case", dispute_id): {
                    "node_id": self.node_id("dispute_case", dispute_id),
                    "node_kind": "dispute_case",
                    "subject_id": dispute_id,
                    "payload": dict(dispute),
                }
            },
            "edges": {},
        }
        for ref in self._iter_reference_nodes(dispute.get("references", {})):
            projection["nodes"][ref["node_id"]] = {
                "node_id": ref["node_id"],
                "node_kind": ref["node_kind"],
                "subject_id": ref["subject_id"],
                "payload": {ref["field"]: ref["subject_id"]},
            }
            projection["edges"][self.edge_id("DISPUTES", dispute_id, ref["subject_id"])] = {
                "edge_id": self.edge_id("DISPUTES", dispute_id, ref["subject_id"]),
                "edge_kind": "DISPUTES",
                "from_node_id": self.node_id("dispute_case", dispute_id),
                "to_node_id": ref["node_id"],
                "source_ref": dispute_id,
                "payload": {"field": ref["field"]},
            }
        return projection

    def _merge_projection(
        self,
        base: Dict[str, Dict[str, Dict[str, Any]]],
        other: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> None:
        for node_id, node in other.get("nodes", {}).items():
            existing = base["nodes"].get(node_id)
            if existing is None:
                base["nodes"][node_id] = {
                    "node_id": node["node_id"],
                    "node_kind": node["node_kind"],
                    "subject_id": node.get("subject_id"),
                    "payload": dict(node.get("payload") or {}),
                }
                continue
            existing_payload = dict(existing.get("payload") or {})
            existing_payload.update(dict(node.get("payload") or {}))
            existing["node_kind"] = node.get("node_kind", existing.get("node_kind"))
            existing["subject_id"] = node.get("subject_id", existing.get("subject_id"))
            existing["payload"] = existing_payload
        for edge_id, edge in other.get("edges", {}).items():
            base["edges"][edge_id] = {
                "edge_id": edge["edge_id"],
                "edge_kind": edge["edge_kind"],
                "from_node_id": edge["from_node_id"],
                "to_node_id": edge["to_node_id"],
                "source_ref": edge.get("source_ref"),
                "payload": dict(edge.get("payload") or {}),
            }

    async def _persist_projection(
        self,
        session,
        *,
        projection: Dict[str, Dict[str, Dict[str, Any]]],
        replace_payload: bool = False,
    ) -> Dict[str, Any]:
        touched_nodes: List[str] = []
        touched_edges: List[Dict[str, Any]] = []
        for node_id in sorted(projection.get("nodes", {})):
            node = projection["nodes"][node_id]
            await self._upsert_graph_node(
                session,
                node_id=node["node_id"],
                node_kind=node["node_kind"],
                subject_id=node.get("subject_id"),
                payload=dict(node.get("payload") or {}),
                replace_payload=replace_payload,
            )
            touched_nodes.append(node_id)
        for edge_id in sorted(projection.get("edges", {})):
            edge = projection["edges"][edge_id]
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=edge["edge_id"],
                    edge_kind=edge["edge_kind"],
                    from_node_id=edge["from_node_id"],
                    to_node_id=edge["to_node_id"],
                    source_ref=edge.get("source_ref"),
                    payload=dict(edge.get("payload") or {}),
                )
            )
        return {"node_ids": touched_nodes, "edges": touched_edges}

    async def _upsert_graph_node(
        self,
        session,
        *,
        node_id: str,
        node_kind: str,
        subject_id: Optional[str],
        payload: Dict[str, Any],
        replace_payload: bool = False,
    ) -> Dict[str, Any]:
        if replace_payload:
            try:
                return await self._graph_dao.upsert_node(
                    session,
                    node_id=node_id,
                    node_kind=node_kind,
                    subject_id=subject_id,
                    payload=payload,
                    replace_payload=True,
                )
            except TypeError:
                pass
        return await self._graph_dao.upsert_node(
            session,
            node_id=node_id,
            node_kind=node_kind,
            subject_id=subject_id,
            payload=payload,
        )

    def _payload_drift(self, expected_payload: Any, actual_payload: Any) -> Dict[str, Any]:
        expected = dict(expected_payload or {})
        actual = dict(actual_payload or {})
        missing_keys = sorted(key for key in expected if key not in actual)
        changed_keys = sorted(
            key for key in expected if key in actual and self._normalized_value(expected[key]) != self._normalized_value(actual[key])
        )
        extra_keys = sorted(key for key in actual if key not in expected)
        return {
            "missing_keys": missing_keys,
            "changed_keys": changed_keys,
            "extra_keys": extra_keys,
        }

    def _normalized_value(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): self._normalized_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, list):
            return [self._normalized_value(item) for item in value]
        return value

    def _record_integrity_metrics(self, report: Mapping[str, Any]) -> None:
        try:
            self._metrics.increment_counter("custody_graph_integrity_scans_total")
            issue_count = len(report.get("issues") or [])
            self._metrics.set_gauge("custody_graph_last_integrity_issue_count", float(issue_count))
            if not bool(report.get("verified", False)):
                self._metrics.increment_counter("custody_graph_integrity_failures_total")
        except Exception:
            return

    def _record_reconcile_metrics(self, report: Mapping[str, Any]) -> None:
        try:
            self._metrics.increment_counter("custody_graph_reconciliations_total")
            issue_count = len(report.get("issues") or []) + len((report.get("integrity") or {}).get("issues") or [])
            self._metrics.set_gauge("custody_graph_last_reconcile_issue_count", float(issue_count))
            if bool(report.get("drift_detected", False)):
                self._metrics.increment_counter("custody_graph_reconciliation_drift_total")
            if bool(report.get("repair_applied", False)):
                self._metrics.increment_counter("custody_graph_repairs_total")
        except Exception:
            return

    async def _sync_dispute_twins(
        self,
        session,
        *,
        dispute: Mapping[str, Any],
        event_type: str,
        authority_source: str,
        change_reason: str,
    ) -> None:
        asset_id = dispute.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            return
        twin_refs = await self._linked_twin_refs(session, asset_id=asset_id.strip())
        resolved_refs = []
        for twin_type in ("asset", "batch", "product"):
            twin_id = twin_refs.get(twin_type)
            if isinstance(twin_id, str) and twin_id.strip():
                resolved_refs.append((twin_type, twin_id))
        snapshots = await self._digital_twin_service.load_authoritative_snapshots(
            session,
            twin_refs=resolved_refs,
        )
        if not snapshots:
            return
        await self._digital_twin_service.persist_relevant_twins_in_session(
            session,
            relevant_twin_snapshot=snapshots,
            task_id=None,
            intent_id=next(iter(self._reference_values(dispute.get("references", {}), "intent_id")), None),
            authority_source=authority_source,
            change_reason=change_reason,
            transition_context={
                "event_type": event_type,
                "phase": "dispute",
                "dispute_case": dict(dispute),
            },
        )

    async def _get_authoritative_twin_snapshot(
        self,
        session,
        *,
        twin_type: str,
        twin_id: str,
    ) -> Optional[Dict[str, Any]]:
        getter = getattr(self._digital_twin_dao, "get_authoritative_snapshot", None)
        if getter is None:
            return None
        try:
            return await getter(session, twin_type=twin_type, twin_id=twin_id)
        except Exception:
            return None

    async def _dispute_map_for_asset(self, session, *, asset_id: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not asset_id:
            return {}
        disputes = await self.list_disputes(session, asset_id=asset_id, limit=200)
        mapping: Dict[str, List[Dict[str, Any]]] = {}
        for dispute in disputes:
            refs = dispute.get("references", {})
            for transition_event_id in self._reference_values(refs, "transition_event_id"):
                mapping.setdefault(transition_event_id, []).append(
                    {
                        "dispute_id": dispute["dispute_id"],
                        "status": dispute["status"],
                        "title": dispute["title"],
                    }
                )
        return mapping

    def _attach_disputes(self, transition: Mapping[str, Any], dispute_map: Mapping[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        result = dict(transition)
        result["disputes"] = list(dispute_map.get(str(transition.get("transition_event_id")), []))
        return result

    def _iter_reference_nodes(self, references: Mapping[str, Any]) -> Iterable[Dict[str, str]]:
        mapping = {
            "asset_id": "asset",
            "transition_event_id": "transition_event",
            "intent_id": "intent",
            "audit_record_id": "audit_record",
            "evidence_bundle_id": "evidence_bundle",
            "transition_receipt_id": "transition_receipt",
        }
        for field, node_kind in mapping.items():
            for value in self._reference_values(references, field):
                yield {
                    "field": field,
                    "node_kind": node_kind,
                    "subject_id": value,
                    "node_id": self.node_id(node_kind, value),
                }

    def _reference_values(self, references: Mapping[str, Any], key: str) -> List[str]:
        value = references.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def _resolve_asset_id(self, references: Mapping[str, Any]) -> Optional[str]:
        values = self._reference_values(references, "asset_id")
        return values[0] if values else None

    def _normalize_status(self, status: Optional[str]) -> Optional[str]:
        if status is None:
            return None
        normalized = str(status).strip().upper()
        if normalized not in DISPUTE_STATUSES:
            raise ValueError(f"Unsupported dispute status '{status}'")
        return normalized

    def parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def utcnow(self) -> datetime:
        if callable(self._clock):
            try:
                now = self._clock()
            except Exception:
                now = None
            if isinstance(now, datetime):
                if now.tzinfo is None:
                    now = now.replace(tzinfo=timezone.utc)
                return now.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def _new_id(self) -> str:
        if callable(self._id_generator):
            try:
                candidate = self._id_generator()
            except Exception:
                candidate = None
            if isinstance(candidate, uuid.UUID):
                return str(candidate)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return str(uuid.uuid4())
