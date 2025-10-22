# seedcore/src/seedcore/graph/gnn_models.py
from __future__ import annotations
import torch
import torch.nn as nn
from typing import Dict, Tuple, Optional

# DGL will be imported when needed to avoid import errors during testing
DGL_AVAILABLE = None
dgl = None
dglnn = None

def _ensure_dgl():
    """Ensure DGL is available, import if needed."""
    global DGL_AVAILABLE, dgl, dglnn
    if DGL_AVAILABLE is None:
        try:
            import dgl
            import dgl.nn as dglnn
            DGL_AVAILABLE = True
        except (ImportError, FileNotFoundError):
            DGL_AVAILABLE = False
            dgl = None
            dglnn = None
    return DGL_AVAILABLE

class SAGE(nn.Module):
    def __init__(self, in_feats: int, h_feats: int = 128, layers: int = 2):
        if not _ensure_dgl():
            raise ImportError("DGL is not available. Please install DGL to use this class.")
        
        super().__init__()
        self.convs = nn.ModuleList()
        self.convs.append(dglnn.SAGEConv(in_feats, h_feats, aggregator_type="mean"))
        for _ in range(layers - 1):
            self.convs.append(dglnn.SAGEConv(h_feats, h_feats, aggregator_type="mean"))
        self.act = nn.ReLU()

    def forward(self, g: dgl.DGLGraph, x: torch.Tensor, edge_weight: Optional[torch.Tensor] = None) -> torch.Tensor:
        h = x
        for conv in self.convs:
            # DGL SAGEConv supports edge_weight in forward; pass if provided
            h = conv(g, h, edge_weight=edge_weight) if edge_weight is not None else conv(g, h)
            h = self.act(h)
        return nn.functional.normalize(h, p=2, dim=1)


# ---------- NEW: Heterogeneous SAGE for HGNN ----------
class HeteroSAGE(nn.Module):
    """
    Relation-aware GraphSAGE over heterographs.
    - Per-ntype linear input projection to a shared hidden dim.
    - Per-relation SAGEConv wrapped in HeteroGraphConv.
    - Returns dict of normalized embeddings per node type.
    """
    def __init__(
        self,
        in_dims: Dict[str, int],           # {ntype: input_dim}
        h_feats: int = 128,
        layers: int = 2,
        rel_names: Optional[Tuple[Tuple[str, str, str], ...]] = None,  # list of canonical etypes
        aggregate: str = "sum",
    ):
        super().__init__()
        self.h_feats = h_feats
        # per-type input projection → hidden
        self.proj = nn.ModuleDict({
            ntype: nn.Linear(in_dim, h_feats) for ntype, in_dim in in_dims.items()
        })
        self.relu = nn.ReLU()

        # build relation modules per layer
        self.convs = nn.ModuleList()
        for _ in range(layers):
            mods = {}
            # if rel_names not given, create lazily in forward from g.canonical_etypes
            self.convs.append(dglnn.HeteroGraphConv(mods, aggregate=aggregate))

        self.rel_names = rel_names  # optional static list

    def forward(
        self,
        g: dgl.DGLHeteroGraph,
        x_dict: Dict[str, torch.Tensor],
        edge_weight_dict: Optional[Dict[Tuple[str, str, str], torch.Tensor]] = None,
    ) -> Dict[str, torch.Tensor]:
        # project to shared space
        h = {ntype: self.relu(self.proj[ntype](x)) for ntype, x in x_dict.items()}

        # ensure convs have per-relation modules
        rels = self.rel_names or g.canonical_etypes
        for li, conv in enumerate(self.convs):
            if len(conv.mods) == 0:
                # lazily materialize per-relation SAGEConv modules
                conv.mods = nn.ModuleDict({
                    str(et): dglnn.SAGEConv(self.h_feats, self.h_feats, aggregator_type="mean")
                    for et in rels
                })

            # build mod_kwargs to feed edge weights per relation if present
            mod_kwargs = {}
            if edge_weight_dict:
                for et in rels:
                    ew = edge_weight_dict.get(et)
                    if ew is not None:
                        mod_kwargs[str(et)] = {"edge_weight": ew}

            h = conv(g, h, mod_kwargs=mod_kwargs if mod_kwargs else None)
            # relu per type
            h = {k: self.relu(v) for k, v in h.items()}

        # L2-normalize per type
        h = {k: nn.functional.normalize(v, p=2, dim=1) for k, v in h.items()}
        return h


# ---------- NEW: Memory fusion head ----------
class MemoryFusion(nn.Module):
    """
    Lightweight readout that fuses memory_cell neighbors into task embeddings.
    - Uses static edge weights (time decay) as attention priors.
    - Optional learned gate.
    """
    def __init__(self, h_feats: int = 128, use_gate: bool = True):
        super().__init__()
        self.use_gate = use_gate
        if use_gate:
            self.gate = nn.Sequential(
                nn.Linear(2 * h_feats, h_feats),
                nn.ReLU(),
                nn.Linear(h_feats, 1),
                nn.Sigmoid(),
            )

    @torch.no_grad()
    def forward(
        self,
        g: dgl.DGLHeteroGraph,
        h: Dict[str, torch.Tensor],
        edge_weight_dict: Optional[Dict[Tuple[str, str, str], torch.Tensor]] = None,
        rel: Tuple[str, str, str] = ("task", "reads", "memory_cell"),
        target_ntype: str = "task",
        memory_ntype: str = "memory_cell",
    ) -> torch.Tensor:
        """
        Returns enhanced task embeddings: h_task_fused [num_task, h_feats].
        """
        h_task = h.get(target_ntype)
        h_mem = h.get(memory_ntype)
        if h_task is None:
            return None

        # If memory nodes/edges absent, no-op
        if h_mem is None or rel not in g.canonical_etypes:
            return h_task

        # Gather adjacency for rel
        src, dst = g.edges(etype=rel)  # src: task, dst: memory_cell
        if src.numel() == 0:
            return h_task

        # messages: from memory -> task (note rel direction above is task -> memory_cell)
        # invert for readout
        # We'll aggregate memory embeddings into task via dst->src map
        # Build per-edge weights (time-decay) if present
        if edge_weight_dict and rel in edge_weight_dict:
            w = edge_weight_dict[rel].to(h_task.device).unsqueeze(1)  # [E,1]
        else:
            w = torch.ones((src.shape[0], 1), device=h_task.device)

        m = h_mem[dst] * w  # [E, D]
        # sum aggregate per src task
        fused = torch.zeros_like(h_task)
        fused.index_add_(0, src, m)

        if self.use_gate:
            # learned gate between original task and fused memory
            gate = self.gate(torch.cat([h_task, fused], dim=1))  # [N_task, 1]
            return nn.functional.normalize(gate * fused + (1 - gate) * h_task, p=2, dim=1)
        else:
            return nn.functional.normalize(0.5 * (h_task + fused), p=2, dim=1)
