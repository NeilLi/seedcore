import ray
import collections
import heapq

@ray.remote(num_cpus=0.05) # No head node resource needed
class MwStoreShard:
    def __init__(self, max_items=10_000):
        self.counts = collections.Counter()
        self.max_items = max_items
    
    def ping(self):
        return "pong"
    
    def incr(self, uuid: str, delta: int = 1):
        self.counts[uuid] += delta
        # Eviction logic
        if len(self.counts) > self.max_items:
            # Drop cold tail (this is inefficient, but matches your code)
            # A better way is to use a min-heap or periodic pruning
            to_remove = len(self.counts) - self.max_items
            if to_remove > 0:
                for item, _ in self.counts.most_common()[:-to_remove-1:-1]:
                    del self.counts[item]
    
    def topn(self, n: int = 1):
        return heapq.nlargest(n, self.counts.items(), key=lambda kv: kv[1])