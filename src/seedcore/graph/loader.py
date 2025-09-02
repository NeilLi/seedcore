from __future__ import annotations
import os
from typing import Dict, List, Tuple, Any
from neo4j import GraphDatabase
import dgl
import torch

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

class GraphLoader:
    """
    Simple k-hop neighborhood loader from Neo4j -> DGL graph (homogeneous).
    Node ids are Neo4j internal ids (or your own id property if you prefer).
    """

    def __init__(self, uri: str = NEO4J_URI, user: str = NEO4J_USER, password: str = NEO4J_PASSWORD):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def load_k_hop(
        self,
        start_ids: List[int],     # list of Neo4j internal ids (id(n))
        k: int = 2,
        limit_nodes: int = 5000,
        limit_rels: int = 20000,
    ) -> Tuple[dgl.DGLGraph, Dict[int, int], torch.Tensor]:
        """
        Returns:
          g: DGLGraph (homogeneous)
          idx_map: {neo4j_id -> graph_index}
          X: torch.FloatTensor [N, F]  (simple features)
        """
        with self.driver.session() as s:
            # Gather nodes within k hops
            q_nodes = f"""
            MATCH (s)
            WHERE id(s) IN $start_ids
            MATCH p=(s)-[*..{k}]-(m)
            WITH COLLECT(DISTINCT m) + COLLECT(DISTINCT s) AS ns
            UNWIND ns AS n
            WITH DISTINCT n LIMIT $limit_nodes
            RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props
            """
            nodes = s.run(q_nodes, start_ids=start_ids, limit_nodes=limit_nodes).data()

            if not nodes:
                # fallback to ensure we still include the start nodes
                nodes = s.run(
                    "MATCH (n) WHERE id(n) IN $start_ids RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props",
                    start_ids=start_ids
                ).data()

            neo_ids = [r["id"] for r in nodes]
            idx_map = {nid: i for i, nid in enumerate(neo_ids)}

            # Gather relations among these nodes
            q_edges = """
            MATCH (u)-[r]->(v)
            WHERE id(u) IN $ids AND id(v) IN $ids
            RETURN id(u) AS src, id(v) AS dst
            LIMIT $limit_rels
            """
            edges = s.run(q_edges, ids=neo_ids, limit_rels=limit_rels).data()

        if not neo_ids:
            # empty graph
            g = dgl.graph(([], []), num_nodes=0)
            return g, {}, torch.empty(0, 0)

        src = [idx_map[e["src"]] for e in edges]
        dst = [idx_map[e["dst"]] for e in edges]
        g = dgl.graph((src, dst), num_nodes=len(neo_ids))

        # === Cheap, deterministic features ===
        # Feature: [deg_in, deg_out, one-hot(labels up to K=8 compressed to 8 bins)]
        deg_in = g.in_degrees().float().unsqueeze(1)
        deg_out = g.out_degrees().float().unsqueeze(1)

        # Build a tiny hashed label feature of length 8
        K = 8
        lbl_feats = torch.zeros((g.num_nodes(), K), dtype=torch.float32)
        # We don't have labels anymore here; rebuild from nodes structure:
        # pass labels list in order:
        label_list = []
        for r in nodes:
            labs = r.get("labels") or []
            # hash the first label
            if labs:
                h = (hash(labs[0]) % K)
                label_list.append(h)
            else:
                label_list.append(0)
        for i, h in enumerate(label_list):
            lbl_feats[i, h] = 1.0

        X = torch.cat([deg_in, deg_out, lbl_feats], dim=1)  # shape: [N, 10]
        return g, idx_map, X
