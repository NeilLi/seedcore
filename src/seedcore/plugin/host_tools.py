from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _shadow_module():
    return _load_module("seedcore_plugin_verify_rct_hot_path_shadow", "scripts/host/verify_rct_hot_path_shadow.py")


@lru_cache(maxsize=1)
def _benchmark_module():
    return _load_module("seedcore_plugin_benchmark_rct_hot_path", "scripts/host/benchmark_rct_hot_path.py")


def default_shadow_artifact_dir() -> str:
    return str(getattr(_shadow_module(), "DEFAULT_ARTIFACT_DIR", REPO_ROOT / ".local-runtime" / "hot_path_shadow"))


def default_benchmark_artifact_dir() -> str:
    return str(getattr(_benchmark_module(), "DEFAULT_ARTIFACT_DIR", REPO_ROOT / ".local-runtime" / "hot_path_benchmarks"))


def run_shadow_verification(*, base_url: str, artifact_dir: str | None = None) -> dict[str, Any]:
    module = _shadow_module()
    run = getattr(module, "run_verification", None)
    if run is None:
        raise RuntimeError("verify_rct_hot_path_shadow.py does not expose run_verification()")
    artifact_root = Path(artifact_dir) if artifact_dir else None
    result = run(base_url=base_url, artifact_root=artifact_root)
    if not isinstance(result, dict):
        raise RuntimeError("Hot-path shadow verification returned an invalid result")
    return result


def run_hotpath_benchmark(
    *,
    base_url: str,
    requests: int,
    warmup: int,
    concurrency: int,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    module = _benchmark_module()
    run = getattr(module, "run_benchmark", None)
    if run is None:
        raise RuntimeError("benchmark_rct_hot_path.py does not expose run_benchmark()")
    artifact_root = Path(artifact_dir or default_benchmark_artifact_dir())
    result = run(
        base_url=base_url,
        total_requests=requests,
        warmup_requests=warmup,
        concurrency=concurrency,
        artifact_root=artifact_root,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Hot-path benchmark returned an invalid result")
    return result
