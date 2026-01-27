import os
import sys


# ----------------------------------------------------------------------
# 1. Environment MUST be set before any imports happen
# ----------------------------------------------------------------------

os.environ.setdefault("ENV", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test"
)
os.environ.setdefault("RAY_ADDRESS", "local")


# ----------------------------------------------------------------------
# 2. Pytest hook: runs BEFORE test collection
# ----------------------------------------------------------------------

def pytest_sessionstart(session):
    """
    This runs before pytest imports ANY test modules.
    We use it to:
    - remove poisoned modules
    - prevent partial imports
    - stabilize Ray + Eventizer + Database
    """

    # 🔥 HARD RESET of known-problematic modules
    poisoned = [
        "ray",
        "seedcore.database",
        "seedcore.ops.eventizer.fast_eventizer",
    ]

    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in poisoned):
            sys.modules.pop(name, None)
    
    # Import mock dependencies to set up mocks BEFORE any test imports
    # This ensures ray is mocked before any test file tries to import ray-using modules
    try:
        # Import database mocks first (more complete), then ray/eventizer mocks
        try:
            import tests.mock_database_dependencies  # noqa: F401
        except ImportError:
            pass  # If not available, mock_ray_dependencies will provide basic database mock
        # Import mock modules which will set up sys.modules['ray'] etc.
        import tests.mock_ray_dependencies  # noqa: F401
        import tests.mock_eventizer_dependencies  # noqa: F401
    except ImportError:
        # If mock files aren't available, at least stub ray.dag to prevent import errors
        import types
        if 'ray.dag' not in sys.modules:
            sys.modules['ray.dag'] = types.ModuleType('ray.dag')
        if 'ray.dag.compiled_dag_node' not in sys.modules:
            sys.modules['ray.dag.compiled_dag_node'] = types.ModuleType('ray.dag.compiled_dag_node')


# ----------------------------------------------------------------------
# 3. Safe Ray init (after imports, but controlled)
# ----------------------------------------------------------------------

import pytest


@pytest.fixture(scope="session", autouse=True)
def _safe_ray():
    """Safe Ray fixture that uses mocks if available."""
    # Try to import mock_ray_dependencies first to set up mocks
    try:
        import tests.mock_ray_dependencies  # noqa: F401
    except ImportError:
        pass  # If not available, continue with real ray
    
    import ray

    # Only initialize real Ray if it's not already mocked
    # Check if ray is a mock by seeing if it has __path__ attribute (package marker)
    if hasattr(ray, '__path__') or not hasattr(ray, 'init'):
        # Ray is mocked, skip initialization
        yield
        return

    if not ray.is_initialized():
        ray.init(
            local_mode=True,
            ignore_reinit_error=True,
            logging_level="ERROR",
            include_dashboard=False,
        )

    yield

    if ray.is_initialized():
        ray.shutdown()
