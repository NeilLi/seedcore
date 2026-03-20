from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from seedcore.coordinator.dao import (
    CustodyDisputeDAO,
    CustodyGraphDAO,
    CustodyTransitionDAO,
    DigitalTwinDAO,
)


DISPUTE_STATUSES = {"OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"}


class CustodyGraphService:
    def __init__(
        self,
        *,
        transition_dao: Optional[CustodyTransitionDAO] = None,
        graph_dao: Optional[CustodyGraphDAO] = None,
        dispute_dao: Optional[CustodyDisputeDAO] = None,
        digital_twin_dao: Optional[DigitalTwinDAO] = None,
    ) -> None:
        self._transition_dao = transition_dao or CustodyTransitionDAO()
        self._graph_dao = graph_dao or CustodyGraphDAO()
        self._dispute_dao = dispute_dao or CustodyDisputeDAO()
        self._digital_twin_dao = digital_twin_dao or DigitalTwinDAO()

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
        touched_nodes = {
            asset_node_id,
            self.node_id("transition_event", transition_event["transition_event_id"]),
        }
        touched_edges: List[Dict[str, Any]] = []

        await self._graph_dao.upsert_node(
            session,
            node_id=asset_node_id,
            node_kind="asset",
            subject_id=transition_event["asset_id"],
            payload={
                "asset_id": transition_event["asset_id"],
                "source_registration_id": transition_event.get("source_registration_id"),
            },
        )
        await self._graph_dao.upsert_node(
            session,
            node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
            node_kind="transition_event",
            subject_id=transition_event["transition_event_id"],
            payload=dict(transition_event),
        )
        touched_edges.append(
            await self._graph_dao.append_edge(
                session,
                edge_id=self.edge_id("SETTLED_AS", transition_event["transition_event_id"], transition_event["asset_id"]),
                edge_kind="SETTLED_AS",
                from_node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
                to_node_id=asset_node_id,
                source_ref=transition_event["transition_event_id"],
                payload={"transition_seq": transition_event.get("transition_seq")},
            )
        )

        if transition_event.get("previous_transition_event_id"):
            prev_node_id = self.node_id("transition_event", transition_event["previous_transition_event_id"])
            touched_nodes.add(prev_node_id)
            await self._graph_dao.upsert_node(
                session,
                node_id=prev_node_id,
                node_kind="transition_event",
                subject_id=transition_event["previous_transition_event_id"],
                payload={"transition_event_id": transition_event["previous_transition_event_id"]},
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("DERIVED_FROM", transition_event["transition_event_id"], transition_event["previous_transition_event_id"]),
                    edge_kind="DERIVED_FROM",
                    from_node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
                    to_node_id=prev_node_id,
                    source_ref=transition_event["transition_event_id"],
                    payload={"previous_receipt_hash": transition_event.get("previous_receipt_hash")},
                )
            )

        if transition_event.get("from_zone"):
            from_node = self.node_id("zone", transition_event["from_zone"])
            touched_nodes.add(from_node)
            await self._graph_dao.upsert_node(
                session,
                node_id=from_node,
                node_kind="zone",
                subject_id=transition_event["from_zone"],
                payload={"zone": transition_event["from_zone"]},
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("MOVED_FROM", transition_event["transition_event_id"], transition_event["from_zone"]),
                    edge_kind="MOVED_FROM",
                    from_node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
                    to_node_id=from_node,
                    source_ref=transition_event["transition_event_id"],
                    payload={},
                )
            )

        if transition_event.get("to_zone"):
            to_node = self.node_id("zone", transition_event["to_zone"])
            touched_nodes.add(to_node)
            await self._graph_dao.upsert_node(
                session,
                node_id=to_node,
                node_kind="zone",
                subject_id=transition_event["to_zone"],
                payload={"zone": transition_event["to_zone"]},
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("MOVED_TO", transition_event["transition_event_id"], transition_event["to_zone"]),
                    edge_kind="MOVED_TO",
                    from_node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
                    to_node_id=to_node,
                    source_ref=transition_event["transition_event_id"],
                    payload={},
                )
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("LOCATED_IN", transition_event["asset_id"], transition_event["to_zone"]),
                    edge_kind="LOCATED_IN",
                    from_node_id=asset_node_id,
                    to_node_id=to_node,
                    source_ref=transition_event["transition_event_id"],
                    payload={"transition_seq": transition_event.get("transition_seq")},
                )
            )

        for kind, ref_key, edge_kind in (
            ("intent", transition_event.get("intent_id"), "EXECUTED_VIA"),
            ("task", transition_event.get("task_id"), "EXECUTED_VIA"),
            ("execution_token", transition_event.get("token_id"), "AUTHORIZED_BY"),
            ("evidence_bundle", transition_event.get("evidence_bundle_id"), "HAS_EVIDENCE"),
            ("transition_receipt", transition_event.get("transition_receipt_id"), "SEALED_BY"),
        ):
            if not ref_key:
                continue
            node_id = self.node_id(kind, ref_key)
            touched_nodes.add(node_id)
            payload = {f"{kind}_id": ref_key}
            if kind == "execution_token":
                payload["policy_receipt_id"] = transition_event.get("policy_receipt_id")
            await self._graph_dao.upsert_node(
                session,
                node_id=node_id,
                node_kind=kind,
                subject_id=str(ref_key),
                payload=payload,
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id(edge_kind, transition_event["transition_event_id"], ref_key),
                    edge_kind=edge_kind,
                    from_node_id=self.node_id("transition_event", transition_event["transition_event_id"]),
                    to_node_id=node_id,
                    source_ref=transition_event["transition_event_id"],
                    payload={},
                )
            )

        if transition_event.get("source_registration_id"):
            registration_id = transition_event["source_registration_id"]
            registration_node = self.node_id("source_registration", registration_id)
            touched_nodes.add(registration_node)
            await self._graph_dao.upsert_node(
                session,
                node_id=registration_node,
                node_kind="source_registration",
                subject_id=registration_id,
                payload={"source_registration_id": registration_id},
            )
            touched_edges.append(
                await self._graph_dao.append_edge(
                    session,
                    edge_id=self.edge_id("REGISTERED_AS", transition_event["asset_id"], registration_id),
                    edge_kind="REGISTERED_AS",
                    from_node_id=asset_node_id,
                    to_node_id=registration_node,
                    source_ref=transition_event["transition_event_id"],
                    payload={},
                )
            )

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
        }

    async def get_asset_graph(self, session, *, asset_id: str, limit: int = 100) -> Dict[str, Any]:
        transitions = await self._transition_dao.list_for_asset(session, asset_id=asset_id, limit=limit)
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
        }

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
        dispute_id = f"dispute:{uuid.uuid4()}"
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
        await self._graph_dao.upsert_node(
            session,
            node_id=self.node_id("dispute_case", dispute_id),
            node_kind="dispute_case",
            subject_id=dispute_id,
            payload=case,
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
        return await self.get_dispute(session, dispute_id=dispute_id)

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
        await self._graph_dao.upsert_node(
            session,
            node_id=self.node_id("dispute_case", dispute_id),
            node_kind="dispute_case",
            subject_id=dispute_id,
            payload=case,
        )
        return await self.get_dispute(session, dispute_id=dispute_id)

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
        for twin_type, twin_id in (("asset", f"asset:{asset_id}"), ("transaction", f"transaction:{intent_id}") if intent_id else (None, None)):
            if not twin_type or not twin_id:
                continue
            rows = await self._digital_twin_dao.list_history(session, twin_type=twin_type, twin_id=twin_id, limit=5)
            refs.extend(rows[:1])
        return refs

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
        return datetime.now(timezone.utc)
