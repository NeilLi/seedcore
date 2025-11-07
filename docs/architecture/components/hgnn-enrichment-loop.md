The HGNN Enrichment Loop
========================

Abstract
--------

This document details a hybrid reasoning architecture designed to efficiently process a high volume of tasks while remaining resilient to novelty and complexity. The system uses a *surprise* score to dynamically route work. Predictable requests remain on low-latency paths, while novel or ambiguous tasks—those with high surprise—take an HGNN enrichment route. The HGNN path is a contextual loop: a stateful graph neural network (GNN) stack generates a deep, memory-fused embedding for the surprised task, appends that context to the task payload, and hands it back to a deep cognitive planner. The result blends fast task processing with rich, graph-based reasoning.

1. Surprise Valve: Hysteresis Routing
-------------------------------------

The routing valve lives in `_decide_route_with_hysteresis`, which classifies each task according to its surprise score `S`.

```305:355:src/seedcore/coordinator/core/policies.py
def _decide_route_with_hysteresis(
    S: float,
    last_decision: Optional[str] = None,
    fast_enter: float = 0.35,
    fast_exit: float = 0.38,
    plan_enter: float = 0.60,
    plan_exit: float = 0.57
) -> str:
    # ... existing code ...
    if S < fast_enter:
        return "fast"
    elif S < plan_enter:
        return "planner"
    else:
        return "hgnn"
```

The thresholds form a hysteresis loop that prevents oscillation between paths:

- `fast` (`S < 0.35`): Simple, routine tasks handled by the fast executor.
- `planner` (`0.35 ≤ S < 0.60`): Multi-step tasks that still map to known patterns.
- `hgnn` (`S ≥ 0.60`): Novel or ambiguous tasks that require contextual enrichment before planning.

2. Core Architecture
--------------------

The HGNN route composes three layers: graph data, GNN compute, and orchestration.

### 2.1 Graph Data Layer — System Memory

The heterogeneous, two-layer graph defined in `deploy/migrations/007_hgnn_graph_schema.sql` is the durable memory backing the HGNN loop. It models domain entities and their interactions, exposes numeric node IDs for DGL, and flattens edges into HGNN-ready views.

- **Node types**: `task`, `agent`, `organ`, `artifact`, `capability`, `memory_cell`.
- **Edge types**: task-task dependencies, task-to-organ execution, task-to-capability usage, task-to-memory reads/writes, and more.
- **Key helpers**: `graph_node_map` stores stable `node_id` integers; `ensure_*_node` functions upsert mappings; the `hgnn_edges` view collapses heterogeneous relationships into `(src, dst, edge_type)` tuples ready for DGL ingestion.

```37:316:deploy/migrations/007_hgnn_graph_schema.sql
CREATE TABLE IF NOT EXISTS graph_node_map (...);
CREATE OR REPLACE FUNCTION ensure_task_node(p_task_id UUID) RETURNS BIGINT AS $$ ... $$;
-- ... existing code ...
CREATE OR REPLACE VIEW hgnn_edges AS
    SELECT ensure_task_node(d.src_task_id) AS src_node_id,
           ensure_task_node(d.dst_task_id) AS dst_node_id,
           'task__depends_on__task'::TEXT   AS edge_type
    FROM task_depends_on_task d
UNION ALL
    -- Additional edge mappings
```

These structures let runtime services translate business identifiers (UUIDs, text IDs) into the dense integer format required by DGL while preserving full edge semantics.

### 2.2 GNN Compute Layer — HeteroSAGE and MemoryFusion

The compute stack lives in `src/seedcore/graph/gnn_models.py` and combines a heterograph GraphSAGE backbone with a memory-aware readout head.

- **HeteroSAGE** lazily instantiates relation-specific `SAGEConv` modules for every canonical edge type and projects heterogeneous node features into a shared embedding space.
- **MemoryFusion** post-processes the task embeddings by aggregating `memory_cell` neighbors with optional gating.

```47:180:src/seedcore/graph/gnn_models.py
class HeteroSAGE(nn.Module):
    # ... existing code ...
    def forward(self, g, x_dict, edge_weight_dict=None):
        h = {ntype: self.relu(self.proj[ntype](x)) for ntype, x in x_dict.items()}
        # Lazy per-relation SAGEConv materialization
        # ... existing code ...
        return {k: nn.functional.normalize(v, p=2, dim=1) for k, v in h.items()}

class MemoryFusion(nn.Module):
    @torch.no_grad()
    def forward(self, g, h, edge_weight_dict=None, rel=("task", "reads", "memory_cell"), ...):
        # Aggregate memory_cell neighbors into task embeddings
        # ... existing code ...
```

> **Note**: As implemented, `MemoryFusion.forward` is decorated with `@torch.no_grad()`. If the gating network is meant to learn, remove the decorator so gradients can flow during training.

### 2.3 Orchestration Layer — `LTMEmbedder`

The Ray actor `LTMEmbedder` owns the lifecycle of the GNN stack. It loads subgraphs, runs the models, and dispatches persistence to background workers.

```26:227:src/seedcore/graph/ltm_embeddings.py
@ray.remote
class LTMEmbedder:
    def embed_tasks_with_memory(self, start_task_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
        hg, idx_maps, x_dict, ew = self.loader.load_k_hop_hetero(...)
        self._ensure_models(in_dims)
        with torch.no_grad():
            h = self.hetero(hg, {k: v.to(DEVICE) for k, v in x_dict.items()}, edge_weight_dict=ew)
            h_task = self.memfuse(hg, h, edge_weight_dict=ew)
        # Convert back to task node_ids
        return {inv_maps["task"][i]: T[i].tolist() for i in range(T.shape[0])}
```

The actor keeps compute hot on the designated device, while delegating blocking database writes to the `upsert_embeddings` Ray task. Additional methods (`embed_memory_cells`, `refresh_recent_memory`, `summarize_agent_memory`) reuse the same stack for maintenance and analytics.

3. End-to-End Flow for High-Surprise Tasks
------------------------------------------

1. **Router assigns HGNN** — A task arrives with `S ≥ 0.60`; `_decide_route_with_hysteresis` emits `"hgnn"`.
2. **Coordinator secures numeric IDs** — The coordinator resolves the task UUID to a numeric `node_id` for DGL via `ensure_task_node`.

```sql
SELECT ensure_task_node(CAST(:task_uuid AS uuid));
```

3. **Coordinator invokes HGNN** — The coordinator fetches the Ray actor and requests an enriched embedding.

```python
ltm_actor = ray.get_actor("LTMEmbedder")
embedding_map_ref = ltm_actor.embed_tasks_with_memory.remote(
    start_task_ids=[numeric_node_id],
    k=2,
)
hgnn_embedding = ray.get(embedding_map_ref).get(numeric_node_id)
```

4. **HGNN loop executes** — `LTMEmbedder` loads the 2-hop heterograph, applies `HeteroSAGE`, and fuses `memory_cell` context through `MemoryFusion`.
5. **Coordinator enriches payload** — The resulting 128-D vector is appended to the task payload and routed directly to the deep planner profile with the surprise state already resolved.

```python
cognitive_context = CognitiveContext(
    task_type=task.type,
    input_data={
        "description": task.description,
        "params": task.params,
        "hgnn_embedding": hgnn_embedding,
    },
)
final_plan = cognitive_service.forward_cognitive_task(
    cognitive_context,
    use_deep=True,
)
```

4. Extended Capabilities
-------------------------

Beyond single-task enrichment, `LTMEmbedder` exposes services that operate on the same graph substrate:

- **Memory maintenance**: `refresh_recent_memory` re-embeds recently updated `memory_cell` nodes in the background to keep long-term memory fresh.
- **Agent profiling**: `summarize_agent_memory` aggregates an agent’s interacted memories into a centroid vector, providing a lightweight behavioral signature.
- **Direct memory embeddings**: `embed_memory_cells` generates standalone vectors for downstream retrieval or analytics pipelines.

5. Conclusion
-------------

The HGNN enrichment loop transforms high-surprise tasks into well-contextualized planner inputs. By combining hysteresis routing, a graph-backed memory layer, a heterogeneous GNN stack, and Ray-based orchestration, the system delivers fast paths for routine traffic while unlocking deep, context-aware reasoning for complex scenarios. The architecture is designed for extension: additional relations, embeddings, or maintenance workflows can plug into the same loop without disturbing the core routing surface.

