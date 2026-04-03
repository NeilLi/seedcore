"""
Phase-4 RCT replay hardening: explicit PKG policy bundle hash, decision-graph hash,
and state-binding hash must align across policy_decision, policy_receipt, and evidence_bundle.

- apply_rct_triple_hash_fields: mutates authz_graph + governed_receipt at decision time.
- evaluate_strict_rct_replay_triple_hash: verification gate when
  SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH is truthy.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional


def strict_rct_replay_triple_hash_enabled() -> bool:
    return (os.environ.get("SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _norm(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def apply_rct_triple_hash_fields(
    authz_graph: Dict[str, Any],
    governed_receipt: Dict[str, Any],
    *,
    compiled_authz_index: Any | None = None,
) -> None:
    """
    Populate policy_snapshot_hash (PKG bundle checksum) and decision_graph_snapshot_hash
    from runtime artifacts. Preserves legacy snapshot_hash as the decision-graph hash.
    """
    dg_hash: Optional[str] = None
    if compiled_authz_index is not None:
        dgs = getattr(compiled_authz_index, "decision_graph_snapshot", None)
        if dgs is not None:
            raw = getattr(dgs, "snapshot_hash", None)
            if raw is not None:
                dg_hash = _norm(raw)
    pkg_hash: Optional[str] = None
    try:
        from seedcore.ops.pkg.manager import get_global_pkg_manager

        mgr = get_global_pkg_manager()
        ev = mgr.get_active_evaluator() if mgr is not None else None
        snap = getattr(ev, "snapshot", None) if ev is not None else None
        ck = getattr(snap, "checksum", None) if snap is not None else None
        pkg_hash = _norm(ck)
    except Exception:
        pass

    if dg_hash:
        authz_graph["decision_graph_snapshot_hash"] = dg_hash
        governed_receipt["decision_graph_snapshot_hash"] = dg_hash
        authz_graph.setdefault("snapshot_hash", dg_hash)
        governed_receipt.setdefault("snapshot_hash", dg_hash)
    if pkg_hash:
        authz_graph["policy_snapshot_hash"] = pkg_hash
        governed_receipt["policy_snapshot_hash"] = pkg_hash


def _decision_graph_hash_from_row(row: Mapping[str, Any]) -> Optional[str]:
    return _norm(row.get("decision_graph_snapshot_hash")) or _norm(row.get("snapshot_hash"))


def evaluate_strict_rct_replay_triple_hash(
    *,
    record: Mapping[str, Any],
    policy_receipt: Mapping[str, Any],
    evidence_bundle: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Refuse policy-only replay: require non-empty policy_snapshot_hash, decision_graph
    snapshot hash, and state_binding_hash on signed artifacts, aligned with policy_decision.
    """
    issues: List[str] = []
    policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
    authz_graph = policy_decision.get("authz_graph") if isinstance(policy_decision.get("authz_graph"), dict) else {}
    governed_receipt = (
        policy_decision.get("governed_receipt") if isinstance(policy_decision.get("governed_receipt"), dict) else {}
    )

    pr = policy_receipt if isinstance(policy_receipt, dict) else {}
    eb = evidence_bundle if isinstance(evidence_bundle, dict) else {}

    # --- Require hashes on signed artifacts (not policy-only) ---
    pr_policy = _norm(pr.get("policy_snapshot_hash"))
    pr_dg = _decision_graph_hash_from_row(pr)
    pr_sb = _norm(pr.get("state_binding_hash"))
    eb_policy = _norm(eb.get("policy_snapshot_hash"))
    eb_dg = _decision_graph_hash_from_row(eb)
    eb_sb = _norm(eb.get("state_binding_hash"))

    if not pr_policy:
        issues.append("policy_receipt_missing_policy_snapshot_hash")
    if not pr_dg:
        issues.append("policy_receipt_missing_decision_graph_snapshot_hash")
    if not pr_sb:
        issues.append("policy_receipt_missing_state_binding_hash")
    if not eb_policy:
        issues.append("evidence_bundle_missing_policy_snapshot_hash")
    if not eb_dg:
        issues.append("evidence_bundle_missing_decision_graph_snapshot_hash")
    if not eb_sb:
        issues.append("evidence_bundle_missing_state_binding_hash")

    # --- Cross-artifact alignment ---
    if pr_policy and eb_policy and pr_policy != eb_policy:
        issues.append("policy_snapshot_hash_mismatch_policy_receipt_vs_evidence_bundle")
    if pr_dg and eb_dg and pr_dg != eb_dg:
        issues.append("decision_graph_snapshot_hash_mismatch_policy_receipt_vs_evidence_bundle")
    if pr_sb and eb_sb and pr_sb != eb_sb:
        issues.append("state_binding_hash_mismatch_policy_receipt_vs_evidence_bundle")

    # --- Align with policy_decision interior (when present) ---
    interior_policy = _norm(authz_graph.get("policy_snapshot_hash")) or _norm(governed_receipt.get("policy_snapshot_hash"))
    interior_dg = _decision_graph_hash_from_row(authz_graph) or _decision_graph_hash_from_row(governed_receipt)
    interior_sb = (
        _norm(governed_receipt.get("state_binding_hash"))
        or _norm(authz_graph.get("state_binding_hash"))
        or _norm(
            (governed_receipt.get("advisory") or {}).get("state_binding_hash")
            if isinstance(governed_receipt.get("advisory"), dict)
            else None
        )
    )

    if interior_policy and pr_policy and interior_policy != pr_policy:
        issues.append("policy_snapshot_hash_mismatch_interior_vs_policy_receipt")
    if interior_policy and eb_policy and interior_policy != eb_policy:
        issues.append("policy_snapshot_hash_mismatch_interior_vs_evidence_bundle")
    if interior_dg and pr_dg and interior_dg != pr_dg:
        issues.append("decision_graph_snapshot_hash_mismatch_interior_vs_policy_receipt")
    if interior_dg and eb_dg and interior_dg != eb_dg:
        issues.append("decision_graph_snapshot_hash_mismatch_interior_vs_evidence_bundle")
    if interior_sb and pr_sb and interior_sb != pr_sb:
        issues.append("state_binding_hash_mismatch_interior_vs_policy_receipt")
    if interior_sb and eb_sb and interior_sb != eb_sb:
        issues.append("state_binding_hash_mismatch_interior_vs_evidence_bundle")

    verified = len(issues) == 0
    artifact = {
        "artifact_type": "rct_triple_hash_strict",
        "verified": verified,
        "error_code": None if verified else "rct_triple_hash_strict_failed",
        "policy_snapshot_hash": pr_policy or eb_policy or interior_policy,
        "decision_graph_snapshot_hash": pr_dg or eb_dg or interior_dg,
        "state_binding_hash": pr_sb or eb_sb or interior_sb,
        "sources": {
            "policy_receipt_policy_snapshot_hash": pr_policy,
            "evidence_bundle_policy_snapshot_hash": eb_policy,
            "interior_policy_snapshot_hash": interior_policy,
        },
    }
    return {"verified": verified, "issues": issues, "artifact": artifact}
