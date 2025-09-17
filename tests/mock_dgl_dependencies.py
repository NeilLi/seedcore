#!/usr/bin/env python3
"""
Mock DGL dependencies for tests.

Provides a lightweight stub for the `dgl` module and `dgl.nn` so imports
and simple model instantiation work without native libs.
"""

import sys
import types
import torch
import torch.nn as nn


class _MockDGLModule(types.ModuleType):
    __version__ = "0.0.0-mock"

    # Placeholders for type annotations used in source
    class DGLGraph:  # noqa: N801
        pass

    class DGLHeteroGraph:  # noqa: N801
        pass

    # Constant used in code for ndata indexing
    NTYPE = "_NTYPE"


mock_dgl = _MockDGLModule("dgl")


# dgl.nn submodule with minimal layers used by our code
class _MockDGLNN(types.ModuleType):
    def __init__(self):
        super().__init__("dgl.nn")

        class SAGEConv(nn.Module):
            def __init__(self, in_feats: int, out_feats: int, aggregator_type: str = "mean"):
                super().__init__()
                self.linear = nn.Linear(in_feats, out_feats)

            def forward(self, g, x, edge_weight=None):  # g ignored
                return self.linear(x)

        class HeteroGraphConv(nn.Module):
            def __init__(self, mods=None, aggregate: str = "sum"):
                super().__init__()
                # match attribute accessed in code
                self.mods = nn.ModuleDict(mods or {})
                self.aggregate = aggregate

            def forward(self, g, x_dict, mod_kwargs=None):  # passthrough
                return x_dict

        self.SAGEConv = SAGEConv
        self.HeteroGraphConv = HeteroGraphConv


mock_dglnn = _MockDGLNN()

# Register modules
sys.modules["dgl"] = mock_dgl
sys.modules["dgl.nn"] = mock_dglnn

print("✅ Mock DGL dependencies loaded successfully")


