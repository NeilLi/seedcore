"""
Phase-3 (authoring / publish-time) validation for RCT-governing PKG snapshots.

Validates compiled decision-graph shape and DB-backed taxonomy/manifest rows before
control-plane activation. Gated by SEEDCORE_PKG_RCT_PUBLISH_VALIDATE on PKGManager.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from seedcore.ops.pkg.authz_graph.compiler import TRANSFER_TRUST_GAP_TAXONOMY

# Mirrors _transition_requirement_payload in authz_graph/compiler.py
RCT_TRANSITION_REQUIREMENT_KEYS: Set[str] = {
    "subject_ref",
    "resource_ref",
    "operation",
    "effect",
    "zone_refs",
    "network_refs",
    "custody_point_refs",
    "workflow_stage_refs",
    "resource_state_hash",
    "requires_break_glass",
    "bypass_deny",
    "required_current_custodian",
    "required_transferable_state",
    "max_telemetry_age_seconds",
    "max_inspection_age_seconds",
    "require_attestation",
    "require_seal",
    "require_approved_source_registration",
    "allow_quarantine",
    "valid_from",
    "valid_to",
    "provenance_source",
}

_ALLOWED_EFFECTS = frozenset({"allow", "deny", "quarantine"})
_KNOWN_TRUST_GAPS = frozenset(TRANSFER_TRUST_GAP_TAXONOMY)


def _decision_graph_as_dict(dgs: Any) -> Dict[str, Any]:
    if dgs is None:
        return {}
    if hasattr(dgs, "to_dict"):
        raw = dgs.to_dict()
        return raw if isinstance(raw, dict) else {}
    if isinstance(dgs, dict):
        return dgs
    return {}


def validate_transition_requirement_entry(entry: Any, *, subject_key: str, index: int) -> List[str]:
    """Return human-readable errors for one compiled transition requirement row."""
    prefix = f"transition_requirements[{subject_key!r}][{index}]"
    if not isinstance(entry, Mapping):
        return [f"{prefix}:not_object"]
    missing = sorted(RCT_TRANSITION_REQUIREMENT_KEYS - set(entry.keys()))
    if missing:
        return [f"{prefix}:missing_keys:{','.join(missing)}"]
    errs: List[str] = []
    effect = entry.get("effect")
    if str(effect).lower() not in _ALLOWED_EFFECTS:
        errs.append(f"{prefix}:invalid_effect:{effect!r}")
    op = entry.get("operation")
    if op is None or not str(op).strip():
        errs.append(f"{prefix}:operation_empty")
    for list_key in (
        "zone_refs",
        "network_refs",
        "custody_point_refs",
        "workflow_stage_refs",
    ):
        val = entry.get(list_key)
        if val is not None and not isinstance(val, list):
            errs.append(f"{prefix}:{list_key}_not_list")
    for bool_key in (
        "requires_break_glass",
        "bypass_deny",
        "require_attestation",
        "require_seal",
        "require_approved_source_registration",
        "allow_quarantine",
    ):
        val = entry.get(bool_key)
        if val is not None and not isinstance(val, bool):
            errs.append(f"{prefix}:{bool_key}_not_bool")
    for int_key in ("max_telemetry_age_seconds", "max_inspection_age_seconds"):
        val = entry.get(int_key)
        if val is not None and not isinstance(val, int):
            errs.append(f"{prefix}:{int_key}_not_int")
    return errs


def validate_decision_graph_snapshot_for_publish(dgs_dict: Mapping[str, Any]) -> List[str]:
    """Structural checks on the compiled decision graph JSON shape."""
    errs: List[str] = []
    wf = str(dgs_dict.get("hot_path_workflow") or "").strip()
    if wf != "restricted_custody_transfer":
        errs.append(f"hot_path_workflow_must_be_restricted_custody_transfer:got:{wf!r}")

    raw_tg = dgs_dict.get("trust_gap_taxonomy") or []
    if not isinstance(raw_tg, Sequence):
        errs.append("trust_gap_taxonomy_not_list")
    else:
        for code in raw_tg:
            s = str(code)
            if s not in _KNOWN_TRUST_GAPS:
                errs.append(f"unknown_trust_gap_code:{s}")

    treqs = dgs_dict.get("transition_requirements")
    if not isinstance(treqs, dict) or not treqs:
        errs.append("transition_requirements_empty")
    else:
        total = 0
        for sk, rows in treqs.items():
            if not isinstance(rows, list):
                errs.append(f"transition_requirements[{sk!r}]:not_list")
                continue
            total += len(rows)
            for i, row in enumerate(rows):
                errs.extend(validate_transition_requirement_entry(row, subject_key=str(sk), index=i))
        if total == 0:
            errs.append("transition_requirements_no_rows")

    return errs


async def gather_rct_publish_validation_errors(
    pkg_client: Any,
    *,
    snapshot_id: int,
    compiled: Any,
) -> List[str]:
    """
    Full publish gate: compiled graph + snapshot manifest + taxonomy tables.

    pkg_client must provide get_snapshot_manifest, get_taxonomy_bundle (async).
    """
    errs: List[str] = []
    if compiled is None:
        return ["compiled_index_missing"]
    if not bool(getattr(compiled, "restricted_transfer_ready", False)):
        errs.append("restricted_transfer_ready_false")
    dgs_dict = _decision_graph_as_dict(getattr(compiled, "decision_graph_snapshot", None))
    if not dgs_dict:
        errs.append("decision_graph_snapshot_missing")
    else:
        errs.extend(validate_decision_graph_snapshot_for_publish(dgs_dict))

    try:
        manifest = await pkg_client.get_snapshot_manifest(snapshot_id)
    except Exception as exc:
        errs.append(f"get_snapshot_manifest_error:{exc}")
        manifest = None
    if not manifest:
        errs.append("pkg_snapshot_manifest_row_missing")

    try:
        tax = await pkg_client.get_taxonomy_bundle(snapshot_id)
    except Exception as exc:
        errs.append(f"get_taxonomy_bundle_error:{exc}")
        tax = {}
    if not isinstance(tax, dict):
        tax = {}
    if not (tax.get("reason_codes") or []):
        errs.append("taxonomy_reason_codes_empty")
    if not (tax.get("trust_gap_codes") or []):
        errs.append("taxonomy_trust_gap_codes_empty")
    if not (tax.get("obligation_codes") or []):
        errs.append("taxonomy_obligation_codes_empty")

    return errs
