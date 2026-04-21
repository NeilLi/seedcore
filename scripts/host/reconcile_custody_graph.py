#!/usr/bin/env python3
"""Run custody graph reconciliation or repair for one asset or a small batch."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--asset-id",
        action="append",
        dest="asset_ids",
        help="Asset id to reconcile. May be repeated.",
    )
    scope.add_argument(
        "--all-assets",
        action="store_true",
        help="Reconcile the current transition-backed asset set up to --asset-limit.",
    )
    parser.add_argument(
        "--asset-limit",
        type=int,
        default=100,
        help="Maximum number of assets to load when --all-assets is used.",
    )
    parser.add_argument(
        "--asset-offset",
        type=int,
        default=0,
        help="Offset used with --all-assets for paging through asset ids.",
    )
    parser.add_argument(
        "--transition-limit",
        type=int,
        default=500,
        help="Maximum transition rows to inspect per asset.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Apply repair while reconciling.",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit non-zero when any reconciled asset shows drift.",
    )
    return parser.parse_args(argv)


async def _resolve_asset_ids(service: Any, args: argparse.Namespace) -> list[str]:
    if args.asset_ids:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in args.asset_ids:
            asset_id = str(raw or "").strip()
            if asset_id and asset_id not in seen:
                seen.add(asset_id)
                ordered.append(asset_id)
        return ordered
    from seedcore.database import get_async_pg_session_factory

    session_factory = get_async_pg_session_factory()
    async with session_factory() as session:
        return await service.list_asset_ids(
            session,
            limit=max(1, int(args.asset_limit)),
            offset=max(0, int(args.asset_offset)),
        )


async def _run(args: argparse.Namespace) -> int:
    from seedcore.coordinator.metrics.registry import get_global_metrics_tracker
    from seedcore.database import get_async_pg_session_factory
    from seedcore.services.custody_graph_service import CustodyGraphService

    service = CustodyGraphService()
    tracker = get_global_metrics_tracker()
    asset_ids = await _resolve_asset_ids(service, args)
    session_factory = get_async_pg_session_factory()

    tracker.increment_counter("custody_graph_batch_runs_total")
    tracker.increment_counter("custody_graph_batch_assets_total", value=len(asset_ids))
    tracker.set_gauge("custody_graph_last_batch_asset_count", float(len(asset_ids)))

    results: list[dict[str, Any]] = []
    drift_assets = 0
    repaired_assets = 0

    for asset_id in asset_ids:
        async with session_factory() as session:
            async with session.begin():
                result = await service.reconcile_asset_projection(
                    session,
                    asset_id=asset_id,
                    limit=max(1, int(args.transition_limit)),
                    repair=bool(args.repair),
                )
        results.append(result)
        if result.get("drift_detected"):
            drift_assets += 1
        if result.get("repair_applied"):
            repaired_assets += 1

    tracker.increment_counter("custody_graph_batch_drift_assets_total", value=drift_assets)
    tracker.set_gauge("custody_graph_last_batch_drift_asset_count", float(drift_assets))

    summary = {
        "asset_count": len(asset_ids),
        "drift_asset_count": drift_assets,
        "repaired_asset_count": repaired_assets,
        "repair_requested": bool(args.repair),
        "results": results,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.fail_on_drift and drift_assets > 0:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
