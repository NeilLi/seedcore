from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(os.getenv("SEEDCORE_APP_ROOT", "/app"))
CONFIG_DIR = Path(os.getenv("SEEDCORE_CONFIG_DIR", str(APP_ROOT / "config")))
DATA_DIR = Path(os.getenv("SEEDCORE_DATA_DIR", str(APP_ROOT / "data")))
OPT_DIR = Path(os.getenv("SEEDCORE_OPT_DIR", str(APP_ROOT / "opt")))


CONFIG_FILE_ALIASES: dict[str, tuple[str, ...]] = {
    "coordinator.yaml": ("coordinator_config.yaml",),
    "organism.yaml": ("organs.yaml",),
    "ray-serve.yaml": ("serve_config.yaml",),
    "eventizer-fast-patterns.json": ("fast_eventizer_patterns.json",),
    "eventizer-patterns.json": ("eventizer_patterns.json",),
    "eventizer-patterns.schema.json": ("eventizer_patterns_schema.json",),
}


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
    extra_aliases: Iterable[str] = (),
) -> Path:
    """Resolve a config file path using env overrides, canonical names, then legacy aliases."""
    candidates = _env_candidates(env_names)
    candidates.append(CONFIG_DIR / canonical_name)

    for alias in CONFIG_FILE_ALIASES.get(canonical_name, ()):
        candidates.append(CONFIG_DIR / alias)
    for alias in extra_aliases:
        candidates.append(CONFIG_DIR / alias)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_project_config_path(
    canonical_name: str,
    *,
    env_names: Iterable[str] = (),
    extra_aliases: Iterable[str] = (),
) -> Path:
    """Resolve a repo-local config path, useful for tests and tooling."""
    project_config_dir = PROJECT_ROOT / "config"
    candidates = _env_candidates(env_names)
    candidates.append(project_config_dir / canonical_name)

    for alias in CONFIG_FILE_ALIASES.get(canonical_name, ()):
        candidates.append(project_config_dir / alias)
    for alias in extra_aliases:
        candidates.append(project_config_dir / alias)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
