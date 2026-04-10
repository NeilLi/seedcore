from __future__ import annotations

import logging
import os
import threading
from typing import Any

from seedcore.infra.kafka.config import kafka_producer_service_name, producer_conf
from seedcore.infra.kafka.envelope import build_stream_envelope
from seedcore.infra.kafka.producer import KafkaProducerBestEffort
from seedcore.infra.kafka.topics import TOPIC_POLICY_OUTCOME_V1
from seedcore.models.pdp_hot_path import HotPathEvaluateRequest, HotPathEvaluateResponse

logger = logging.getLogger(__name__)

_POLICY_OUTCOME_ENABLE_ENV = "SEEDCORE_KAFKA_POLICY_OUTCOME_ENABLE"

_producer_lock = threading.Lock()
_producer: KafkaProducerBestEffort | None = None
_producer_init_failed = False


def _policy_outcome_enabled() -> bool:
    return os.getenv(_POLICY_OUTCOME_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _get_best_effort_producer() -> KafkaProducerBestEffort | None:
    global _producer, _producer_init_failed
    if _producer_init_failed:
        return None
    with _producer_lock:
        if _producer is not None:
            return _producer
        try:
            _producer = KafkaProducerBestEffort(producer_conf())
            return _producer
        except Exception as e:
            _producer_init_failed = True
            logger.warning("Kafka policy outcome producer disabled after init failure: %s", e)
            return None


def _redacted_policy_outcome_payload(
    request: HotPathEvaluateRequest,
    response: HotPathEvaluateResponse,
) -> dict[str, Any]:
    """No execution tokens, full receipts, or signer material — correlation + decision summary only."""
    return {
        "stream": "policy_outcome",
        "payload_schema_version": "seedcore.policy_outcome.hot_path.v0",
        "request_id": response.request_id,
        "intent_id": request.action_intent.intent_id,
        "contract_version": response.contract_version,
        "disposition": response.decision.disposition,
        "reason_code": response.decision.reason_code,
        "allowed": response.decision.allowed,
        "policy_snapshot_ref": response.decision.policy_snapshot_ref,
        "policy_snapshot_hash": response.decision.policy_snapshot_hash,
        "latency_ms": response.latency_ms,
        "decided_at": response.decided_at.isoformat(),
        "trust_gap_count": len(response.trust_gaps),
    }


def publish_pdp_hot_path_policy_outcome_best_effort(
    request: HotPathEvaluateRequest,
    response: HotPathEvaluateResponse,
) -> None:
    """
    After a synchronous PDP hot-path decision, optionally publish a redacted outcome (Phase 2a).
    Fail-open: never raises; logs on failure.
    """
    if not _policy_outcome_enabled():
        return
    prod = _get_best_effort_producer()
    if prod is None:
        return
    try:
        payload = _redacted_policy_outcome_payload(request, response)
        envelope = build_stream_envelope(payload, producer=kafka_producer_service_name())
        prod.send(TOPIC_POLICY_OUTCOME_V1, envelope)
    except Exception as e:
        logger.warning("policy outcome Kafka publish dropped: %s", e)
