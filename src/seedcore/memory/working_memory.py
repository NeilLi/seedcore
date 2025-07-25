import redis
import os

class WorkingMemoryManager:
    def __init__(self, organ_id: str):
        self.organ_id = organ_id
        # Connect to your Redis container using environment variables
        self.client = redis.Redis(host=os.getenv("REDIS_HOST", "ray-redis"), 
                                  port=int(os.getenv("REDIS_PORT", 6379)), 
                                  db=0,
                                  decode_responses=True)
        # Metrics for Prometheus
        self.hits = 0
        self.misses = 0
        print(f"✅ WorkingMemoryManager for Organ '{self.organ_id}' connected to Redis.")

    def _get_key(self, item_id: str) -> str:
        """Creates a namespaced key for the organ."""
        return f"organ:{self.organ_id}:item:{item_id}"

    def get_metrics(self) -> dict:
        """Returns operational metrics for Prometheus export."""
        hit_rate = (self.hits / (self.hits + self.misses)) if (self.hits + self.misses) > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate
        }

    def set_item(self, item_id: str, value: str):
        """
        Stores an item in Redis with a 45-second TTL.
        """
        key = self._get_key(item_id)
        self.client.set(key, value, ex=45)

    def get_item(self, item_id: str) -> str | None:
        """
        Retrieves an item and updates hit/miss metrics for Prometheus.
        """
        key = self._get_key(item_id)
        value = self.client.get(key)
        if value is not None:
            self.hits += 1
        else:
            self.misses += 1
        return value 