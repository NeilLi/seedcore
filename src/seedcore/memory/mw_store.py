import ray
import collections
import heapq

@ray.remote(num_cpus=0.05, resources={"head_node": 0.001})
class MwStore:
    def __init__(self, max_items=10_000):
        self.counts = collections.Counter()
        self.max_items = max_items
    
    def ping(self):
        """Keepalive method to prevent Ray from garbage collecting this actor."""
        return "pong"
    
    def incr(self, uuid: str, delta: int = 1):
        self.counts[uuid] += delta
        if len(self.counts) > self.max_items:
            # Drop cold tail
            for _ in range(len(self.counts) - self.max_items):
                self.counts.pop(min(self.counts, key=self.counts.get))
    
    def topn(self, n: int = 1):
        return heapq.nlargest(n, self.counts.items(), key=lambda kv: kv[1]) 