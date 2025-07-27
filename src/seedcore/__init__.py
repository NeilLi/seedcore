import ray
from .bootstrap import bootstrap_actors

# Bootstrap singleton actors at module import
try:
    miss_tracker, shared_cache, mw_store = bootstrap_actors()
except Exception as e:
    # If bootstrap fails, actors will be created on-demand by helper functions
    miss_tracker = None
    shared_cache = None
    mw_store = None
