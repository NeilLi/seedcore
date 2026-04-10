#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_get(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return payload


def _text_get(url: str) -> str:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.text


def _latest_json(directory: Path) -> dict[str, Any] | None:
    if not directory.exists():
        return None
    candidates = sorted(directory.glob("*.json"))
    if not candidates:
        return None
    latest = candidates[-1]
    payload = json.loads(latest.read_text(encoding="utf-8"))
    return {
        "path": str(latest),
        "payload": payload,
    }


def capture_baseline(
    *,
    runtime_api_base: str,
    repo_root: Path,
    output_root: Path,
) -> Path:
    status = _json_get(f"{runtime_api_base}/pdp/hot-path/status")
    metrics_text = _text_get(f"{runtime_api_base}/pdp/hot-path/metrics")

    shadow = _latest_json(repo_root / ".local-runtime" / "hot_path_shadow")
    benchmark = _latest_json(repo_root / ".local-runtime" / "hot_path_benchmarks")

    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"hot_path_deployment_baseline_{_now_stamp()}.json"
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "runtime_api_base": runtime_api_base,
        "status": status,
        "metrics_text": metrics_text,
        "latest_shadow_artifact": shadow,
        "latest_benchmark_artifact": benchmark,
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture live hot-path benchmark/observability baseline.")
    parser.add_argument(
        "--runtime-api-base",
        default="http://127.0.0.1:8002/api/v1",
        help="Base runtime API URL (default: %(default)s)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="SeedCore repo root (default: %(default)s)",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Directory for baseline artifacts (default: <repo>/.local-runtime/hot_path_baselines)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output_root = (
        Path(args.output_root).resolve()
        if args.output_root
        else repo_root / ".local-runtime" / "hot_path_baselines"
    )
    output_path = capture_baseline(
        runtime_api_base=args.runtime_api_base.rstrip("/"),
        repo_root=repo_root,
        output_root=output_root,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
