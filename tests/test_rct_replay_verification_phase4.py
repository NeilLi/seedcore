"""Phase-4 RCT triple-hash replay verification."""

import pytest

from seedcore.ops.evidence.rct_replay_verification import (
    evaluate_strict_rct_replay_triple_hash,
    strict_rct_replay_triple_hash_enabled,
)


def test_strict_flag_reads_env(monkeypatch):
    monkeypatch.delenv("SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH", raising=False)
    assert strict_rct_replay_triple_hash_enabled() is False
    monkeypatch.setenv("SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH", "1")
    assert strict_rct_replay_triple_hash_enabled() is True


def test_evaluate_strict_passes_when_aligned():
    policy = "sha256:pkg-checksum-aaa"
    dg = "sha256:decision-graph-bbb"
    sb = "sha256:state-binding-ccc"
    record = {
        "policy_decision": {
            "authz_graph": {
                "policy_snapshot_hash": policy,
                "decision_graph_snapshot_hash": dg,
                "snapshot_hash": dg,
                "state_binding_hash": sb,
            },
            "governed_receipt": {
                "policy_snapshot_hash": policy,
                "decision_graph_snapshot_hash": dg,
                "snapshot_hash": dg,
                "state_binding_hash": sb,
            },
        }
    }
    pr = {
        "policy_snapshot_hash": policy,
        "decision_graph_snapshot_hash": dg,
        "state_binding_hash": sb,
    }
    eb = {
        "policy_snapshot_hash": policy,
        "decision_graph_snapshot_hash": dg,
        "state_binding_hash": sb,
    }
    out = evaluate_strict_rct_replay_triple_hash(
        record=record, policy_receipt=pr, evidence_bundle=eb
    )
    assert out["verified"] is True
    assert out["issues"] == []


def test_evaluate_strict_fails_policy_only():
    record = {"policy_decision": {"authz_graph": {}, "governed_receipt": {}}}
    pr = {
        "policy_snapshot_hash": "p",
        "decision_graph_snapshot_hash": None,
        "state_binding_hash": None,
    }
    eb = {"policy_snapshot_hash": "p"}
    out = evaluate_strict_rct_replay_triple_hash(
        record=record, policy_receipt=pr, evidence_bundle=eb
    )
    assert out["verified"] is False
    assert any("missing" in issue for issue in out["issues"])
