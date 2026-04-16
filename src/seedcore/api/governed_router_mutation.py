from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.coordinator.dao import GovernedExecutionAuditDAO

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouterGovernedIds:
    intent_id: str
    token_id: str
    task_id: str


def derive_router_governed_ids(
    *,
    namespace: str,
    operation: str,
    target_ref: str,
    task_prefix: str,
) -> RouterGovernedIds:
    intent_id = f"{namespace}:{operation}:{target_ref}"
    token_id = str(uuid.uuid5(uuid.NAMESPACE_URL, intent_id))
    task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{task_prefix}:{target_ref}"))
    return RouterGovernedIds(intent_id=intent_id, token_id=token_id, task_id=task_id)


def build_router_audit_callbacks(
    *,
    session: AsyncSession,
    dao: GovernedExecutionAuditDAO,
    ids: RouterGovernedIds,
    record_type: str,
    action_type: str,
    target_ref: str,
    actor_ref: Optional[str],
    actor_organ_id: str,
    policy_source: str,
) -> tuple[
    Callable[[], Awaitable[tuple[Optional[str], Optional[int]]]],
    Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
]:
    async def _load_previous_chain() -> tuple[str | None, int | None]:
        try:
            latest = await dao.get_latest_for_task(session, task_id=ids.task_id)
        except Exception:
            logger.warning(
                "Router governed audit chain lookup failed task_id=%s record_type=%s",
                ids.task_id,
                record_type,
                exc_info=True,
            )
            return None, None
        if not isinstance(latest, dict):
            return None, None
        evidence_bundle = latest.get("evidence_bundle")
        if not isinstance(evidence_bundle, dict):
            return None, None
        previous = evidence_bundle.get("mutation_receipt")
        if not isinstance(previous, dict):
            return None, None
        prev_hash = previous.get("payload_hash")
        prev_counter = previous.get("receipt_counter")
        return (
            str(prev_hash) if isinstance(prev_hash, str) and prev_hash else None,
            int(prev_counter) if isinstance(prev_counter, int) else None,
        )

    async def _append_audit(evidence_bundle: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await dao.append_record(
                session,
                task_id=ids.task_id,
                record_type=record_type,
                intent_id=ids.intent_id,
                token_id=ids.token_id,
                action_intent={
                    "intent_id": ids.intent_id,
                    "action": {"type": action_type},
                    "resource": {"asset_id": target_ref},
                },
                policy_case={},
                policy_decision={"allowed": True, "source": policy_source},
                policy_receipt={},
                evidence_bundle=evidence_bundle,
                actor_agent_id=actor_ref,
                actor_organ_id=actor_organ_id,
            )
        except Exception:
            logger.warning(
                "Router governed audit append failed task_id=%s record_type=%s",
                ids.task_id,
                record_type,
                exc_info=True,
            )
            return {"persisted": False}

    return _load_previous_chain, _append_audit
