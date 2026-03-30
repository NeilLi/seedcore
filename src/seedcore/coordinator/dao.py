from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Sequence
import inspect
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, text, tuple_  # pyright: ignore[reportMissingImports]

from ..integrations.rust_kernel import (
    approval_binding_hash_with_rust,
    apply_transfer_approval_transition_with_rust,
    validate_transfer_approval_with_rust,
    verify_approval_transition_history_with_rust,
)
from ..models.asset_custody import AssetCustodyState
from ..models.custody_graph import (
    CustodyDisputeCase,
    CustodyDisputeEvent,
    CustodyGraphEdge,
    CustodyGraphNode,
    CustodyTransitionEvent,
)
from ..models.digital_twin import DigitalTwinEventJournal, DigitalTwinHistory, DigitalTwinState


MAX_PROTO_PLAN_BYTES = int(os.getenv("MAX_PROTO_PLAN_BYTES", str(256 * 1024)))

logger = logging.getLogger(__name__)


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


class TaskRouterTelemetryDAO:
    """Lightweight helper for persisting router telemetry snapshots."""

    def __init__(self, table_name: str = "task_router_telemetry") -> None:
        self._table_name = table_name

    async def insert(
        self,
        session,
        *,
        task_id: str,
        surprise_score: float,
        x_vector: Sequence[float],
        weights: Sequence[float],
        ocps_metadata: Dict[str, Any],
        chosen_route: str,
    ) -> None:
        stmt = text(
            f"""
            INSERT INTO {self._table_name}
            (task_id, surprise_score, x_vector, weights, ocps_metadata, chosen_route)
            VALUES (CAST(:task_id AS uuid), :surprise_score, CAST(:x_vector AS jsonb), CAST(:weights AS jsonb), CAST(:ocps_metadata AS jsonb), :chosen_route)
            """
        )
        await session.execute(
            stmt,
            {
                "task_id": task_id,
                "surprise_score": surprise_score,
                "x_vector": json.dumps(list(x_vector), sort_keys=True),
                "weights": json.dumps(list(weights), sort_keys=True),
                "ocps_metadata": json.dumps(dict(ocps_metadata or {}), sort_keys=True),
                "chosen_route": chosen_route,
            },
        )



class TaskOutboxDAO:
    """DAO for managing coordinator outbox events (enqueue, list, delete, backoff).

    Implements the Outbox Pattern to ensure reliable, decoupled communication
    between the coordinator and downstream task processors.

    Lifecycle:
      1. enqueue_nim_task_embed() — write event to outbox
      2. list_pending_nim_task_embeds() — read pending events
      3. delete() — remove processed event
      4. backoff() — defer retry for failed event
    """

    _TABLE_NAME = "task_outbox"

    async def enqueue_nim_task_embed(
        self,
        session,
        *,
        task_id: str,
        reason: str = "coordinator",
        dedupe_key: Optional[str] = None,
    ) -> bool:
        """Insert a 'nim_task_embed' event into the outbox.

        Args:
            session: Active database session.
            task_id: The UUID of the related task.
            reason: Origin or cause of the enqueue (default: 'coordinator').
            dedupe_key: Optional key for idempotent insert.

        Returns:
            True if the event was inserted, False if skipped due to deduplication.
        """
        payload = {"reason": reason, "task_id": task_id}
        encoded_payload = json.dumps(payload, sort_keys=True)

        if len(encoded_payload.encode("utf-8")) > MAX_PROTO_PLAN_BYTES:
            logger.warning(
                "[Coordinator] Outbox payload for %s exceeded %s bytes; truncating.",
                task_id,
                MAX_PROTO_PLAN_BYTES,
            )
            encoded_payload = json.dumps(
                {"reason": reason, "task_id": task_id, "_truncated": True},
                sort_keys=True,
            )

        stmt = text(
            """
            INSERT INTO task_outbox (task_id, event_type, payload, dedupe_key)
            VALUES (CAST(:task_id AS uuid), :event_type, CAST(:payload AS jsonb), :dedupe_key)
            ON CONFLICT (dedupe_key) DO NOTHING
            """
        )

        result = await session.execute(
            stmt,
            {
                "task_id": task_id,
                "event_type": "nim_task_embed",
                "payload": encoded_payload,
                "dedupe_key": dedupe_key,
            },
        )

        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, (int, float)):
            inserted = rowcount > 0
        elif hasattr(result, "fetchone"):
            try:
                inserted = bool(result.fetchone())
            except Exception:  # pragma: no cover - defensive for mocks only
                inserted = False
        else:
            inserted = False
        if inserted:
            logger.debug(f"[Coordinator] Enqueued nim_task_embed for {task_id}")
        else:
            logger.debug(f"[Coordinator] Skipped duplicate nim_task_embed for {task_id}")
        return inserted

    async def enqueue_embed_task(
        self,
        session,
        *,
        task_id: str,
        reason: str = "coordinator",
        dedupe_key: Optional[str] = None,
    ) -> bool:
        """Backward-compatible alias for legacy enqueue method."""
        return await self.enqueue_nim_task_embed(
            session,
            task_id=task_id,
            reason=reason,
            dedupe_key=dedupe_key,
        )

    async def list_pending_nim_task_embeds(self, session, limit: int = 100) -> List[Any]:
        """Retrieve pending 'nim_task_embed' events awaiting processing."""
        stmt = text(
            f"""
            SELECT id, task_id, payload, attempts
            FROM {self._TABLE_NAME}
            WHERE event_type = 'nim_task_embed'
            ORDER BY id
            LIMIT :limit
            """
        )
        result = await session.execute(stmt, {"limit": limit})
        rows = result.fetchall()

        class Row:
            """Simple DTO wrapper for pending outbox entries."""

            def __init__(self, id_val, task_id, payload, attempts):
                self.id = id_val
                self.task_id = task_id
                self.payload = payload
                self.attempts = attempts or 0
                self.reason = payload.get("reason", "outbox") if isinstance(payload, dict) else "outbox"

        return [Row(row.id, row.task_id, row.payload, row.attempts) for row in rows]

    async def claim_pending_nim_task_embeds(
        self, session, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Claim pending 'nim_task_embed' events for processing with FOR UPDATE SKIP LOCKED.
        
        This method uses row-level locking to ensure concurrent-safe processing:
        - FOR UPDATE SKIP LOCKED prevents multiple workers from processing the same event
        - Filters by available_at (scheduling/backoff) and attempts (poison pill protection)
        - Returns events that are ready to be processed (not locked by other workers)
        
        Production Tip: This query enables multiple Coordinator pods to process different
        outbox rows concurrently without contention. Each pod claims different rows atomically.
        
        Args:
            session: Active database session (must be in a transaction).
            limit: Maximum number of events to claim.
            
        Returns:
            List of dictionaries with 'id' and 'payload' keys.
        """
        stmt = text(
            f"""
            WITH cte AS (
              SELECT id, payload
                FROM {self._TABLE_NAME}
               WHERE event_type = 'nim_task_embed'
                 AND available_at <= NOW()  -- Only claim events that are ready (respects backoff)
                 AND COALESCE(attempts, 0) < 10  -- Poison pill protection (max 10 retries)
            ORDER BY available_at ASC, id ASC  -- Process oldest available events first
               FOR UPDATE SKIP LOCKED  -- The "Magic" concurrency command - prevents pod contention
               LIMIT :limit
            )
            SELECT id, payload FROM cte
            """
        )
        result = await session.execute(stmt, {"limit": limit})

        rows: List[Any] = []
        try:
            mappings_fn = getattr(result, "mappings", None)
            if callable(mappings_fn):
                mapped = mappings_fn()
                all_fn = getattr(mapped, "all", None)
                if callable(all_fn):
                    maybe_rows = all_fn()
                    if isinstance(maybe_rows, list):
                        rows = maybe_rows
        except Exception:
            rows = []

        if not rows:
            fetchall = getattr(result, "fetchall", None)
            if callable(fetchall):
                maybe_rows = fetchall()
                rows = await maybe_rows if inspect.isawaitable(maybe_rows) else maybe_rows
        return [{"id": row["id"], "payload": row["payload"]} for row in rows]

    async def delete(
        self,
        session,
        id_val: Any | None = None,
        *,
        event_id: Any | None = None,
    ) -> None:
        """Delete a processed event from the outbox."""
        target_id = id_val if id_val is not None else event_id
        if target_id is None:
            raise ValueError("delete() requires id_val or event_id")
        stmt = text(f"DELETE FROM {self._TABLE_NAME} WHERE id = :id")
        await session.execute(stmt, {"id": target_id})
        logger.debug(f"[Coordinator] Deleted outbox event {target_id}")

    async def backoff(
        self,
        session,
        id_val: Any | None = None,
        *,
        event_id: Any | None = None,
    ) -> None:
        """Increment retry attempts and defer event availability using backoff strategy."""
        target_id = id_val if id_val is not None else event_id
        if target_id is None:
            raise ValueError("backoff() requires id_val or event_id")
        stmt = text(
            f"""
            UPDATE {self._TABLE_NAME}
            SET attempts = COALESCE(attempts, 0) + 1,
                available_at = NOW() + (LEAST(COALESCE(attempts, 0) + 1, 5) * INTERVAL '30 seconds')
            WHERE id = :id
            """
        )
        await session.execute(stmt, {"id": target_id})
        logger.warning(f"[Coordinator] Backed off event {target_id} for retry.")


class TaskProtoPlanDAO:
    """DAO for persisting proto-plan payloads for downstream workers."""

    _TABLE_NAME = "task_proto_plan"

    async def upsert(
        self,
        session,
        *,
        task_id: str,
        route: str,
        proto_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        serialized = json.dumps(proto_plan, sort_keys=True)
        encoded = serialized.encode("utf-8")
        truncated = False
        if len(encoded) > MAX_PROTO_PLAN_BYTES:
            truncated = True
            logger.warning(
                "[Coordinator] Proto-plan for %s exceeded %s bytes (got %s); truncating",
                task_id,
                MAX_PROTO_PLAN_BYTES,
                len(encoded),
            )
            preview = encoded[: MAX_PROTO_PLAN_BYTES - 128].decode("utf-8", "ignore")
            proto_plan = {
                "_truncated": True,
                "size_bytes": len(encoded),
                "preview": preview,
            }
            serialized = json.dumps(proto_plan, sort_keys=True)

        stmt = text(
            """
            INSERT INTO task_proto_plan (task_id, route, proto_plan)
            VALUES (CAST(:task_id AS uuid), :route, CAST(:proto_plan AS jsonb))
            ON CONFLICT (task_id) DO UPDATE
            SET route = EXCLUDED.route,
                proto_plan = EXCLUDED.proto_plan
            RETURNING id
            """
        )
        result = await session.execute(
            stmt,
            {
                "task_id": task_id,
                "route": route,
                "proto_plan": serialized,
            },
        )
        row = None
        if hasattr(result, "fetchone"):
            maybe_row = result.fetchone()
            row = await maybe_row if inspect.isawaitable(maybe_row) else maybe_row

        response: Dict[str, Any] = {"truncated": truncated}
        if row is not None:
            if isinstance(row, dict):
                id_value = row.get("id")
            else:
                id_value = getattr(row, "id", None)
            if isinstance(id_value, (int, str)):
                response["id"] = id_value
        return response

    async def get_by_task_id(
        self, session, *, task_id: str
    ) -> Optional[Dict[str, Any]]:
        stmt = text(
            """
            SELECT id, task_id, route, proto_plan
              FROM task_proto_plan
             WHERE task_id = CAST(:task_id AS uuid)
            """
        )
        result = await session.execute(stmt, {"task_id": task_id})

        row = None
        fetchone = getattr(result, "fetchone", None)
        if callable(fetchone):
            maybe_row = fetchone()
            row = await maybe_row if inspect.isawaitable(maybe_row) else maybe_row

        if not row:
            return None

        # Support both dict-like and object-style rows
        get = row.get if isinstance(row, dict) else lambda k, default=None: getattr(row, k, default)
        proto_plan_raw = get("proto_plan")
        try:
            proto_plan = json.loads(proto_plan_raw) if isinstance(proto_plan_raw, str) else proto_plan_raw
        except (TypeError, json.JSONDecodeError):
            proto_plan = proto_plan_raw

        return {
            "id": get("id"),
            "task_id": get("task_id"),
            "route": get("route"),
            "proto_plan": proto_plan,
        }


class GovernedExecutionAuditDAO:
    """Append-only persistence helper for governed execution audit records."""

    _TABLE_NAME = "governed_execution_audit"

    async def append_record(
        self,
        session,
        *,
        task_id: str,
        record_type: str,
        intent_id: str,
        token_id: Optional[str] = None,
        policy_snapshot: Optional[str] = None,
        policy_decision: Optional[Dict[str, Any]] = None,
        action_intent: Optional[Dict[str, Any]] = None,
        policy_case: Optional[Dict[str, Any]] = None,
        policy_receipt: Optional[Dict[str, Any]] = None,
        evidence_bundle: Optional[Dict[str, Any]] = None,
        actor_agent_id: Optional[str] = None,
        actor_organ_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = dict(action_intent or {})
        case = dict(policy_case or {})
        decision = dict(policy_decision or {})
        receipt = dict(policy_receipt or {})
        evidence = dict(evidence_bundle or {}) if isinstance(evidence_bundle, dict) else {}
        input_hash = self._sha256_hex(
            _canonical_json(
                {
                    "action_intent": payload,
                    "policy_case": case,
                    "policy_decision": decision,
                    "policy_receipt": receipt,
                }
            )
        )
        evidence_hash = (
            self._sha256_hex(_canonical_json(evidence))
            if evidence
            else None
        )

        stmt = text(
            f"""
            INSERT INTO {self._TABLE_NAME}
            (
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
                evidence_hash
            )
            VALUES (
                CAST(:task_id AS uuid),
                :record_type,
                :intent_id,
                :token_id,
                :policy_snapshot,
                CAST(:policy_decision AS jsonb),
                CAST(:action_intent AS jsonb),
                CAST(:policy_case AS jsonb),
                CAST(:policy_receipt AS jsonb),
                CAST(:evidence_bundle AS jsonb),
                :actor_agent_id,
                :actor_organ_id,
                :input_hash,
                :evidence_hash
            )
            RETURNING id, recorded_at
            """
        )
        result = await session.execute(
            stmt,
            {
                "task_id": str(uuid.UUID(str(task_id))),
                "record_type": record_type,
                "intent_id": intent_id,
                "token_id": token_id,
                "policy_snapshot": policy_snapshot,
                "policy_decision": _canonical_json(decision),
                "action_intent": _canonical_json(payload),
                "policy_case": _canonical_json(case),
                "policy_receipt": _canonical_json(receipt),
                "evidence_bundle": _canonical_json(evidence),
                "actor_agent_id": actor_agent_id,
                "actor_organ_id": actor_organ_id,
                "input_hash": input_hash,
                "evidence_hash": evidence_hash,
            },
        )
        row = result.mappings().one()
        return {
            "entry_id": str(row["id"]),
            "recorded_at": row["recorded_at"].isoformat() if row["recorded_at"] else None,
            "input_hash": input_hash,
            "evidence_hash": evidence_hash,
        }

    async def list_for_task(
        self,
        session,
        *,
        task_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        stmt = text(
            f"""
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
            FROM {self._TABLE_NAME}
            WHERE task_id = CAST(:task_id AS uuid)
            ORDER BY recorded_at DESC, id DESC
            LIMIT :limit
            """
        )
        result = await session.execute(
            stmt,
            {"task_id": str(uuid.UUID(str(task_id))), "limit": max(1, min(int(limit), 500))},
        )
        return [self._mapping_to_dict(row) for row in result.mappings().all()]

    async def get_latest_for_task(self, session, *, task_id: str) -> Optional[Dict[str, Any]]:
        rows = await self.list_for_task(session, task_id=task_id, limit=1)
        return rows[0] if rows else None

    async def search_transition_records(
        self,
        session,
        *,
        asset_id: Optional[str] = None,
        disposition: Optional[str] = None,
        trust_gap_code: Optional[str] = None,
        current_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        components = self._build_transition_search_components(
            asset_id=asset_id,
            disposition=disposition,
            trust_gap_code=trust_gap_code,
            current_only=current_only,
        )
        normalized_limit = max(1, min(int(limit), 500))
        normalized_offset = max(0, int(offset))
        params: Dict[str, Any] = {
            **components["params"],
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        stmt = text(
            f"""
            {components["dataset_sql"]}
            ORDER BY recorded_at DESC, id DESC
            LIMIT :limit
            OFFSET :offset
            """
        )
        result = await session.execute(stmt, params)
        return [self._mapping_to_dict(row) for row in result.mappings().all()]

    async def summarize_transition_records(
        self,
        session,
        *,
        asset_id: Optional[str] = None,
        disposition: Optional[str] = None,
        trust_gap_code: Optional[str] = None,
        current_only: bool = True,
    ) -> Dict[str, Any]:
        components = self._build_transition_search_components(
            asset_id=asset_id,
            disposition=disposition,
            trust_gap_code=trust_gap_code,
            current_only=current_only,
        )
        params = dict(components["params"])
        disposition_expr = components["disposition_expr"]
        summary_stmt = text(
            f"""
            WITH dataset AS (
                {components["dataset_sql"]}
            )
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN {disposition_expr} = 'allow' THEN 1 ELSE 0 END), 0) AS allow_count,
                COALESCE(SUM(CASE WHEN {disposition_expr} = 'deny' THEN 1 ELSE 0 END), 0) AS deny_count,
                COALESCE(SUM(CASE WHEN {disposition_expr} = 'quarantine' THEN 1 ELSE 0 END), 0) AS quarantine_count
            FROM dataset
            """
        )
        summary_result = await session.execute(summary_stmt, params)
        summary_row = summary_result.mappings().one()

        trust_gap_stmt = text(
            f"""
            WITH dataset AS (
                {components["dataset_sql"]}
            ),
            trust_gap_rows AS (
                SELECT DISTINCT
                    dataset.id,
                    trust_gap_code
                FROM dataset
                CROSS JOIN LATERAL (
                    SELECT jsonb_array_elements_text(COALESCE(dataset.policy_decision->'governed_receipt'->'trust_gap_codes', '[]'::jsonb)) AS trust_gap_code
                    UNION
                    SELECT trust_gap->>'code' AS trust_gap_code
                    FROM jsonb_array_elements(COALESCE(dataset.policy_decision->'authz_graph'->'trust_gaps', '[]'::jsonb)) AS trust_gap
                    WHERE trust_gap->>'code' IS NOT NULL
                ) AS codes
            )
            SELECT
                trust_gap_code,
                COUNT(*) AS count
            FROM trust_gap_rows
            WHERE trust_gap_code IS NOT NULL AND trust_gap_code <> ''
            GROUP BY trust_gap_code
            ORDER BY count DESC, trust_gap_code ASC
            """
        )
        trust_gap_result = await session.execute(trust_gap_stmt, params)
        trust_gap_rows = trust_gap_result.mappings().all()
        allow_count = int(summary_row["allow_count"] or 0)
        deny_count = int(summary_row["deny_count"] or 0)
        quarantine_count = int(summary_row["quarantine_count"] or 0)
        return {
            "total": int(summary_row["total"] or 0),
            "restricted_count": deny_count + quarantine_count,
            "dispositions": [
                {"value": "allow", "count": allow_count},
                {"value": "deny", "count": deny_count},
                {"value": "quarantine", "count": quarantine_count},
            ],
            "trust_gap_codes": [
                {"value": str(row["trust_gap_code"]), "count": int(row["count"] or 0)}
                for row in trust_gap_rows
            ],
        }

    def _build_transition_search_components(
        self,
        *,
        asset_id: Optional[str],
        disposition: Optional[str],
        trust_gap_code: Optional[str],
        current_only: bool,
    ) -> Dict[str, Any]:
        normalized_asset_id = str(asset_id).strip() if isinstance(asset_id, str) and asset_id.strip() else None
        normalized_disposition = str(disposition).strip().lower() if isinstance(disposition, str) and disposition.strip() else None
        normalized_trust_gap_code = (
            str(trust_gap_code).strip() if isinstance(trust_gap_code, str) and trust_gap_code.strip() else None
        )
        asset_expr = "COALESCE(policy_decision->'governed_receipt'->>'asset_ref', policy_decision->'authz_graph'->>'asset_ref', policy_receipt->>'asset_ref', action_intent->'resource'->>'asset_id')"
        disposition_expr = "LOWER(COALESCE(policy_decision->'authz_graph'->>'disposition', policy_decision->'governed_receipt'->>'disposition', policy_decision->>'disposition'))"
        base_predicates = [
            f"({asset_expr}) IS NOT NULL",
            f"COALESCE(policy_decision->'authz_graph', policy_decision->'governed_receipt') IS NOT NULL",
        ]
        filtered_predicates: List[str] = []
        params: Dict[str, Any] = {}
        if normalized_asset_id is not None:
            base_predicates.append(f"({asset_expr}) = :asset_id")
            params["asset_id"] = normalized_asset_id
        if normalized_disposition is not None:
            filtered_predicates.append(f"{disposition_expr} = :disposition")
            params["disposition"] = normalized_disposition
        if normalized_trust_gap_code is not None:
            filtered_predicates.append(
                """
                (
                    COALESCE(policy_decision->'governed_receipt'->'trust_gap_codes', '[]'::jsonb) @> jsonb_build_array(CAST(:trust_gap_code AS text))
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(COALESCE(policy_decision->'authz_graph'->'trust_gaps', '[]'::jsonb)) AS trust_gap
                        WHERE trust_gap->>'code' = CAST(:trust_gap_code AS text)
                    )
                )
                """
            )
            params["trust_gap_code"] = normalized_trust_gap_code
        base_where_clause = " AND ".join(predicate.strip() for predicate in base_predicates)
        filtered_where_clause = " AND ".join(predicate.strip() for predicate in filtered_predicates) or "TRUE"
        select_columns = """
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
        """
        if current_only:
            dataset_sql = f"""
                WITH ranked AS (
                    SELECT
                        {select_columns},
                        ROW_NUMBER() OVER (
                            PARTITION BY {asset_expr}
                            ORDER BY recorded_at DESC, id DESC
                        ) AS row_num
                    FROM {self._TABLE_NAME}
                    WHERE {base_where_clause}
                )
                SELECT
                    {select_columns}
                FROM ranked
                WHERE row_num = 1
                  AND {filtered_where_clause}
            """
        else:
            dataset_sql = f"""
                SELECT
                    {select_columns}
                FROM {self._TABLE_NAME}
                WHERE {base_where_clause}
                  AND {filtered_where_clause}
            """
        return {
            "params": params,
            "dataset_sql": dataset_sql.strip(),
            "disposition_expr": disposition_expr,
        }

    async def list_for_intent(
        self,
        session,
        *,
        intent_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        stmt = text(
            f"""
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
            FROM {self._TABLE_NAME}
            WHERE intent_id = :intent_id
            ORDER BY recorded_at DESC, id DESC
            LIMIT :limit
            """
        )
        result = await session.execute(
            stmt,
            {"intent_id": str(intent_id), "limit": max(1, min(int(limit), 500))},
        )
        return [self._mapping_to_dict(row) for row in result.mappings().all()]

    async def get_latest_for_intent(self, session, *, intent_id: str) -> Optional[Dict[str, Any]]:
        rows = await self.list_for_intent(session, intent_id=intent_id, limit=1)
        return rows[0] if rows else None

    async def get_by_entry_id(self, session, *, entry_id: str) -> Optional[Dict[str, Any]]:
        stmt = text(
            f"""
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
            FROM {self._TABLE_NAME}
            WHERE id = CAST(:entry_id AS uuid)
            LIMIT 1
            """
        )
        result = await session.execute(
            stmt,
            {"entry_id": str(uuid.UUID(str(entry_id)))},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._mapping_to_dict(row)

    def _mapping_to_dict(self, row: Any) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "task_id": str(row["task_id"]),
            "record_type": row["record_type"],
            "intent_id": row["intent_id"],
            "token_id": row["token_id"],
            "policy_snapshot": row["policy_snapshot"],
            "policy_decision": dict(row["policy_decision"] or {}),
            "action_intent": dict(row["action_intent"] or {}),
            "policy_case": dict(row["policy_case"] or {}),
            "policy_receipt": dict(row.get("policy_receipt") or {}),
            "evidence_bundle": dict(row["evidence_bundle"] or {}),
            "actor_agent_id": row["actor_agent_id"],
            "actor_organ_id": row["actor_organ_id"],
            "input_hash": row["input_hash"],
            "evidence_hash": row["evidence_hash"],
            "recorded_at": row["recorded_at"].isoformat() if row["recorded_at"] else None,
        }

    def _sha256_hex(self, payload: str) -> str:
        import hashlib

        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TransferApprovalEnvelopeDAO:
    """Persistence helper for versioned transfer approval envelopes."""

    _ENVELOPES_TABLE = "transfer_approval_envelopes"
    _TRANSITIONS_TABLE = "transfer_approval_transition_events"

    async def create_envelope(
        self,
        session,
        *,
        envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = self._normalize_envelope(self._validated_envelope(envelope))
        await self._clear_current_marker(session, approval_envelope_id=normalized["approval_envelope_id"])
        stmt = text(
            f"""
            INSERT INTO {self._ENVELOPES_TABLE}
            (
                approval_envelope_id,
                version,
                is_current,
                workflow_type,
                status,
                asset_ref,
                lot_id,
                policy_snapshot_ref,
                approval_binding_hash,
                envelope_payload,
                created_at,
                expires_at,
                superseded_by_version
            )
            VALUES
            (
                :approval_envelope_id,
                :version,
                :is_current,
                :workflow_type,
                :status,
                :asset_ref,
                :lot_id,
                :policy_snapshot_ref,
                :approval_binding_hash,
                CAST(:envelope_payload AS jsonb),
                :created_at,
                :expires_at,
                :superseded_by_version
            )
            RETURNING id, recorded_at
            """
        )
        result = await session.execute(
            stmt,
            {
                **normalized,
                "envelope_payload": _canonical_json(normalized["envelope_payload"]),
            },
        )
        row = result.mappings().one()
        return {
            **self._mapping_to_envelope_dict(
                {
                    **normalized,
                    "id": row["id"],
                    "recorded_at": row["recorded_at"],
                }
            ),
        }

    async def create_or_update_envelope(
        self,
        session,
        *,
        envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = self._validated_envelope(envelope)
        version = int(normalized.get("version") or 1)
        current = await self.get_current(
            session,
            approval_envelope_id=str(normalized.get("approval_envelope_id") or ""),
        )
        if current is not None and int(current.get("version") or 0) >= version:
            version = int(current.get("version") or 0) + 1
            normalized["version"] = version
        return await self.create_envelope(session, envelope=normalized)

    async def get_current(self, session, *, approval_envelope_id: str) -> Optional[Dict[str, Any]]:
        stmt = text(
            f"""
            SELECT *
            FROM {self._ENVELOPES_TABLE}
            WHERE approval_envelope_id = :approval_envelope_id
              AND is_current = TRUE
            LIMIT 1
            """
        )
        result = await session.execute(stmt, {"approval_envelope_id": str(approval_envelope_id)})
        row = result.mappings().one_or_none()
        return self._mapping_to_envelope_dict(row) if row is not None else None

    async def get_version(
        self,
        session,
        *,
        approval_envelope_id: str,
        version: int,
    ) -> Optional[Dict[str, Any]]:
        stmt = text(
            f"""
            SELECT *
            FROM {self._ENVELOPES_TABLE}
            WHERE approval_envelope_id = :approval_envelope_id
              AND version = :version
            LIMIT 1
            """
        )
        result = await session.execute(
            stmt,
            {"approval_envelope_id": str(approval_envelope_id), "version": int(version)},
        )
        row = result.mappings().one_or_none()
        return self._mapping_to_envelope_dict(row) if row is not None else None

    async def list_transition_events(
        self,
        session,
        *,
        approval_envelope_id: str,
    ) -> List[Dict[str, Any]]:
        stmt = text(
            f"""
            SELECT *
            FROM {self._TRANSITIONS_TABLE}
            WHERE approval_envelope_id = :approval_envelope_id
            ORDER BY occurred_at ASC, recorded_at ASC
            """
        )
        result = await session.execute(stmt, {"approval_envelope_id": str(approval_envelope_id)})
        return [self._mapping_to_transition_dict(row) for row in result.mappings().all()]

    async def get_current_with_history(
        self,
        session,
        *,
        approval_envelope_id: str,
    ) -> Optional[Dict[str, Any]]:
        envelope = await self.get_current(session, approval_envelope_id=approval_envelope_id)
        if envelope is None:
            return None
        events = await self.list_transition_events(session, approval_envelope_id=approval_envelope_id)
        history = self._history_payload(events)
        return {
            **envelope,
            "transition_history": events,
            "approval_transition_head": history["chain_head"],
            "approval_transition_count": len(events),
        }

    async def apply_transition(
        self,
        session,
        *,
        approval_envelope_id: str,
        transition: Dict[str, Any],
        actor_ref: Optional[str] = None,
        occurred_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        current = await self.get_current(session, approval_envelope_id=approval_envelope_id)
        if current is None:
            raise ValueError(f"approval envelope '{approval_envelope_id}' not found")

        history_events = await self.list_transition_events(session, approval_envelope_id=approval_envelope_id)
        history_payload = self._history_payload(history_events)
        history_check = verify_approval_transition_history_with_rust(history_payload)
        if not bool(history_check.get("valid", False)):
            raise ValueError("stored approval transition history failed Rust verification")

        transition_payload = dict(transition or {})
        if actor_ref and transition_payload.get("actor_ref") is None:
            transition_payload["actor_ref"] = actor_ref
        if occurred_at and transition_payload.get("occurred_at") is None:
            transition_payload["occurred_at"] = occurred_at

        rust_result = apply_transfer_approval_transition_with_rust(
            dict(current.get("envelope") or {}),
            transition_payload,
            history=history_payload,
            now=self._coerce_datetime(transition_payload.get("occurred_at") or occurred_at),
        )
        if not bool(rust_result.get("valid", False)):
            raise ValueError(
                rust_result.get("error_code")
                or "approval_transition_invalid"
            )

        updated_envelope = rust_result.get("approval_envelope")
        transition_event = rust_result.get("transition_event")
        updated_history = rust_result.get("history")
        binding_hash = self._coerce_binding_hash(rust_result.get("binding_hash"))
        if not isinstance(updated_envelope, Mapping):
            raise ValueError("Rust approval transition did not return an approval envelope")
        if not isinstance(transition_event, Mapping):
            raise ValueError("Rust approval transition did not return a transition event")
        if not isinstance(updated_history, Mapping):
            raise ValueError("Rust approval transition did not return transition history")

        next_version = int(current.get("version") or 0) + 1
        envelope_payload = dict(updated_envelope)
        envelope_payload["approval_envelope_id"] = approval_envelope_id
        envelope_payload["version"] = next_version
        if binding_hash is not None:
            envelope_payload["approval_binding_hash"] = binding_hash

        await self.supersede_current_version(
            session,
            approval_envelope_id=approval_envelope_id,
            superseded_by_version=next_version,
        )
        stored_envelope = await self.create_envelope(session, envelope=envelope_payload)
        stored_event = await self.append_transition_event(
            session,
            approval_envelope_id=approval_envelope_id,
            envelope_version=next_version,
            event_id=str(transition_event.get("event_id") or transition_event.get("approval_transition_id") or f"{approval_envelope_id}:{next_version}"),
            event_hash=str(transition_event.get("event_hash") or updated_history.get("chain_head") or ""),
            previous_event_hash=self._coerce_optional_string(transition_event.get("previous_event_hash")),
            previous_status=self._coerce_optional_string(current.get("status")),
            next_status=self._coerce_optional_string(envelope_payload.get("status")),
            actor_ref=self._coerce_optional_string(actor_ref or transition_event.get("actor_ref")),
            transition_payload=transition_payload,
            transition_event=dict(transition_event),
            occurred_at=self._isoformat(
                self._coerce_datetime(
                    transition_event.get("occurred_at")
                    or transition_payload.get("occurred_at")
                    or occurred_at
                )
            ),
        )
        return {
            **stored_envelope,
            "transition_history": [*history_events, stored_event],
            "approval_transition_head": self._coerce_optional_string(updated_history.get("chain_head")),
            "approval_transition_count": len(history_events) + 1,
            "last_transition_event": stored_event,
        }

    async def append_transition_event(
        self,
        session,
        *,
        approval_envelope_id: str,
        envelope_version: int,
        event_id: str,
        event_hash: str,
        previous_event_hash: Optional[str],
        previous_status: Optional[str],
        next_status: Optional[str],
        actor_ref: Optional[str],
        transition_payload: Dict[str, Any],
        transition_event: Dict[str, Any],
        occurred_at: Optional[str],
    ) -> Dict[str, Any]:
        occurred_at_value = self._coerce_datetime(occurred_at) or datetime.now(timezone.utc)
        stmt = text(
            f"""
            INSERT INTO {self._TRANSITIONS_TABLE}
            (
                approval_envelope_id,
                envelope_version,
                event_id,
                event_hash,
                previous_event_hash,
                previous_status,
                next_status,
                actor_ref,
                transition_payload,
                transition_event,
                occurred_at
            )
            VALUES
            (
                :approval_envelope_id,
                :envelope_version,
                :event_id,
                :event_hash,
                :previous_event_hash,
                :previous_status,
                :next_status,
                :actor_ref,
                CAST(:transition_payload AS jsonb),
                CAST(:transition_event AS jsonb),
                :occurred_at
            )
            RETURNING id, recorded_at
            """
        )
        result = await session.execute(
            stmt,
            {
                "approval_envelope_id": str(approval_envelope_id),
                "envelope_version": int(envelope_version),
                "event_id": str(event_id),
                "event_hash": str(event_hash),
                "previous_event_hash": str(previous_event_hash) if previous_event_hash is not None else None,
                "previous_status": str(previous_status) if previous_status is not None else None,
                "next_status": str(next_status) if next_status is not None else None,
                "actor_ref": str(actor_ref) if actor_ref is not None else None,
                "transition_payload": _canonical_json(dict(transition_payload or {})),
                "transition_event": _canonical_json(dict(transition_event or {})),
                "occurred_at": occurred_at_value,
            },
        )
        row = result.mappings().one()
        return self._mapping_to_transition_dict(
            {
                "id": row["id"],
                "approval_envelope_id": approval_envelope_id,
                "envelope_version": envelope_version,
                "event_id": event_id,
                "event_hash": event_hash,
                "previous_event_hash": previous_event_hash,
                "previous_status": previous_status,
                "next_status": next_status,
                "actor_ref": actor_ref,
                "transition_payload": dict(transition_payload or {}),
                "transition_event": dict(transition_event or {}),
                "occurred_at": occurred_at_value,
                "recorded_at": row["recorded_at"],
            }
        )

    async def supersede_current_version(
        self,
        session,
        *,
        approval_envelope_id: str,
        superseded_by_version: int,
    ) -> None:
        stmt = text(
            f"""
            UPDATE {self._ENVELOPES_TABLE}
            SET is_current = FALSE,
                superseded_by_version = :superseded_by_version
            WHERE approval_envelope_id = :approval_envelope_id
              AND is_current = TRUE
            """
        )
        await session.execute(
            stmt,
            {
                "approval_envelope_id": str(approval_envelope_id),
                "superseded_by_version": int(superseded_by_version),
            },
        )

    async def _clear_current_marker(self, session, *, approval_envelope_id: str) -> None:
        stmt = text(
            f"""
            UPDATE {self._ENVELOPES_TABLE}
            SET is_current = FALSE
            WHERE approval_envelope_id = :approval_envelope_id
              AND is_current = TRUE
            """
        )
        await session.execute(stmt, {"approval_envelope_id": str(approval_envelope_id)})

    def _normalize_envelope(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(envelope or {})
        approval_envelope_id = str(payload.get("approval_envelope_id") or "").strip()
        if not approval_envelope_id:
            raise ValueError("approval_envelope_id is required")
        version = int(payload.get("version") or 1)
        created_at = self._coerce_datetime(payload.get("created_at")) or datetime.now(timezone.utc)
        expires_at = self._coerce_datetime(payload.get("expires_at"))
        binding_hash = self._coerce_binding_hash(payload.get("approval_binding_hash"))
        if binding_hash is not None:
            payload["approval_binding_hash"] = binding_hash
        payload["version"] = version
        return {
            "approval_envelope_id": approval_envelope_id,
            "version": version,
            "is_current": True,
            "workflow_type": str(payload.get("workflow_type") or "").strip() or "custody_transfer",
            "status": str(payload.get("status") or "").strip() or "PENDING",
            "asset_ref": str(payload.get("asset_ref") or "").strip(),
            "lot_id": str(payload.get("lot_id")).strip() if payload.get("lot_id") is not None else None,
            "policy_snapshot_ref": (
                str(payload.get("policy_snapshot_ref") or payload.get("policy_snapshot") or "").strip()
                or None
            ),
            "approval_binding_hash": binding_hash,
            "envelope_payload": payload,
            "created_at": created_at,
            "expires_at": expires_at,
            "superseded_by_version": None,
        }

    def _mapping_to_envelope_dict(self, row: Any) -> Dict[str, Any]:
        payload = dict(row.get("envelope_payload") or {}) if isinstance(row, dict) else dict(row["envelope_payload"] or {})
        payload["approval_envelope_id"] = str(
            (row.get("approval_envelope_id") if isinstance(row, dict) else row["approval_envelope_id"]) or payload.get("approval_envelope_id") or ""
        )
        payload["version"] = int(
            (row.get("version") if isinstance(row, dict) else row["version"]) or payload.get("version") or 1
        )
        binding_hash = self._coerce_binding_hash(
            row.get("approval_binding_hash") if isinstance(row, dict) else row["approval_binding_hash"]
        )
        if binding_hash is not None:
            payload["approval_binding_hash"] = binding_hash
        return {
            "id": str(row.get("id") if isinstance(row, dict) else row["id"]) if (row.get("id") if isinstance(row, dict) else row["id"]) is not None else None,
            "approval_envelope_id": payload["approval_envelope_id"],
            "version": payload["version"],
            "is_current": bool(row.get("is_current") if isinstance(row, dict) else row["is_current"]),
            "status": str(row.get("status") if isinstance(row, dict) else row["status"]),
            "workflow_type": str(row.get("workflow_type") if isinstance(row, dict) else row["workflow_type"]),
            "asset_ref": str(row.get("asset_ref") if isinstance(row, dict) else row["asset_ref"]),
            "lot_id": row.get("lot_id") if isinstance(row, dict) else row["lot_id"],
            "policy_snapshot_ref": row.get("policy_snapshot_ref") if isinstance(row, dict) else row["policy_snapshot_ref"],
            "approval_binding_hash": binding_hash,
            "created_at": self._isoformat(row.get("created_at") if isinstance(row, dict) else row["created_at"]),
            "expires_at": self._isoformat(row.get("expires_at") if isinstance(row, dict) else row["expires_at"]),
            "recorded_at": self._isoformat(row.get("recorded_at") if isinstance(row, dict) else row["recorded_at"]),
            "superseded_by_version": row.get("superseded_by_version") if isinstance(row, dict) else row["superseded_by_version"],
            "envelope": payload,
        }

    def _validated_envelope(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(envelope or {})
        asset_ref = str(payload.get("asset_ref") or "").strip()
        if not asset_ref:
            raise ValueError("asset_ref is required")
        validation = validate_transfer_approval_with_rust(payload)
        if not bool(validation.get("valid", False)):
            raise ValueError(validation.get("error_code") or "approval_envelope_invalid")
        rust_binding = approval_binding_hash_with_rust(payload)
        binding_hash = self._coerce_binding_hash(rust_binding.get("binding_hash"))
        if binding_hash is None:
            raise ValueError(rust_binding.get("error_code") or "approval_binding_hash_invalid")
        provided_binding = self._coerce_binding_hash(payload.get("approval_binding_hash"))
        if provided_binding is not None and provided_binding != binding_hash:
            raise ValueError("approval_binding_hash_mismatch")
        payload["approval_binding_hash"] = binding_hash
        return payload

    def _history_payload(self, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        raw_events = [
            dict(item.get("transition_event") or {})
            for item in events
            if isinstance(item.get("transition_event"), dict)
        ]
        chain_head = None
        if events:
            last_event = events[-1]
            chain_head = self._coerce_optional_string(last_event.get("event_hash"))
        return {
            "events": raw_events,
            "chain_head": chain_head,
        }

    def _mapping_to_transition_dict(self, row: Any) -> Dict[str, Any]:
        return {
            "id": str(row.get("id") if isinstance(row, dict) else row["id"]),
            "approval_envelope_id": str(row.get("approval_envelope_id") if isinstance(row, dict) else row["approval_envelope_id"]),
            "envelope_version": int(row.get("envelope_version") if isinstance(row, dict) else row["envelope_version"]),
            "event_id": str(row.get("event_id") if isinstance(row, dict) else row["event_id"]),
            "event_hash": str(row.get("event_hash") if isinstance(row, dict) else row["event_hash"]),
            "previous_event_hash": row.get("previous_event_hash") if isinstance(row, dict) else row["previous_event_hash"],
            "previous_status": row.get("previous_status") if isinstance(row, dict) else row["previous_status"],
            "next_status": row.get("next_status") if isinstance(row, dict) else row["next_status"],
            "actor_ref": row.get("actor_ref") if isinstance(row, dict) else row["actor_ref"],
            "transition_payload": dict(row.get("transition_payload") or {}) if isinstance(row, dict) else dict(row["transition_payload"] or {}),
            "transition_event": dict(row.get("transition_event") or {}) if isinstance(row, dict) else dict(row["transition_event"] or {}),
            "occurred_at": self._isoformat(row.get("occurred_at") if isinstance(row, dict) else row["occurred_at"]),
            "recorded_at": self._isoformat(row.get("recorded_at") if isinstance(row, dict) else row["recorded_at"]),
        }

    def _coerce_optional_string(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _coerce_binding_hash(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, dict):
            algorithm = str(value.get("algorithm") or "").strip()
            raw_value = str(value.get("value") or "").strip()
            if algorithm and raw_value:
                return f"{algorithm}:{raw_value}"
            return None
        normalized = str(value).strip()
        return normalized or None

    def _coerce_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _isoformat(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)


class DigitalTwinDAO:
    """Persistence helper for authoritative digital twin state + version history."""

    async def get_authoritative_snapshot(
        self,
        session,
        *,
        twin_type: str,
        twin_id: str,
    ) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(DigitalTwinState).where(
                    DigitalTwinState.twin_type == str(twin_type),
                    DigitalTwinState.twin_id == str(twin_id),
                )
            )
        ).scalars().first()
        if row is None:
            return None
        return self._state_to_dict(row)

    async def get_authoritative_snapshots(
        self,
        session,
        *,
        twin_refs: Sequence[tuple[str, str]],
    ) -> Dict[tuple[str, str], Dict[str, Any]]:
        normalized_refs = {
            (str(twin_type).strip(), str(twin_id).strip())
            for twin_type, twin_id in twin_refs
            if str(twin_type).strip() and str(twin_id).strip()
        }
        if not normalized_refs:
            return {}

        rows = (
            await session.execute(
                select(DigitalTwinState).where(
                    tuple_(DigitalTwinState.twin_type, DigitalTwinState.twin_id).in_(
                        list(normalized_refs)
                    )
                )
            )
        ).scalars().all()
        return {
            (row.twin_type, row.twin_id): self._state_to_dict(row)
            for row in rows
        }

    async def upsert_snapshot(
        self,
        session,
        *,
        twin_snapshot: Dict[str, Any],
        authority_source: str,
        source_task_id: Optional[str] = None,
        source_intent_id: Optional[str] = None,
        change_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = self._normalize_snapshot(twin_snapshot)
        twin_type = normalized["twin_kind"]
        twin_id = normalized["twin_id"]
        source_task_uuid = self._coerce_uuid(source_task_id)

        row = (
            await session.execute(
                select(DigitalTwinState).where(
                    DigitalTwinState.twin_type == twin_type,
                    DigitalTwinState.twin_id == twin_id,
                )
            )
        ).scalars().first()

        if row is None:
            row = DigitalTwinState(
                twin_type=twin_type,
                twin_id=twin_id,
                state_version=1,
                authority_source=str(authority_source),
                snapshot=normalized,
                last_task_id=source_task_uuid,
                last_intent_id=str(source_intent_id) if source_intent_id is not None else None,
            )
            session.add(row)
            await session.flush()
            await self._append_history(
                session,
                row=row,
                change_reason=change_reason,
                source_task_id=source_task_uuid,
                source_intent_id=source_intent_id,
            )
            return {**self._state_to_dict(row), "changed": True}

        previous_snapshot = dict(row.snapshot or {})
        changed = _canonical_json(previous_snapshot) != _canonical_json(normalized)

        row.authority_source = str(authority_source)
        if source_task_uuid is not None:
            row.last_task_id = source_task_uuid
        if source_intent_id is not None:
            row.last_intent_id = str(source_intent_id)

        if changed:
            row.state_version = int(row.state_version or 0) + 1
            row.snapshot = normalized
            await session.flush()
            await self._append_history(
                session,
                row=row,
                change_reason=change_reason,
                source_task_id=source_task_uuid,
                source_intent_id=source_intent_id,
            )
        else:
            await session.flush()

        return {**self._state_to_dict(row), "changed": changed}

    async def list_history(
        self,
        session,
        *,
        twin_type: str,
        twin_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        rows = (
            await session.execute(
                select(DigitalTwinHistory)
                .where(
                    DigitalTwinHistory.twin_type == str(twin_type),
                    DigitalTwinHistory.twin_id == str(twin_id),
                )
                .order_by(DigitalTwinHistory.recorded_at.desc(), DigitalTwinHistory.state_version.desc())
                .limit(max(1, min(int(limit), 500)))
            )
        ).scalars().all()
        return [self._history_to_dict(row) for row in rows]

    async def _append_history(
        self,
        session,
        *,
        row: DigitalTwinState,
        change_reason: Optional[str],
        source_task_id: Optional[uuid.UUID],
        source_intent_id: Optional[str],
    ) -> None:
        history = DigitalTwinHistory(
            twin_state_id=row.id,
            twin_type=row.twin_type,
            twin_id=row.twin_id,
            state_version=int(row.state_version),
            authority_source=row.authority_source,
            snapshot=dict(row.snapshot or {}),
            change_reason=str(change_reason) if change_reason is not None else None,
            source_task_id=source_task_id,
            source_intent_id=str(source_intent_id) if source_intent_id is not None else None,
        )
        session.add(history)
        await session.flush()

    def _normalize_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(payload or {})
        twin_type = str(data.get("twin_kind") or data.get("twin_type") or "").strip()
        twin_id = str(data.get("twin_id") or "").strip()
        if not twin_type or not twin_id:
            raise ValueError("twin_snapshot must include non-empty twin_kind and twin_id")
        normalized = {
            "twin_kind": twin_type,
            "twin_id": twin_id,
            **data,
        }
        normalized["twin_kind"] = twin_type
        normalized["twin_id"] = twin_id
        return normalized

    def _state_to_dict(self, row: DigitalTwinState) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "twin_type": row.twin_type,
            "twin_kind": row.twin_type,
            "twin_id": row.twin_id,
            "state_version": int(row.state_version or 0),
            "authority_source": row.authority_source,
            "snapshot": dict(row.snapshot or {}),
            "last_task_id": str(row.last_task_id) if row.last_task_id is not None else None,
            "last_intent_id": row.last_intent_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _history_to_dict(self, row: DigitalTwinHistory) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "twin_state_id": str(row.twin_state_id),
            "twin_type": row.twin_type,
            "twin_kind": row.twin_type,
            "twin_id": row.twin_id,
            "state_version": int(row.state_version),
            "authority_source": row.authority_source,
            "snapshot": dict(row.snapshot or {}),
            "change_reason": row.change_reason,
            "source_task_id": str(row.source_task_id) if row.source_task_id is not None else None,
            "source_intent_id": row.source_intent_id,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        }

    def _coerce_uuid(self, value: Optional[str]) -> Optional[uuid.UUID]:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None


class DigitalTwinEventJournalDAO:
    """Persistence helper for normalized twin event journal records."""

    async def append_event(
        self,
        session,
        *,
        twin_kind: str,
        twin_id: str,
        event_type: str,
        revision_stage: str,
        lifecycle_state: Optional[str],
        task_id: Optional[str],
        intent_id: Optional[str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        row = DigitalTwinEventJournal(
            twin_type=str(twin_kind),
            twin_id=str(twin_id),
            event_type=str(event_type),
            revision_stage=str(revision_stage),
            lifecycle_state=str(lifecycle_state) if lifecycle_state is not None else None,
            task_id=self._coerce_uuid(task_id),
            intent_id=str(intent_id) if intent_id is not None else None,
            payload=dict(payload or {}),
        )
        session.add(row)
        flushed = session.flush()
        if inspect.isawaitable(flushed):
            await flushed
        return self._row_to_dict(row)

    async def list_events(
        self,
        session,
        *,
        twin_type: str,
        twin_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows = (
            await session.execute(
                select(DigitalTwinEventJournal)
                .where(
                    DigitalTwinEventJournal.twin_type == str(twin_type),
                    DigitalTwinEventJournal.twin_id == str(twin_id),
                )
                .order_by(DigitalTwinEventJournal.recorded_at.desc())
                .limit(max(1, min(int(limit), 500)))
            )
        ).scalars().all()
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: DigitalTwinEventJournal) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "twin_type": row.twin_type,
            "twin_id": row.twin_id,
            "event_type": row.event_type,
            "revision_stage": row.revision_stage,
            "lifecycle_state": row.lifecycle_state,
            "task_id": str(row.task_id) if row.task_id is not None else None,
            "intent_id": row.intent_id,
            "payload": dict(row.payload or {}),
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        }

    def _coerce_uuid(self, value: Optional[str]) -> Optional[uuid.UUID]:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None


class CustodyGraphDAO:
    """Idempotent persistence helper for graph nodes and append-only edges."""

    async def upsert_node(
        self,
        session,
        *,
        node_id: str,
        node_kind: str,
        subject_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = (
            await session.execute(
                select(CustodyGraphNode).where(CustodyGraphNode.node_id == str(node_id))
            )
        ).scalars().first()
        if row is None:
            row = CustodyGraphNode(
                node_id=str(node_id),
                node_kind=str(node_kind),
                subject_id=str(subject_id) if subject_id is not None else None,
                payload=dict(payload or {}),
            )
            session.add(row)
            await session.flush()
            return self._node_to_dict(row)

        row.node_kind = str(node_kind)
        if subject_id is not None:
            row.subject_id = str(subject_id)
        if payload:
            merged = dict(row.payload or {})
            merged.update(dict(payload))
            row.payload = merged
        await session.flush()
        return self._node_to_dict(row)

    async def append_edge(
        self,
        session,
        *,
        edge_id: str,
        edge_kind: str,
        from_node_id: str,
        to_node_id: str,
        source_ref: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = (
            await session.execute(
                select(CustodyGraphEdge).where(CustodyGraphEdge.edge_id == str(edge_id))
            )
        ).scalars().first()
        if row is None:
            row = CustodyGraphEdge(
                edge_id=str(edge_id),
                edge_kind=str(edge_kind),
                from_node_id=str(from_node_id),
                to_node_id=str(to_node_id),
                source_ref=str(source_ref) if source_ref is not None else None,
                payload=dict(payload or {}),
            )
            session.add(row)
            await session.flush()
            return self._edge_to_dict(row)

        return self._edge_to_dict(row)

    async def list_nodes(self, session, *, node_ids: Sequence[str]) -> List[Dict[str, Any]]:
        normalized = [str(node_id) for node_id in node_ids if str(node_id).strip()]
        if not normalized:
            return []
        rows = (
            await session.execute(
                select(CustodyGraphNode).where(CustodyGraphNode.node_id.in_(normalized))
            )
        ).scalars().all()
        return [self._node_to_dict(row) for row in rows]

    async def list_edges_for_nodes(self, session, *, node_ids: Sequence[str]) -> List[Dict[str, Any]]:
        normalized = [str(node_id) for node_id in node_ids if str(node_id).strip()]
        if not normalized:
            return []
        rows = (
            await session.execute(
                select(CustodyGraphEdge).where(
                    (CustodyGraphEdge.from_node_id.in_(normalized))
                    | (CustodyGraphEdge.to_node_id.in_(normalized))
                )
            )
        ).scalars().all()
        return [self._edge_to_dict(row) for row in rows]

    def _node_to_dict(self, row: CustodyGraphNode) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "node_id": row.node_id,
            "node_kind": row.node_kind,
            "subject_id": row.subject_id,
            "payload": dict(row.payload or {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _edge_to_dict(self, row: CustodyGraphEdge) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "edge_id": row.edge_id,
            "edge_kind": row.edge_kind,
            "from_node_id": row.from_node_id,
            "to_node_id": row.to_node_id,
            "source_ref": row.source_ref,
            "payload": dict(row.payload or {}),
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        }


class CustodyTransitionDAO:
    """Append-only lineage event helper for governed custody transitions."""

    async def append_transition_event(self, session, **payload: Any) -> Dict[str, Any]:
        transition_event_id = str(payload["transition_event_id"])
        row = (
            await session.execute(
                select(CustodyTransitionEvent).where(
                    CustodyTransitionEvent.transition_event_id == transition_event_id
                )
            )
        ).scalars().first()
        if row is None:
            row = CustodyTransitionEvent(
                transition_event_id=transition_event_id,
                asset_id=str(payload["asset_id"]),
                intent_id=self._coerce_str(payload.get("intent_id")),
                task_id=self._coerce_uuid(payload.get("task_id")),
                token_id=self._coerce_str(payload.get("token_id")),
                authority_source=str(payload.get("authority_source") or "unknown"),
                transition_seq=int(payload.get("transition_seq") or 0),
                from_zone=self._coerce_str(payload.get("from_zone")),
                to_zone=self._coerce_str(payload.get("to_zone")),
                actor_agent_id=self._coerce_str(payload.get("actor_agent_id")),
                actor_organ_id=self._coerce_str(payload.get("actor_organ_id")),
                endpoint_id=self._coerce_str(payload.get("endpoint_id")),
                receipt_hash=self._coerce_str(payload.get("receipt_hash")),
                receipt_nonce=self._coerce_str(payload.get("receipt_nonce")),
                receipt_counter=(
                    int(payload.get("receipt_counter"))
                    if payload.get("receipt_counter") is not None
                    else None
                ),
                previous_transition_event_id=self._coerce_str(payload.get("previous_transition_event_id")),
                previous_receipt_hash=self._coerce_str(payload.get("previous_receipt_hash")),
                evidence_bundle_id=self._coerce_str(payload.get("evidence_bundle_id")),
                policy_receipt_id=self._coerce_str(payload.get("policy_receipt_id")),
                transition_receipt_id=self._coerce_str(payload.get("transition_receipt_id")),
                lineage_status=str(payload.get("lineage_status") or "authoritative"),
                source_registration_id=self._coerce_str(payload.get("source_registration_id")),
                audit_record_id=self._coerce_str(payload.get("audit_record_id")),
                details=dict(payload.get("details") or {}),
            )
            session.add(row)
            await session.flush()
        return self._row_to_dict(row)

    async def get_latest_for_asset(self, session, *, asset_id: str) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(CustodyTransitionEvent)
                .where(CustodyTransitionEvent.asset_id == str(asset_id))
                .order_by(CustodyTransitionEvent.transition_seq.desc(), CustodyTransitionEvent.recorded_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_for_asset(self, session, *, asset_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows = (
            await session.execute(
                select(CustodyTransitionEvent)
                .where(CustodyTransitionEvent.asset_id == str(asset_id))
                .order_by(CustodyTransitionEvent.transition_seq.asc(), CustodyTransitionEvent.recorded_at.asc())
                .limit(max(1, min(int(limit), 500)))
            )
        ).scalars().all()
        return [self._row_to_dict(row) for row in rows]

    async def get_by_transition_event_id(self, session, *, transition_event_id: str) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(CustodyTransitionEvent).where(
                    CustodyTransitionEvent.transition_event_id == str(transition_event_id)
                )
            )
        ).scalars().first()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def search(
        self,
        session,
        *,
        asset_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        token_id: Optional[str] = None,
        zone: Optional[str] = None,
        actor_agent_id: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = select(CustodyTransitionEvent)
        if asset_id:
            query = query.where(CustodyTransitionEvent.asset_id == str(asset_id))
        if intent_id:
            query = query.where(CustodyTransitionEvent.intent_id == str(intent_id))
        if task_id:
            query = query.where(CustodyTransitionEvent.task_id == self._coerce_uuid(task_id))
        if token_id:
            query = query.where(CustodyTransitionEvent.token_id == str(token_id))
        if zone:
            query = query.where(
                (CustodyTransitionEvent.from_zone == str(zone))
                | (CustodyTransitionEvent.to_zone == str(zone))
            )
        if actor_agent_id:
            query = query.where(CustodyTransitionEvent.actor_agent_id == str(actor_agent_id))
        if endpoint_id:
            query = query.where(CustodyTransitionEvent.endpoint_id == str(endpoint_id))
        if from_time is not None:
            query = query.where(CustodyTransitionEvent.recorded_at >= from_time)
        if to_time is not None:
            query = query.where(CustodyTransitionEvent.recorded_at <= to_time)
        rows = (
            await session.execute(
                query.order_by(CustodyTransitionEvent.recorded_at.desc()).limit(max(1, min(int(limit), 500)))
            )
        ).scalars().all()
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: CustodyTransitionEvent) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "transition_event_id": row.transition_event_id,
            "asset_id": row.asset_id,
            "intent_id": row.intent_id,
            "task_id": str(row.task_id) if row.task_id is not None else None,
            "token_id": row.token_id,
            "authority_source": row.authority_source,
            "transition_seq": int(row.transition_seq or 0),
            "from_zone": row.from_zone,
            "to_zone": row.to_zone,
            "actor_agent_id": row.actor_agent_id,
            "actor_organ_id": row.actor_organ_id,
            "endpoint_id": row.endpoint_id,
            "receipt_hash": row.receipt_hash,
            "receipt_nonce": row.receipt_nonce,
            "receipt_counter": row.receipt_counter,
            "previous_transition_event_id": row.previous_transition_event_id,
            "previous_receipt_hash": row.previous_receipt_hash,
            "evidence_bundle_id": row.evidence_bundle_id,
            "policy_receipt_id": row.policy_receipt_id,
            "transition_receipt_id": row.transition_receipt_id,
            "lineage_status": row.lineage_status,
            "source_registration_id": row.source_registration_id,
            "audit_record_id": row.audit_record_id,
            "details": dict(row.details or {}),
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        }

    def _coerce_uuid(self, value: Optional[str]) -> Optional[uuid.UUID]:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None

    def _coerce_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text_value = str(value).strip()
        return text_value or None


class CustodyDisputeDAO:
    """Persistence helper for custody dispute cases and append-only events."""

    async def create_case(
        self,
        session,
        *,
        dispute_id: str,
        status: str,
        title: str,
        summary: Optional[str] = None,
        asset_id: Optional[str] = None,
        opened_by: Optional[str] = None,
        references: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = CustodyDisputeCase(
            dispute_id=str(dispute_id),
            status=str(status),
            title=str(title),
            summary=str(summary) if summary is not None else None,
            asset_id=str(asset_id) if asset_id is not None else None,
            opened_by=str(opened_by) if opened_by is not None else None,
            reference_map=dict(references or {}),
            details=dict(details or {}),
        )
        session.add(row)
        await session.flush()
        return self._case_to_dict(row)

    async def get_case(self, session, *, dispute_id: str) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(CustodyDisputeCase).where(CustodyDisputeCase.dispute_id == str(dispute_id))
            )
        ).scalars().first()
        if row is None:
            return None
        return self._case_to_dict(row)

    async def list_cases(
        self,
        session,
        *,
        status: Optional[str] = None,
        asset_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = select(CustodyDisputeCase)
        if status:
            query = query.where(CustodyDisputeCase.status == str(status))
        if asset_id:
            query = query.where(CustodyDisputeCase.asset_id == str(asset_id))
        rows = (
            await session.execute(
                query.order_by(CustodyDisputeCase.recorded_at.desc()).limit(max(1, min(int(limit), 500)))
            )
        ).scalars().all()
        return [self._case_to_dict(row) for row in rows]

    async def append_event(
        self,
        session,
        *,
        dispute_id: str,
        event_type: str,
        actor_id: Optional[str] = None,
        note: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        case_row = (
            await session.execute(
                select(CustodyDisputeCase).where(CustodyDisputeCase.dispute_id == str(dispute_id))
            )
        ).scalars().first()
        if case_row is None:
            raise ValueError(f"Unknown dispute_id '{dispute_id}'")
        if status is not None:
            case_row.status = str(status)
        event = CustodyDisputeEvent(
            dispute_case_id=case_row.id,
            dispute_id=case_row.dispute_id,
            event_type=str(event_type),
            status=str(status) if status is not None else case_row.status,
            actor_id=str(actor_id) if actor_id is not None else None,
            note=str(note) if note is not None else None,
            payload=dict(payload or {}),
        )
        session.add(event)
        await session.flush()
        return self._event_to_dict(event)

    async def resolve_case(
        self,
        session,
        *,
        dispute_id: str,
        status: str,
        resolved_by: Optional[str],
        resolution: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(CustodyDisputeCase).where(CustodyDisputeCase.dispute_id == str(dispute_id))
            )
        ).scalars().first()
        if row is None:
            return None
        row.status = str(status)
        row.resolved_by = str(resolved_by) if resolved_by is not None else None
        row.resolution = str(resolution) if resolution is not None else None
        row.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        return self._case_to_dict(row)

    async def list_events(self, session, *, dispute_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows = (
            await session.execute(
                select(CustodyDisputeEvent)
                .where(CustodyDisputeEvent.dispute_id == str(dispute_id))
                .order_by(CustodyDisputeEvent.recorded_at.asc())
                .limit(max(1, min(int(limit), 500)))
            )
        ).scalars().all()
        return [self._event_to_dict(row) for row in rows]

    def _case_to_dict(self, row: CustodyDisputeCase) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "dispute_id": row.dispute_id,
            "status": row.status,
            "asset_id": row.asset_id,
            "title": row.title,
            "summary": row.summary,
            "opened_by": row.opened_by,
            "resolved_by": row.resolved_by,
            "resolution": row.resolution,
            "references": dict(row.reference_map or {}),
            "details": dict(row.details or {}),
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }

    def _event_to_dict(self, row: CustodyDisputeEvent) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "dispute_case_id": str(row.dispute_case_id),
            "dispute_id": row.dispute_id,
            "event_type": row.event_type,
            "status": row.status,
            "actor_id": row.actor_id,
            "note": row.note,
            "payload": dict(row.payload or {}),
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        }


class AssetCustodyStateDAO:
    """Mutable authoritative state helper for asset custody/location."""

    async def upsert_snapshot(
        self,
        session,
        *,
        asset_id: str,
        source_registration_id: Optional[str] = None,
        lot_id: Optional[str] = None,
        source_claim_id: Optional[str] = None,
        producer_id: Optional[str] = None,
        current_zone: Optional[str] = None,
        is_quarantined: Optional[bool] = None,
        authority_source: str,
        last_transition_seq: Optional[int] = None,
        last_receipt_hash: Optional[str] = None,
        last_receipt_nonce: Optional[str] = None,
        last_receipt_counter: Optional[int] = None,
        last_endpoint_id: Optional[str] = None,
        last_task_id: Optional[str] = None,
        last_intent_id: Optional[str] = None,
        last_token_id: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        row = (
            await session.execute(
                select(AssetCustodyState).where(AssetCustodyState.asset_id == str(asset_id))
            )
        ).scalars().first()

        if row is None:
            row = AssetCustodyState(
                asset_id=str(asset_id),
                source_registration_id=source_registration_id,
                lot_id=lot_id,
                source_claim_id=source_claim_id,
                producer_id=producer_id,
                current_zone=current_zone,
                is_quarantined=bool(is_quarantined) if is_quarantined is not None else False,
                authority_source=str(authority_source),
                last_transition_seq=int(last_transition_seq or 0),
                last_receipt_hash=last_receipt_hash,
                last_receipt_nonce=last_receipt_nonce,
                last_receipt_counter=int(last_receipt_counter) if last_receipt_counter is not None else None,
                last_endpoint_id=last_endpoint_id,
                last_task_id=self._coerce_uuid(last_task_id),
                last_intent_id=last_intent_id,
                last_token_id=last_token_id,
                updated_by=updated_by,
            )
            session.add(row)
            await session.flush()
            return self._to_dict(row)

        if source_registration_id is not None:
            row.source_registration_id = str(source_registration_id)
        if lot_id is not None:
            row.lot_id = str(lot_id)
        if source_claim_id is not None:
            row.source_claim_id = str(source_claim_id)
        if producer_id is not None:
            row.producer_id = str(producer_id)
        if current_zone is not None:
            row.current_zone = str(current_zone)
        if is_quarantined is not None:
            row.is_quarantined = bool(is_quarantined)
        row.authority_source = str(authority_source)
        if last_transition_seq is not None:
            row.last_transition_seq = int(last_transition_seq)
        if last_receipt_hash is not None:
            row.last_receipt_hash = str(last_receipt_hash)
        if last_receipt_nonce is not None:
            row.last_receipt_nonce = str(last_receipt_nonce)
        if last_receipt_counter is not None:
            row.last_receipt_counter = int(last_receipt_counter)
        if last_endpoint_id is not None:
            row.last_endpoint_id = str(last_endpoint_id)
        if last_task_id is not None:
            row.last_task_id = self._coerce_uuid(last_task_id)
        if last_intent_id is not None:
            row.last_intent_id = str(last_intent_id)
        if last_token_id is not None:
            row.last_token_id = str(last_token_id)
        if updated_by is not None:
            row.updated_by = str(updated_by)
        await session.flush()
        return self._to_dict(row)

    def _to_dict(self, row: AssetCustodyState) -> Dict[str, Any]:
        return {
            "asset_id": str(row.asset_id),
            "source_registration_id": row.source_registration_id,
            "lot_id": row.lot_id,
            "source_claim_id": row.source_claim_id,
            "producer_id": row.producer_id,
            "current_zone": row.current_zone,
            "is_quarantined": bool(row.is_quarantined),
            "authority_source": row.authority_source,
            "last_transition_seq": int(getattr(row, "last_transition_seq", 0) or 0),
            "last_receipt_hash": row.last_receipt_hash,
            "last_receipt_nonce": row.last_receipt_nonce,
            "last_receipt_counter": row.last_receipt_counter,
            "last_endpoint_id": row.last_endpoint_id,
            "last_task_id": str(row.last_task_id) if row.last_task_id is not None else None,
            "last_intent_id": row.last_intent_id,
            "last_token_id": row.last_token_id,
            "updated_by": row.updated_by,
        }

    async def get_snapshot(self, session, *, asset_id: str) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(AssetCustodyState).where(AssetCustodyState.asset_id == str(asset_id))
            )
        ).scalars().first()
        if row is None:
            return None
        return self._to_dict(row)

    def _coerce_uuid(self, value: Optional[str]) -> Optional[uuid.UUID]:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None
