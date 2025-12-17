#!/usr/bin/env python3
"""
bootstrap_entry.py
Bootstrap orchestrator for SeedCore:
1. Initialize organism
2. Initialize dispatchers
"""

import os
import sys
import time
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Import path setup
# ---------------------------------------------------------------------------
# Add project root to path for namespaced imports (bootstraps.*, seedcore.*)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

# Add project root first (enables bootstraps.* imports)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Add src to path for seedcore imports (if not already covered by root)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("bootstrap_entry")


def _init_env():
    os.environ.setdefault("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
    os.environ.setdefault("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes")


def main() -> int:
    _init_env()

    mode = os.getenv("BOOTSTRAP_MODE", "all").lower().strip()
    exit_after = _flag("EXIT_AFTER_BOOTSTRAP", True)

    valid_modes = {"all", "organism", "dispatchers"}
    if mode not in valid_modes:
        log.error(f"Invalid BOOTSTRAP_MODE={mode!r}. Expected {valid_modes}.")
        return 1

    # Lazy import organism bootstrap first (ensures proper sequence)
    # Use namespaced absolute imports (matches seedcore.* pattern)
    # (relative imports fail when script is run directly)
    if mode in ("all", "organism"):
        from bootstraps.bootstrap_organism import bootstrap_organism
        log.info("🚀 Step 1/2: Initializing organism...")
        try:
            if not bootstrap_organism():
                log.error("❌ Organism initialization failed")
                return 1
        except Exception:
            log.exception("❌ Organism initialization crashed")
            return 1
        log.info("✅ Organism initialized")

    if mode in ("all", "dispatchers"):
        # Lazy import dispatcher bootstrap after organism is initialized
        from bootstraps.bootstrap_dispatchers import bootstrap_dispatchers
        
        log.info("🚀 Step 2/2: Initializing dispatchers...")
        try:
            if not bootstrap_dispatchers():
                log.error("❌ Dispatcher bootstrap failed")
                return 1
        except Exception:
            log.exception("❌ Dispatcher bootstrap crashed")
            return 1
        log.info("✅ Dispatchers initialized")

    if exit_after:
        log.info("🚪 EXIT_AFTER_BOOTSTRAP=true — exiting")
        return 0

    log.info("👀 EXIT_AFTER_BOOTSTRAP=false — staying alive for debugging")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Exit on signal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
