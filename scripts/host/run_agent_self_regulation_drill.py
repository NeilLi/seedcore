#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from seedcore.drills.agent_self_regulation import run_agent_self_regulation_drill  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local assistant self-regulation drill and write gate evidence."
    )
    parser.add_argument(
        "--manifest-output",
        default="artifacts/agent_self_regulation/gated_actions_manifest.json",
        help="Path for the generated gated action manifest.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/agent_self_regulation/drill_evidence.json",
        help="Path for the drill evidence JSON.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    evidence = await run_agent_self_regulation_drill(
        manifest_path=Path(args.manifest_output),
        evidence_path=Path(args.output),
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main())
