# agents/bridges/checkpoint_manager.py

from typing import Dict, Any


class CheckpointManager:
    """
    Handles:
    - loading/saving private memory via CheckpointStore
    - automatic key construction: organ_id/agent_id
    """

    def __init__(self, cfg: Dict[str, Any], agent_id: str, privmem, organ_id: str):
        from ..checkpoint import CheckpointStoreFactory

        self.enabled = cfg.get("enabled", False)
        self.privmem = privmem
        self.key = f"{organ_id}/{agent_id}"
        self.store = CheckpointStoreFactory.from_config(cfg)

    # ------------------------------------------------------------------
    def maybe_restore(self):
        if not self.enabled or not hasattr(self.privmem, "load"):
            return

        try:
            blob = self.store.load(self.key)
            if blob:
                self.privmem.load(blob)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def after_task(self):
        """Save private memory after each task."""
        if not self.enabled or not hasattr(self.privmem, "dump"):
            return

        try:
            blob = self.privmem.dump()
            self.store.save(self.key, blob)
        except Exception:
            pass
