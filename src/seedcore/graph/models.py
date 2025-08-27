from __future__ import annotations
import torch
import torch.nn as nn
import dgl
import dgl.nn as dglnn

class SAGE(nn.Module):
    def __init__(self, in_feats: int, h_feats: int = 128, layers: int = 2):
        super().__init__()
        self.convs = nn.ModuleList()
        self.convs.append(dglnn.SAGEConv(in_feats, h_feats, aggregator_type="mean"))
        for _ in range(layers - 1):
            self.convs.append(dglnn.SAGEConv(h_feats, h_feats, aggregator_type="mean"))
        self.act = nn.ReLU()

    def forward(self, g: dgl.DGLGraph, x: torch.Tensor) -> torch.Tensor:
        h = x
        for conv in self.convs:
            h = conv(g, h)
            h = self.act(h)
        return nn.functional.normalize(h, p=2, dim=1)  # nice unit vectors
