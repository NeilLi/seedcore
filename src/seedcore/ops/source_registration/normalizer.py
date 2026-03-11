from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


VISION_ARTIFACT_TYPES = {
    "honeycomb_macro_image",
    "seal_macro_image",
}

TELEMETRY_MEASUREMENT_TYPES = {
    "oxygen_level",
    "humidity",
    "gps",
}

BIOSIGNATURE_MEASUREMENT_TYPES = {
    "pollen_count",
    "purity_score",
    "spectral_match_score",
}


@dataclass(frozen=True)
class SourceRegistrationNormalizationResult:
    registration: Dict[str, Any]
    multimodal_context: Dict[str, Any]
    eventizer_text: str
    cognitive_enrichment_required: bool


def normalize_source_registration_context(
    registration: Dict[str, Any] | None,
    *,
    tracking_events: Optional[Iterable[Dict[str, Any]]] = None,
    multimodal_context: Optional[Dict[str, Any]] = None,
    task_description: str = "",
) -> SourceRegistrationNormalizationResult:
    raw_registration = dict(registration or {})
    normalized_events = _normalize_tracking_events(
        tracking_events
        if tracking_events is not None
        else raw_registration.get("tracking_events")
    )
    ingress_event_ids = _normalize_id_list(
        raw_registration.get("ingress_event_ids"),
        fallback=[event["id"] for event in normalized_events if event.get("id")],
    )
    artifacts = _normalize_artifacts(raw_registration.get("artifacts"))
    measurements = _normalize_measurements(raw_registration.get("measurements"))

    operator_commands = _extract_operator_commands(normalized_events)
    stream_kinds = _collect_stream_kinds(
        normalized_events,
        artifacts=artifacts,
        measurements=measurements,
        operator_commands=operator_commands,
        existing=raw_registration.get("normalization", {}).get("stream_kinds")
        if isinstance(raw_registration.get("normalization"), dict)
        else None,
    )
    event_types = _collect_event_types(
        normalized_events,
        existing=raw_registration.get("normalization", {}).get("event_types")
        if isinstance(raw_registration.get("normalization"), dict)
        else None,
    )
    modalities = _derive_modalities(
        raw_registration=raw_registration,
        artifacts=artifacts,
        measurements=measurements,
        operator_commands=operator_commands,
    )
    artifact_types = [artifact["artifact_type"] for artifact in artifacts]
    measurement_types = list(measurements.keys())
    eventizer_text = _build_eventizer_text(
        task_description=task_description,
        registration=raw_registration,
        artifacts=artifacts,
        measurements=measurements,
        operator_commands=operator_commands,
    )

    cognitive_enrichment_required = (
        len(modalities) >= 3
        or ("vision" in modalities and "sensor" in modalities)
        or ("vision" in modalities and "biosignature" in modalities)
    )

    normalization_meta = {}
    if isinstance(raw_registration.get("normalization"), dict):
        normalization_meta.update(raw_registration["normalization"])
    normalization_meta.update(
        {
            "source": (
                normalization_meta.get("source")
                or ("tracking_event_projection" if normalized_events else "task_payload")
            ),
            "ingress_event_ids": ingress_event_ids,
            "tracking_event_count": len(normalized_events),
            "stream_kinds": stream_kinds,
            "event_types": event_types,
            "artifact_types": artifact_types,
            "measurement_types": measurement_types,
            "modalities": modalities,
            "operator_commands": operator_commands,
            "summary_text": eventizer_text,
            "cognitive_enrichment_required": cognitive_enrichment_required,
        }
    )

    normalized_registration = dict(raw_registration)
    normalized_registration["artifacts"] = artifacts
    normalized_registration["measurements"] = measurements
    normalized_registration["tracking_events"] = normalized_events
    normalized_registration["ingress_event_ids"] = ingress_event_ids
    normalized_registration["normalization"] = normalization_meta

    normalized_multimodal = _merge_multimodal_context(
        multimodal_context or {},
        artifacts=artifacts,
        measurements=measurements,
        ingress_event_ids=ingress_event_ids,
        normalization_meta=normalization_meta,
    )

    return SourceRegistrationNormalizationResult(
        registration=normalized_registration,
        multimodal_context=normalized_multimodal,
        eventizer_text=eventizer_text,
        cognitive_enrichment_required=cognitive_enrichment_required,
    )


def _normalize_tracking_events(events: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(events, Iterable) or isinstance(events, (dict, str, bytes)):
        return normalized
    for event in events:
        if not isinstance(event, dict):
            continue
        normalized_event = {
            "id": _string_or_none(event.get("id")),
            "event_type": _normalize_token(event.get("event_type")),
            "source_kind": _normalize_token(event.get("source_kind")),
            "payload": dict(event.get("payload") or {}),
            "captured_at": _string_or_none(event.get("captured_at")),
            "producer_id": _string_or_none(event.get("producer_id")),
            "device_id": _string_or_none(event.get("device_id")),
            "operator_id": _string_or_none(event.get("operator_id")),
            "correlation_id": _string_or_none(event.get("correlation_id")),
            "snapshot_id": event.get("snapshot_id"),
        }
        normalized.append(normalized_event)
    return normalized


def _normalize_artifacts(artifacts: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(artifacts, list):
        return normalized
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        normalized.append(
            {
                "artifact_id": _string_or_none(artifact.get("artifact_id")),
                "artifact_type": _normalize_token(
                    artifact.get("artifact_type"),
                    default="unknown_artifact",
                ),
                "uri": str(artifact.get("uri") or "").strip(),
                "sha256": str(artifact.get("sha256") or "").strip().lower(),
                "captured_at": _string_or_none(artifact.get("captured_at")),
                "captured_by": _string_or_none(artifact.get("captured_by")),
                "device_id": _string_or_none(artifact.get("device_id")),
                "content_type": _string_or_none(artifact.get("content_type")),
                "metadata": dict(artifact.get("metadata") or {}),
            }
        )
    return normalized


def _normalize_measurements(measurements: Any) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    if not isinstance(measurements, dict):
        return normalized
    for measurement_type, payload in measurements.items():
        if not isinstance(payload, dict):
            continue
        normalized_type = _normalize_token(
            payload.get("measurement_type") or measurement_type
        )
        metadata = dict(payload.get("metadata") or {})
        for key in ("lat", "lon", "altitude_meters"):
            if payload.get(key) is not None:
                metadata.setdefault(key, payload.get(key))
        normalized_value = {
            "measurement_id": _string_or_none(payload.get("measurement_id")),
            "measurement_type": normalized_type,
            "value": _coerce_float(payload.get("value"), fallback=payload.get("altitude_meters")),
            "unit": str(payload.get("unit") or ("geo" if normalized_type == "gps" else "unitless")).strip().lower(),
            "measured_at": _string_or_none(payload.get("measured_at")),
            "sensor_id": _string_or_none(payload.get("sensor_id")),
            "quality_score": _coerce_float(payload.get("quality_score")),
            "raw_artifact_id": _string_or_none(payload.get("raw_artifact_id")),
            "metadata": metadata,
        }
        if normalized_value["value"] is None:
            continue
        if normalized_type == "gps":
            for key in ("lat", "lon", "altitude_meters"):
                if metadata.get(key) is not None:
                    normalized_value[key] = metadata.get(key)
        normalized[normalized_type] = normalized_value
    return normalized


def _collect_stream_kinds(
    events: List[Dict[str, Any]],
    *,
    artifacts: List[Dict[str, Any]],
    measurements: Dict[str, Dict[str, Any]],
    operator_commands: List[str],
    existing: Any,
) -> List[str]:
    ordered = _normalize_id_list(existing)
    for event in events:
        source_kind = _normalize_token(event.get("source_kind"))
        if source_kind and source_kind not in ordered:
            ordered.append(source_kind)
    if artifacts and "provenance_scan" not in ordered:
        ordered.append("provenance_scan")
    if measurements and "telemetry" not in ordered:
        ordered.append("telemetry")
    if operator_commands and "operator_request" not in ordered:
        ordered.append("operator_request")
    if (
        isinstance(existing, list)
        and any(str(item).strip() for item in existing)
        and "source_declaration" not in ordered
    ):
        # Preserve declaration state when the caller already modeled it.
        ordered.append("source_declaration")
    return ordered


def _collect_event_types(events: List[Dict[str, Any]], *, existing: Any) -> List[str]:
    ordered = _normalize_id_list(existing)
    for event in events:
        event_type = _normalize_token(event.get("event_type"))
        if event_type and event_type not in ordered:
            ordered.append(event_type)
    return ordered


def _derive_modalities(
    *,
    raw_registration: Dict[str, Any],
    artifacts: List[Dict[str, Any]],
    measurements: Dict[str, Dict[str, Any]],
    operator_commands: List[str],
) -> List[str]:
    modalities: List[str] = []
    if raw_registration.get("claimed_origin") or raw_registration.get("collection_site"):
        modalities.append("declaration")
    artifact_types = {artifact["artifact_type"] for artifact in artifacts}
    if artifact_types & VISION_ARTIFACT_TYPES:
        modalities.append("vision")
    if any(name in TELEMETRY_MEASUREMENT_TYPES for name in measurements):
        modalities.append("sensor")
    if any(name in BIOSIGNATURE_MEASUREMENT_TYPES for name in measurements):
        modalities.append("biosignature")
    if operator_commands:
        modalities.append("operator")
    return modalities


def _extract_operator_commands(events: List[Dict[str, Any]]) -> List[str]:
    commands: List[str] = []
    for event in events:
        if event.get("source_kind") != "operator_request":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        command = _normalize_token(payload.get("command") or payload.get("request_type"))
        if command and command not in commands:
            commands.append(command)
    return commands


def _build_eventizer_text(
    *,
    task_description: str,
    registration: Dict[str, Any],
    artifacts: List[Dict[str, Any]],
    measurements: Dict[str, Dict[str, Any]],
    operator_commands: List[str],
) -> str:
    parts: List[str] = []
    task_description = str(task_description or "").strip()
    if task_description:
        parts.append(task_description)

    reg_id = registration.get("registration_id")
    lot_id = registration.get("lot_id")
    producer_id = registration.get("producer_id")
    claim_id = registration.get("source_claim_id")
    header = "Source registration"
    if reg_id:
        header += f" {reg_id}"
    detail_tokens = [token for token in [f"claim {claim_id}" if claim_id else None, f"lot {lot_id}" if lot_id else None, f"producer {producer_id}" if producer_id else None] if token]
    if detail_tokens:
        header += " for " + ", ".join(detail_tokens)
    parts.append(header)

    claimed_origin = registration.get("claimed_origin") if isinstance(registration.get("claimed_origin"), dict) else {}
    if claimed_origin:
        origin_bits: List[str] = []
        if claimed_origin.get("zone_id"):
            origin_bits.append(f"zone {claimed_origin['zone_id']}")
        if claimed_origin.get("site_id"):
            origin_bits.append(f"site {claimed_origin['site_id']}")
        if claimed_origin.get("altitude_meters") is not None:
            origin_bits.append(f"altitude {claimed_origin['altitude_meters']} meters")
        if origin_bits:
            parts.append("Claimed origin " + ", ".join(origin_bits))

    if artifacts:
        parts.append(
            "Artifacts " + ", ".join(artifact["artifact_type"] for artifact in artifacts[:5])
        )

    if measurements:
        measurement_chunks: List[str] = []
        for name, payload in list(measurements.items())[:6]:
            value = payload.get("value")
            unit = payload.get("unit")
            if value is None:
                continue
            measurement_chunks.append(f"{name}={value} {unit}".strip())
        if measurement_chunks:
            parts.append("Measurements " + "; ".join(measurement_chunks))

    if operator_commands:
        parts.append("Operator commands " + ", ".join(operator_commands))

    return ". ".join(part.rstrip(".") for part in parts if part).strip()


def _merge_multimodal_context(
    multimodal_context: Dict[str, Any],
    *,
    artifacts: List[Dict[str, Any]],
    measurements: Dict[str, Dict[str, Any]],
    ingress_event_ids: List[str],
    normalization_meta: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(multimodal_context or {})
    existing_artifacts = merged.get("artifacts")
    merged_artifacts = list(existing_artifacts) if isinstance(existing_artifacts, list) else []
    seen_keys = {
        f"{item.get('sha256')}|{item.get('uri')}"
        for item in merged_artifacts
        if isinstance(item, dict)
    }
    for artifact in artifacts:
        key = f"{artifact.get('sha256')}|{artifact.get('uri')}"
        if key in seen_keys:
            continue
        merged_artifacts.append(
            {
                "artifact_type": artifact.get("artifact_type"),
                "uri": artifact.get("uri"),
                "sha256": artifact.get("sha256"),
                "device_id": artifact.get("device_id"),
            }
        )
        seen_keys.add(key)
    if merged_artifacts:
        merged["artifacts"] = merged_artifacts

    if not merged.get("modality"):
        modalities = normalization_meta.get("modalities") or []
        if "vision" in modalities:
            merged["modality"] = "vision"
        elif "sensor" in modalities or "biosignature" in modalities:
            merged["modality"] = "sensor"

    merged["source_registration"] = {
        "ingress_event_ids": ingress_event_ids,
        "artifact_types": normalization_meta.get("artifact_types") or [],
        "measurement_types": list(measurements.keys()),
        "stream_kinds": normalization_meta.get("stream_kinds") or [],
        "modalities": normalization_meta.get("modalities") or [],
    }
    return merged


def _normalize_id_list(values: Any, *, fallback: Optional[List[str]] = None) -> List[str]:
    normalized: List[str] = []
    iterable = values if isinstance(values, list) else fallback or []
    for value in iterable:
        string_value = _string_or_none(value)
        if string_value and string_value not in normalized:
            normalized.append(string_value)
    return normalized


def _normalize_token(value: Any, default: str = "") -> str:
    if value is None:
        return default
    token = str(value).strip().lower().replace(" ", "_")
    return token or default


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _coerce_float(value: Any, *, fallback: Any = None) -> Optional[float]:
    target = value if value is not None else fallback
    if target is None:
        return None
    try:
        return float(target)
    except (TypeError, ValueError):
        return None
