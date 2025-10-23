# seedcore/src/seedcore/graph/loader.py
from __future__ import annotations
import os, math, time
from typing import Dict, List, Tuple, Any, Optional
from neo4j import GraphDatabase

# DGL will be imported when needed to avoid import errors during testing
DGL_AVAILABLE = None
dgl = None
torch = None

def _ensure_dgl():
    """Ensure DGL is available, import if needed."""
    global DGL_AVAILABLE, dgl, torch
    if DGL_AVAILABLE is None:
        try:
            import dgl
            import torch
            DGL_AVAILABLE = True
        except (ImportError, FileNotFoundError):
            DGL_AVAILABLE = False
            dgl = None
            torch = None
    return DGL_AVAILABLE

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# toggle between homogeneous (legacy) and hetero (HGNN+LTM)
GRAPH_MODE_HETERO = os.getenv("GRAPH_MODE", "hetero").lower() in ("hetero", "h", "1", "true")

# map raw Neo4j labels → canonical node types in your paper
# adjust as needed to your actual label taxonomy
LABEL_TO_TYPE = {
    "Task": "task",
    "Artifact": "artifact",
    "Capability": "capability",
    "MemoryCell": "memory_cell",
    "Agent": "agent",
    "Organ": "organ",
}

# map Neo4j relationship type → canonical canonical_etype (src_ntype, rel_name, dst_ntype)
REL_TO_ETYPE = {
    # Task layer
    "DEPENDS_ON":  ("task", "depends_on", "task"),
    "PRODUCES":    ("task", "produces", "artifact"),
    "USES":        ("task", "uses", "capability"),
    "READS":       ("task", "reads", "memory_cell"),
    "WRITES":      ("task", "writes", "memory_cell"),
    # Cross-layer
    "EXECUTED_BY": ("task", "executed_by", "organ"),
    "OWNED_BY":    ("task", "owned_by", "agent"),
}

class GraphLoader:
    """
    Homogeneous k-hop loader (legacy) + NEW hetero loader for HGNN/LTM.
    """
    def __init__(self, uri: str = NEO4J_URI, user: str = NEO4J_USER, password: str = NEO4J_PASSWORD):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    # -------------------- legacy homogeneous path (unchanged) --------------------
    def load_k_hop(
        self,
        start_ids: List[int],
        k: int = 2,
        limit_nodes: int = 5000,
        limit_rels: int = 20000,
    ) -> Tuple[dgl.DGLGraph, Dict[int, int], torch.Tensor]:
        """
        Load k-hop neighborhood as homogeneous DGL graph (legacy implementation).
        
        Returns:
            g: DGLGraph with homogeneous node/edge types
            idx_map: {neo4j_id -> local_id} mapping
            X: Node features tensor [num_nodes, feature_dim]
        """
        if not _ensure_dgl():
            raise ImportError("DGL is not available. Please install DGL to use this function.")
        
        if not start_ids:
            # Return empty graph
            empty_g = dgl.graph(([], []))
            return empty_g, {}, torch.empty(0, 128)  # 128 is GRAPH_H_FEATS
        
        with self.driver.session() as s:
            # 1) Gather nodes within k hops
            q_nodes = f"""
            MATCH (s) WHERE id(s) IN $start_ids
            MATCH p=(s)-[*..{k}]-(m)
            WITH COLLECT(DISTINCT m) + COLLECT(DISTINCT s) AS ns
            UNWIND ns AS n
            WITH DISTINCT n LIMIT $limit_nodes
            RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props
            """
            nodes = s.run(q_nodes, start_ids=start_ids, limit_nodes=limit_nodes).data()
            
            # Fallback to just start nodes if no neighbors found
            if not nodes:
                nodes = s.run(
                    "MATCH (n) WHERE id(n) IN $start_ids RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props",
                    start_ids=start_ids
                ).data()
            
            if not nodes:
                # Return empty graph
                empty_g = dgl.graph(([], []))
                return empty_g, {}, torch.empty(0, 128)
            
            # 2) Create node ID mapping
            idx_map = {int(r["id"]): i for i, r in enumerate(nodes)}
            all_ids = list(idx_map.keys())
            
            # 3) Collect edges between these nodes
            q_edges = """
            MATCH (u)-[r]->(v)
            WHERE id(u) IN $ids AND id(v) IN $ids
            RETURN id(u) AS src, id(v) AS dst
            LIMIT $limit_rels
            """
            edges = s.run(q_edges, ids=all_ids, limit_rels=limit_rels).data()
            
            if not edges:
                # No edges found, create isolated nodes
                src_ids = []
                dst_ids = []
            else:
                src_ids = [idx_map[int(e["src"])] for e in edges]
                dst_ids = [idx_map[int(e["dst"])] for e in edges]
            
            # 4) Create DGL graph
            g = dgl.graph((src_ids, dst_ids), num_nodes=len(nodes))
            
            # 5) Create node features (deterministic based on node properties)
            X = torch.zeros(len(nodes), 128)  # GRAPH_H_FEATS = 128
            
            for i, node in enumerate(nodes):
                # Create deterministic features based on node properties
                props = node.get("props", {})
                labels = node.get("labels", [])
                
                # Use node ID as seed for deterministic features
                node_id = int(node["id"])
                torch.manual_seed(node_id % (2**32))
                
                # Create features based on node properties
                feature_vec = torch.randn(128)
                
                # Add some structure based on labels
                if "Task" in labels:
                    feature_vec[0] = 1.0
                if "Agent" in labels:
                    feature_vec[1] = 1.0
                if "Memory" in labels:
                    feature_vec[2] = 1.0
                
                # Add property-based features
                if "priority" in props:
                    feature_vec[3] = float(props["priority"]) / 10.0
                if "complexity" in props:
                    feature_vec[4] = float(props["complexity"])
                
                X[i] = feature_vec
            
            return g, idx_map, X

    # -------------------- new heterograph path for HGNN + LTM --------------------
    def load_k_hop_hetero(
        self,
        start_ids: List[int],
        k: int = 2,
        limit_nodes: int = 8000,
        limit_rels: int = 40000,
        decay_half_life_s: float = 86_400.0,  # 1 day half-life for recency decay
        feature_bins: int = 8,
        attach_recency: bool = True,
    ) -> Tuple[dgl.DGLHeteroGraph, Dict[str, Dict[int, int]], Dict[str, torch.Tensor], Dict[Tuple[str, str, str], torch.Tensor]]:
        """
        Returns:
          hg:                 DGLHeteroGraph with your canonical node/edge types
          idx_maps:           {ntype: {neo4j_id -> local_id}}
          x_dict:             {ntype: features tensor}
          edge_weight_dict:   {canonical_etype: tensor of edge weights (e.g., time decay)}
        """
        if not _ensure_dgl():
            raise ImportError("DGL is not available. Please install DGL to use this function.")
        
        now = time.time()
        with self.driver.session() as s:
            # 1) gather nodes within k hops
            q_nodes = f"""
            MATCH (s) WHERE id(s) IN $start_ids
            MATCH p=(s)-[*..{k}]-(m)
            WITH COLLECT(DISTINCT m) + COLLECT(DISTINCT s) AS ns
            UNWIND ns AS n
            WITH DISTINCT n LIMIT $limit_nodes
            RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props
            """
            nodes = s.run(q_nodes, start_ids=start_ids, limit_nodes=limit_nodes).data()
            if not nodes:
                nodes = s.run(
                    "MATCH (n) WHERE id(n) IN $start_ids RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props",
                    start_ids=start_ids
                ).data()

            if not nodes:
                # empty - return None to indicate no graph data available
                # The calling code should handle this case
                return None, {}, {}, {}

            # 2) partition nodes by canonical ntype
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for r in nodes:
                labs = (r.get("labels") or [])
                # pick the first mapped label that we recognize; fallback to 'task' for safety
                ntype = None
                for lbl in labs:
                    if lbl in LABEL_TO_TYPE:
                        ntype = LABEL_TO_TYPE[lbl]; break
                ntype = ntype or "task"
                by_type.setdefault(ntype, []).append(r)

            # 3) assign per-type local ids
            idx_maps: Dict[str, Dict[int, int]] = {}
            for ntype, arr in by_type.items():
                idx_maps[ntype] = {int(r["id"]): i for i, r in enumerate(arr)}

            # 4) collect allowed relations among these nodes
            all_ids = [int(r["id"]) for r in nodes]
            q_edges = """
            MATCH (u)-[r]->(v)
            WHERE id(u) IN $ids AND id(v) IN $ids
            RETURN id(u) AS src, type(r) AS rtype, id(v) AS dst, r.updated_at AS rut
            LIMIT $limit_rels
            """
            raw_edges = s.run(q_edges, ids=all_ids, limit_rels=limit_rels).data()

        # 5) build hetero edge index per canonical etype
        edge_dict: Dict[Tuple[str, str, str], Tuple[List[int], List[int]]] = {}
        edge_weight_dict: Dict[Tuple[str, str, str], List[float]] = {}
        for e in raw_edges:
            rtype = e["rtype"]
            if rtype not in REL_TO_ETYPE:
                continue
            src_nt, rel, dst_nt = REL_TO_ETYPE[rtype]
            src_id, dst_id = int(e["src"]), int(e["dst"])
            if src_id not in idx_maps.get(src_nt, {}) or dst_id not in idx_maps.get(dst_nt, {}):
                continue
            src_local = idx_maps[src_nt][src_id]
            dst_local = idx_maps[dst_nt][dst_id]
            key = (src_nt, rel, dst_nt)
            s_list, d_list = edge_dict.setdefault(key, ([], []))
            s_list.append(src_local); d_list.append(dst_local)

            if attach_recency:
                # time-decay edge weight from relation.updated_at (seconds since epoch) if present
                rut = e.get("rut")  # might be None or a string/datetime; normalize to epoch seconds
                try:
                    ts = float(rut) if isinstance(rut, (int, float)) else None
                except Exception:
                    ts = None
                age_s = max(0.0, (now - ts)) if ts else 0.0
                # half-life decay: w = 0.5 ** (age / half_life)
                w = 0.5 ** (age_s / max(1e-6, decay_half_life_s))
            else:
                w = 1.0
            edge_weight_dict.setdefault(key, []).append(float(w))

        # 6) create heterograph
        hg = dgl.heterograph({
            k: (torch.tensor(v[0], dtype=torch.int64), torch.tensor(v[1], dtype=torch.int64))
            for k, v in edge_dict.items()
        }, num_nodes_dict={nt: len(arr) for nt, arr in by_type.items()})

        # 7) features per node type
        #    simple, robust recipe: [deg_in, deg_out, hashed_label(K=feature_bins), recency(optional)]
        x_dict: Dict[str, torch.Tensor] = {}
        K = feature_bins
        # To get global degrees, project to homogeneous quickly
        homo = dgl.to_homogeneous(hg)
        homo_in = homo.in_degrees().float()
        homo_out = homo.out_degrees().float()
        # map back to per-ntype slices
        type_slices = homo.ndata[dgl.NTYPE]  # tensor of type ids
        type_offset = {}
        # build offsets per type id
        # DGL assigns types in creation order; we map via ntid -> mask
        for ntid, ntype in enumerate(hg.ntypes):
            mask = (type_slices == ntid)
            deg_in = homo_in[mask].unsqueeze(1)
            deg_out = homo_out[mask].unsqueeze(1)

            # hashed label (we saved original nodes list, keep first label)
            lbl = torch.zeros((hg.num_nodes(ntype), K), dtype=torch.float32)
            for i, r in enumerate(by_type[ntype]):
                labs = r.get("labels") or []
                h = (hash(labs[0]) % K) if labs else 0
                lbl[i, h] = 1.0

            # optional node recency from props.updated_at (if present)
            if attach_recency:
                rec = torch.zeros((hg.num_nodes(ntype), 1), dtype=torch.float32)
                for i, r in enumerate(by_type[ntype]):
                    props = r.get("props") or {}
                    rut = props.get("updated_at")
                    try:
                        ts = float(rut) if isinstance(rut, (int, float)) else None
                    except Exception:
                        ts = None
                    age_s = max(0.0, (now - ts)) if ts else 0.0
                    rec[i, 0] = 0.5 ** (age_s / max(1e-6, decay_half_life_s))
                x = torch.cat([deg_in, deg_out, lbl, rec], dim=1)  # [N, 2+K+1]
            else:
                x = torch.cat([deg_in, deg_out, lbl], dim=1)       # [N, 2+K]

            x_dict[ntype] = x

        # 8) finalize edge weights as tensors
        ew_tensors = {
            et: torch.tensor(ws, dtype=torch.float32)
            for et, ws in edge_weight_dict.items()
        }

        return hg, idx_maps, x_dict, ew_tensors
