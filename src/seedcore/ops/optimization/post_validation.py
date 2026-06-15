from __future__ import annotations

from datetime import datetime

from seedcore.models.optimization import (
    RoutePlanPostValidationResult,
    RoutePlanProposal,
    RoutePlanValidationContext,
)


def post_validate_route_plan(
    proposal: RoutePlanProposal,
    context: RoutePlanValidationContext,
) -> RoutePlanPostValidationResult:
    """Validate an optimizer proposal against SeedCore authority constraints."""

    reason_codes: list[str] = []
    quarantine_reason_seen = False

    def deny(reason_code: str) -> None:
        if reason_code not in reason_codes:
            reason_codes.append(reason_code)

    def quarantine(reason_code: str) -> None:
        nonlocal quarantine_reason_seen
        quarantine_reason_seen = True
        deny(reason_code)

    if not proposal.route_plan_hash:
        quarantine("missing_route_plan_hash")
    if proposal.workflow_join_key != context.workflow_join_key:
        deny("workflow_join_key_mismatch")
    if proposal.origin_ref != context.origin_ref:
        deny("origin_ref_mismatch")
    if proposal.destination_ref != context.destination_ref:
        deny("destination_ref_mismatch")
    if (
        proposal.policy_snapshot_ref
        and context.policy_snapshot_ref
        and proposal.policy_snapshot_ref != context.policy_snapshot_ref
    ):
        deny("policy_snapshot_ref_mismatch")

    allowed_assets = set(context.allowed_asset_refs)
    proposal_assets = set(proposal.asset_refs)
    if proposal_assets - allowed_assets:
        deny("unauthorized_asset_ref")
    if allowed_assets - proposal_assets:
        deny("missing_asset_ref")
    if proposal_assets & set(context.quarantined_asset_refs):
        quarantine("quarantined_asset_ref")

    if set(proposal.actor_refs) - set(context.allowed_actor_refs):
        deny("unauthorized_actor_ref")
    if set(proposal.device_refs) - set(context.allowed_device_refs):
        deny("unauthorized_device_ref")

    if proposal.authority_window is not None:
        if proposal.authority_window.starts_at < context.authority_window.starts_at:
            deny("authority_window_start_before_context")
        if proposal.authority_window.expires_at > context.authority_window.expires_at:
            deny("authority_window_expiry_after_context")

    forbidden_zones = set(context.forbidden_zone_refs)
    for stop in proposal.stops:
        stop_assets = set(stop.asset_refs)
        if stop_assets - allowed_assets:
            deny("stop_unauthorized_asset_ref")
        if stop_assets & set(context.quarantined_asset_refs):
            quarantine("stop_quarantined_asset_ref")
        if stop.actor_ref and stop.actor_ref not in context.allowed_actor_refs:
            deny("stop_unauthorized_actor_ref")
        if stop.device_ref and stop.device_ref not in context.allowed_device_refs:
            deny("stop_unauthorized_device_ref")
        if stop.zone_ref and stop.zone_ref in forbidden_zones:
            deny("forbidden_zone_ref")
        for timestamp in (stop.planned_arrival_at, stop.planned_departure_at):
            if timestamp is not None and not _within_window(timestamp, context):
                deny("stop_time_outside_authority_window")

    disposition = "allow"
    if quarantine_reason_seen:
        disposition = "quarantine"
    elif reason_codes:
        disposition = "deny"

    return RoutePlanPostValidationResult(
        proposal_id=proposal.proposal_id,
        route_plan_hash=proposal.route_plan_hash,
        disposition=disposition,
        reason_codes=reason_codes,
        policy_snapshot_ref=context.policy_snapshot_ref or proposal.policy_snapshot_ref,
        authority_minted=False,
    )


def _within_window(timestamp: datetime, context: RoutePlanValidationContext) -> bool:
    return context.authority_window.starts_at <= timestamp <= context.authority_window.expires_at
