"""
seedcore/ml/driver/nim_retrieval_sdk.py
NIM Retrieval (embeddings) driver using the OpenAI SDK.
"""

from __future__ import annotations
import os
from typing import List, Optional, Union, Dict, Any
from types import SimpleNamespace

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - exercised in environments without openai
    OpenAI = None  # type: ignore[assignment]


class NimRetrievalSDK:
    """
    OpenAI SDK-based client for /v1/embeddings at NIM endpoints.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        model: str = "nvidia/nv-embedqa-e5-v5",
        timeout: int = 60,
    ):
        if OpenAI is None:
            self.client = SimpleNamespace()
        else:
            self.client = OpenAI(
                base_url=base_url.rstrip("/"),
                api_key=api_key or os.getenv("NIM_LLM_API_KEY", "none"),
                timeout=timeout,
            )
        self._ensure_embeddings_interface()
        self.model = model

    def _ensure_embeddings_interface(self) -> None:
        """Provide a patchable embeddings surface for minimal OpenAI stubs."""
        embeddings = getattr(self.client, "embeddings", None)
        create = getattr(embeddings, "create", None) if embeddings is not None else None
        if callable(create):
            return

        def _missing_create(*_args, **_kwargs):
            raise RuntimeError("OpenAI client does not expose embeddings.create")

        self.client.embeddings = SimpleNamespace(create=_missing_create)  # type: ignore[attr-defined]

    def embed(
        self,
        inputs: Union[str, List[str]],
        *,
        input_type: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> List[List[float]]:
        payload: Dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "input": inputs,
        }
        
        # For NIM servers, pass input_type through extra_body for OpenAI SDK compatibility
        if input_type:
            payload["extra_body"] = {**(extra_body or {}), "input_type": input_type}
        elif extra_body:
            payload["extra_body"] = extra_body

        res = self.client.embeddings.create(**payload)
        return [row.embedding for row in res.data]

    def embed_query(self, text: str, **kwargs) -> List[float]:
        return self.embed(text, input_type="query", **kwargs)[0]

    def embed_passage(self, text: str, **kwargs) -> List[float]:
        return self.embed(text, input_type="passage", **kwargs)[0]

    @staticmethod
    def cosine_sim(a: List[float], b: List[float]) -> float:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
