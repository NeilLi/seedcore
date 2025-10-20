"""Convenience helpers for extracting eventizer features from task payloads."""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, MutableMapping, Optional

from seedcore.ops.eventizer.fast_eventizer import process_text_fast

logger = logging.getLogger(__name__)

_TEXT_PARAM_KEYS: tuple[str, ...] = (
    "eventizer_text",
    "text",
    "body",
    "prompt",
    "query",
    "message",
    "input_text",
    "content",
)


def _coerce_mapping(value: Any) -> MutableMapping[str, Any]:
    if isinstance(value, MutableMapping):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _extract_params(payload: Any) -> MutableMapping[str, Any]:
    if hasattr(payload, "params"):
        params = getattr(payload, "params")
        if isinstance(params, Mapping):
            return dict(params)
    if isinstance(payload, Mapping):
        params = payload.get("params")
        if isinstance(params, Mapping):
            return dict(params)
    return {}


def _extract_text(payload: Any, params: Mapping[str, Any]) -> Optional[str]:
    for key in _TEXT_PARAM_KEYS:
        candidate = params.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    description = None
    if hasattr(payload, "description"):
        description = getattr(payload, "description")
    elif isinstance(payload, Mapping):
        description = payload.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return None


def features_from_payload(payload: Any) -> Dict[str, Any]:
    """Return fast eventizer features for *payload* (best-effort)."""

    params = _extract_params(payload)
    text = _extract_text(payload, params)
    if not text:
        return {}

    task_type = ""
    domain = ""
    if hasattr(payload, "type"):
        task_type = getattr(payload, "type") or ""
    elif isinstance(params, Mapping):
        task_type = params.get("type", "")
    if hasattr(payload, "domain"):
        domain = getattr(payload, "domain") or ""
    elif isinstance(params, Mapping):
        domain = params.get("domain", "")

    try:
        result = process_text_fast(text, task_type=task_type, domain=domain)
    except Exception as exc:  # pragma: no cover - defensive logging around optional dependency
        logger.warning(
            "Fast eventizer processing failed for task %s: %s",
            getattr(payload, "task_id", None),
            exc,
        )
        return {}

    result = dict(result)
    result["text"] = text

    # Normalize nested mappings so downstream callers can safely mutate them
    event_tags = result.get("event_tags")
    attributes = result.get("attributes")
    confidence = result.get("confidence")
    if event_tags is not None:
        result["event_tags"] = _coerce_mapping(event_tags)
    if attributes is not None:
        result["attributes"] = _coerce_mapping(attributes)
    if confidence is not None:
        result["confidence"] = _coerce_mapping(confidence)

    return result

__all__ = ["features_from_payload"]
