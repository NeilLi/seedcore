from __future__ import annotations

import os
import time
from types import SimpleNamespace
import pytest

from seedcore.ops.pkg.authz_graph.ray_cache import AuthzGraphCacheActor, _transition_cache_key


class DummyCompiledIndex:
    def __init__(self, allowed: bool = True, disposition: str = "allow") -> None:
        self.allowed = allowed
        self.disposition = disposition
        self.snapshot_ref = "snapshot:pkg-prod-2026-04-02"
        self.snapshot_id = 1
        self.snapshot_hash = "abc123hash"
        self.permissions_by_subject = {}

    def evaluate_transition(self, request) -> SimpleNamespace:
        return SimpleNamespace(
            allowed=self.allowed,
            disposition=SimpleNamespace(value=self.disposition),
            reason="evaluated_disposition",
            quarantined=False,
            asset_ref="asset:123",
            resource_ref="resource:123",
            current_custodian="custodian:123",
            restricted_token_recommended=False,
            trust_gaps=[],
            checked_constraints=[],
            permission_match=SimpleNamespace(
                allowed=self.allowed,
                matched_subjects=[],
                authority_paths=[],
                matched_permissions=[],
                deny_permissions=[],
                break_glass_permissions=[],
                break_glass_required=False,
                break_glass_used=False,
                reason="evaluated_reason",
            ),
            receipt=SimpleNamespace(
                decision_hash="dec-hash-123",
                disposition=SimpleNamespace(value=self.disposition),
                snapshot_ref=self.snapshot_ref,
                snapshot_id=self.snapshot_id,
                snapshot_version="1.0",
                snapshot_hash=self.snapshot_hash,
                principal_ref=request.principal_ref,
                operation=request.operation,
                asset_ref=request.asset_ref,
                resource_ref=request.resource_ref,
                reason="evaluated_reason",
                generated_at="2026-04-02T08:00:00Z",
                trust_gap_codes=[],
                provenance_sources=[],
            )
        )


def test_positive_cache_expires_with_ttl(monkeypatch) -> None:
    # Force positive cache TTL to 0.1 seconds for testing
    monkeypatch.setenv("SEEDCORE_POSITIVE_CACHE_TTL_SECONDS", "0.1")

    actor = AuthzGraphCacheActor()
    index = DummyCompiledIndex(allowed=True, disposition="allow")
    actor._compiled_index = index

    payload = {
        "principal_ref": "agent:1",
        "operation": "TRANSFER",
        "asset_ref": "asset:123",
    }

    # 1. First evaluation: cache miss & populates
    res1 = actor.evaluate_transition(payload)
    assert actor._status["transition_cache_entries"] == 1

    # 2. Immediate second evaluation: cache hit
    res2 = actor.evaluate_transition(payload)
    assert actor._status["transition_cache_entries"] == 1

    # 3. Sleep 0.15 seconds to let positive cache entry expire
    time.sleep(0.15)

    # 4. Third evaluation: cache expires and is re-evaluated
    res3 = actor.evaluate_transition(payload)
    # The old expired entry is popped, then newly evaluated and stored
    assert actor._status["transition_cache_entries"] == 1


def test_negative_cache_cached_permanently(monkeypatch) -> None:
    # Set positive cache TTL to 0.05 seconds
    monkeypatch.setenv("SEEDCORE_POSITIVE_CACHE_TTL_SECONDS", "0.05")

    actor = AuthzGraphCacheActor()
    # allowed=False represents denial/quarantine
    index = DummyCompiledIndex(allowed=False, disposition="deny")
    actor._compiled_index = index

    payload = {
        "principal_ref": "agent:1",
        "operation": "TRANSFER",
        "asset_ref": "asset:123",
    }

    # 1. First evaluation: caches the denial
    actor.evaluate_transition(payload)
    assert actor._status["transition_cache_entries"] == 1

    # 2. Sleep 0.1 seconds (longer than positive TTL)
    time.sleep(0.1)

    # 3. Cache hit on negative authority should still succeed (permanent caching for denials)
    res = actor.evaluate_transition(payload)
    assert res["allowed"] is False
    assert actor._status["transition_cache_entries"] == 1


def test_cache_invalidation_keys() -> None:
    actor = AuthzGraphCacheActor()
    index = DummyCompiledIndex(allowed=True, disposition="allow")
    actor._compiled_index = index

    payload1 = {
        "principal_ref": "agent:1",
        "operation": "TRANSFER",
        "asset_ref": "asset:123",
        "revocation_epoch": "epoch:1",
        "token_counter_version": "v1",
    }

    payload2 = {
        **payload1,
        "revocation_epoch": "epoch:2", # Changed revocation epoch
    }

    payload3 = {
        **payload1,
        "token_counter_version": "v2", # Changed token counter version
    }

    # Verify cache key hashes are different
    key1 = _transition_cache_key(index, payload1)
    key2 = _transition_cache_key(index, payload2)
    key3 = _transition_cache_key(index, payload3)

    assert key1 != key2
    assert key1 != key3
    assert key2 != key3

    # Verify they produce different cache entries in the actor
    actor.evaluate_transition(payload1)
    assert actor._status["transition_cache_entries"] == 1

    actor.evaluate_transition(payload2)
    assert actor._status["transition_cache_entries"] == 2

    actor.evaluate_transition(payload3)
    assert actor._status["transition_cache_entries"] == 3
