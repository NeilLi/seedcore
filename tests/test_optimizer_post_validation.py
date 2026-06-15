from __future__ import annotations

from datetime import datetime, timezone

from seedcore.models.optimization import (
    RoutePlanAuthorityWindow,
    RoutePlanProposal,
    RoutePlanStop,
    RoutePlanValidationContext,
)
from seedcore.ops.optimization import post_validate_route_plan


START = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
END = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)


def test_post_validate_route_plan_allows_matching_fixture_plan() -> None:
    result = post_validate_route_plan(_proposal(), _context())

    assert result.disposition == "allow"
    assert result.reason_codes == []
    assert result.authority_minted is False


def test_post_validate_route_plan_denies_forbidden_zone() -> None:
    proposal = _proposal(
        stops=[
            RoutePlanStop(
                stop_id="stop-1",
                sequence=0,
                location_ref="dock-a",
                zone_ref="quarantine-zone",
                asset_refs=["asset-1"],
                planned_arrival_at=START,
            )
        ]
    )

    result = post_validate_route_plan(proposal, _context())

    assert result.disposition == "deny"
    assert "forbidden_zone_ref" in result.reason_codes
    assert result.authority_minted is False


def test_post_validate_route_plan_denies_unauthorized_actor() -> None:
    proposal = _proposal(actor_refs=["actor-evil"])

    result = post_validate_route_plan(proposal, _context())

    assert result.disposition == "deny"
    assert "unauthorized_actor_ref" in result.reason_codes


def test_post_validate_route_plan_quarantines_asset_lockout() -> None:
    context = _context(quarantined_asset_refs=["asset-1"])

    result = post_validate_route_plan(_proposal(), context)

    assert result.disposition == "quarantine"
    assert "quarantined_asset_ref" in result.reason_codes


def test_post_validate_route_plan_quarantines_missing_hash() -> None:
    proposal = _proposal(route_plan_hash=None)

    result = post_validate_route_plan(proposal, _context())

    assert result.disposition == "quarantine"
    assert "missing_route_plan_hash" in result.reason_codes


def test_post_validate_route_plan_denies_stop_outside_window() -> None:
    proposal = _proposal(
        stops=[
            RoutePlanStop(
                stop_id="stop-1",
                sequence=0,
                location_ref="dock-a",
                asset_refs=["asset-1"],
                planned_arrival_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
            )
        ]
    )

    result = post_validate_route_plan(proposal, _context())

    assert result.disposition == "deny"
    assert "stop_time_outside_authority_window" in result.reason_codes


def _proposal(**overrides: object) -> RoutePlanProposal:
    data = {
        "proposal_id": "route-plan-1",
        "workflow_join_key": "workflow:rct-1",
        "optimizer_backend": "fixture",
        "generated_at": START,
        "route_plan_hash": "route-plan-hash-1",
        "asset_refs": ["asset-1"],
        "actor_refs": ["actor-1"],
        "device_refs": ["device-1"],
        "origin_ref": "origin-a",
        "destination_ref": "destination-b",
        "stops": [
            RoutePlanStop(
                stop_id="stop-1",
                sequence=0,
                location_ref="dock-a",
                asset_refs=["asset-1"],
                actor_ref="actor-1",
                device_ref="device-1",
                planned_arrival_at=START,
            )
        ],
        "authority_window": RoutePlanAuthorityWindow(starts_at=START, expires_at=END),
        "policy_snapshot_ref": "policy-snapshot-1",
    }
    data.update(overrides)
    return RoutePlanProposal(**data)


def _context(**overrides: object) -> RoutePlanValidationContext:
    data = {
        "workflow_join_key": "workflow:rct-1",
        "allowed_asset_refs": ["asset-1"],
        "allowed_actor_refs": ["actor-1"],
        "allowed_device_refs": ["device-1"],
        "origin_ref": "origin-a",
        "destination_ref": "destination-b",
        "authority_window": RoutePlanAuthorityWindow(starts_at=START, expires_at=END),
        "forbidden_zone_refs": ["quarantine-zone"],
        "policy_snapshot_ref": "policy-snapshot-1",
    }
    data.update(overrides)
    return RoutePlanValidationContext(**data)
