from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_verify_hot_path_observability_uses_portable_python_resolution() -> None:
    script = (ROOT / "scripts" / "host" / "verify_hot_path_observability.sh").read_text()

    assert 'command -v python3' in script
    assert 'PYTHON_BIN="python3"' in script
    assert 'PYTHON_BIN="python"' in script
    assert '"${PYTHON_BIN}" - <<\'PY\'' in script


def test_verify_pkg_redis_resilience_covers_outage_and_recovery() -> None:
    script = (ROOT / "scripts" / "host" / "verify_pkg_redis_resilience.sh").read_text()

    assert 'docker stop "${REDIS_CONTAINER}"' in script
    assert 'docker start "${REDIS_CONTAINER}"' in script
    assert 'trap cleanup EXIT' in script
    assert '/health' in script
    assert '/readyz' in script
    assert '/pdp/hot-path/status' in script


def test_verify_productized_surface_can_enable_redis_dependency_drill() -> None:
    script = (ROOT / "scripts" / "host" / "verify_productized_surface.sh").read_text()

    assert 'SEEDCORE_RUN_REDIS_DEPENDENCY_DRILL' in script
    assert 'verify_pkg_redis_resilience.sh' in script
