from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

import httpx  # pyright: ignore[reportMissingImports]

from seedcore.infra.kafka.config import consumer_conf, kafka_consumer_group_id
from seedcore.infra.kafka.consumer import KafkaConsumer
from seedcore.infra.kafka.delegated_intent import DelegatedIntentPayload
from seedcore.infra.kafka.topics import TOPIC_INTENT_V1

logger = logging.getLogger(__name__)

_DEFAULT_ARTIFACTS_DIR = "artifacts/kafka_streams"


def _runtime_base_url() -> str:
    return (os.getenv("SEEDCORE_API") or "http://127.0.0.1:8002").strip().rstrip("/")


def _truthy_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _artifacts_log_path() -> Path:
    raw = os.getenv("SEEDCORE_KAFKA_INTENT_INGRESS_LOG_DIR", _DEFAULT_ARTIFACTS_DIR).strip()
    return Path(raw)


async def _post_json(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    payload: Mapping[str, Any],
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.request(method, url, json=dict(payload), params=dict(params or {}))
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{method} {url} returned unexpected payload type")
    return body


async def process_delegated_intent_event(
    event: Mapping[str, Any],
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    payload_raw = event.get("payload") if isinstance(event, Mapping) else None
    if not isinstance(payload_raw, Mapping):
        raise ValueError("Kafka event missing payload object")

    delegated = DelegatedIntentPayload.model_validate(payload_raw)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=float(os.getenv("SEEDCORE_PLUGIN_TIMEOUT", "15.0")))
    base_url = _runtime_base_url()
    preflight_required = _truthy_env("SEEDCORE_KAFKA_INTENT_INGRESS_PREFLIGHT_REQUIRED", default=True)
    no_execute = _truthy_env("SEEDCORE_KAFKA_INTENT_INGRESS_NO_EXECUTE", default=False)
    try:
        preflight = await _post_json(
            client,
            method="POST",
            url=f"{base_url}/api/v1/owner-context/preflight",
            payload=delegated.owner_context_preflight.model_dump(mode="json"),
        )
        if preflight_required and not bool(preflight.get("ok")):
            return {
                "status": "rejected_preflight",
                "request_id": delegated.request_id,
                "workflow_id": delegated.workflow_id,
                "correlation_id": delegated.correlation_id,
                "preflight": preflight,
            }

        evaluation = await _post_json(
            client,
            method="POST",
            url=f"{base_url}/api/v1/agent-actions/evaluate",
            payload=delegated.gateway_request.model_dump(mode="json"),
            params={"debug": "false", "no_execute": "true" if no_execute else "false"},
        )
        return {
            "status": "evaluated",
            "request_id": delegated.request_id,
            "workflow_id": delegated.workflow_id,
            "correlation_id": delegated.correlation_id,
            "preflight": preflight,
            "evaluation": {
                "decision": (
                    evaluation.get("decision")
                    if isinstance(evaluation.get("decision"), dict)
                    else {}
                ),
                "request_id": evaluation.get("request_id"),
                "trust_gaps": evaluation.get("trust_gaps"),
                "required_approvals": evaluation.get("required_approvals"),
            },
        }
    finally:
        if owns_client:
            await client.aclose()


def _format_record(*, topic: str, event: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "request_id": result.get("request_id"),
        "status": result.get("status"),
        "workflow_id": result.get("workflow_id"),
        "correlation_id": result.get("correlation_id"),
        "event": dict(event),
        "result": dict(result),
    }


def run_delegated_intent_ingress(
    *,
    log_file: TextIO | None = None,
    append_file_path: Path | None = None,
) -> None:
    conf = consumer_conf(group_id=kafka_consumer_group_id("seedcore-intent-ingress"))
    consumer = KafkaConsumer(conf, [TOPIC_INTENT_V1])

    append_fp: TextIO | None = None
    if append_file_path is not None:
        append_file_path.parent.mkdir(parents=True, exist_ok=True)
        append_fp = append_file_path.open("a", encoding="utf-8")

    stop = False

    def _handle_sig(_sig, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    logger.info("delegated intent ingress subscribed: %s", TOPIC_INTENT_V1)

    try:
        while not stop:
            msg = consumer.poll_raw(timeout=1.0)
            if msg is None:
                continue
            try:
                event = consumer.decode(msg)
            except json.JSONDecodeError as exc:
                logger.warning("skip non-json delegated intent event: %s", exc)
                consumer.commit(msg)
                continue

            try:
                result = asyncio.run(process_delegated_intent_event(event))
            except Exception as exc:
                logger.warning("delegated intent ingress processing failed; message left uncommitted: %s", exc)
                continue

            line = _format_record(topic=msg.topic(), event=event, result=result)
            logger.info("delegated_intent %s", json.dumps(line, default=str))
            if log_file is not None:
                log_file.write(json.dumps(line, default=str) + "\n")
                log_file.flush()
            if append_fp is not None:
                append_fp.write(json.dumps(line, default=str) + "\n")
                append_fp.flush()
            consumer.commit(msg)
    finally:
        consumer.close()
        if append_fp is not None:
            append_fp.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    path = _artifacts_log_path() / "delegated_intent_ingress.jsonl"
    if _truthy_env("SEEDCORE_KAFKA_INTENT_INGRESS_APPEND_FILE"):
        run_delegated_intent_ingress(append_file_path=path)
    else:
        run_delegated_intent_ingress()


if __name__ == "__main__":
    main()
