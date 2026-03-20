from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(os.getenv("SEEDCORE_APP_ROOT", "/app"))
CONFIG_DIR = Path(os.getenv("SEEDCORE_CONFIG_DIR", str(APP_ROOT / "config")))
DATA_DIR = Path(os.getenv("SEEDCORE_DATA_DIR", str(APP_ROOT / "data")))
OPT_DIR = Path(os.getenv("SEEDCORE_OPT_DIR", str(APP_ROOT / "opt")))


def _env_candidates(env_names: Iterable[str]) -> list[Path]:
    candidates: list[Path] = []
    for env_name in env_names:
        raw = os.getenv(env_name)
        if raw:
            candidates.append(Path(raw))
    return candidates


def resolve_config_path(
    canonical_name: str,
    *,
    env_names: Iterable[str] = (),
) -> Path:
    """Resolve a config file path using env overrides, then the canonical name."""
    candidates = _env_candidates(env_names)
    candidates.append(CONFIG_DIR / canonical_name)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_project_config_path(
    canonical_name: str,
    *,
    env_names: Iterable[str] = (),
) -> Path:
    """Resolve a repo-local config path using the canonical filename."""
    project_config_dir = PROJECT_ROOT / "config"
    candidates = _env_candidates(env_names)
    candidates.append(project_config_dir / canonical_name)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
