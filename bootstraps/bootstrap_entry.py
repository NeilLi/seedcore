#!/usr/bin/env python3
"""
bootstrap_entry.py
Lightweight orchestrator that runs organism init first, then dispatchers.
Use env BOOTSTRAP_MODE=organism|dispatchers|all (default: all)
"""

import os
import sys
import logging
from pathlib import Path

# Ensure "src" is importable for seedcore imports
ROOT = Path(__file__).resolve().parents[1]  # /app
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("bootstrap_entry")

# Sensible default Ray address for in-cluster usage; override via env
os.environ.setdefault("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
os.environ.setdefault("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

def main() -> int:
    mode = os.getenv("BOOTSTRAP_MODE", "all").lower().strip()
    exit_after = os.getenv("EXIT_AFTER_BOOTSTRAP", "true").lower() in ("1", "true", "yes")

    # Import lazily so these modules can share utilities but stay independent
    from bootstraps.bootstrap_organism import bootstrap_organism
    from bootstraps.bootstrap_dispatchers import bootstrap_dispatchers

    rc = 0
    if mode in ("all", "organism"):
        log.info("🚀 Step 1/2: Initializing organism...")
        ok = bootstrap_organism()
        if not ok:
            log.error("❌ Organism initialization failed")
            return 1
        log.info("✅ Organism initialized")

    if mode in ("all", "dispatchers"):
        log.info("🚀 Step 2/2: Initializing dispatchers...")
        ok = bootstrap_dispatchers()
        if not ok:
            log.error("❌ Dispatcher bootstrap failed")
            return 1
        log.info("✅ Dispatchers initialized")

    if exit_after:
        log.info("🚪 EXIT_AFTER_BOOTSTRAP=true — exiting")
        return rc

    # Optional “stay alive” for debugging jobs
    log.info("👀 EXIT_AFTER_BOOTSTRAP=false — staying alive for debugging")
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("🛑 Exit on SIGINT")
    return rc

if __name__ == "__main__":
    sys.exit(main())

