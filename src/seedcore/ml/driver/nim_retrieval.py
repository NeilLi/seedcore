"""
seedcore/ml/driver/nim_retrieval.py
Low-level NIM Retrieval (embeddings) driver using direct HTTP calls.

Supports NVIDIA NIM embeddings like: nvidia/nv-embedqa-e5-v5
"""

from __future__ import annotations
import hashlib
import os
import httpx
from typing import List, Optional, Union, Dict, Any


def _env_truthy(name: str) -> bool:
    value = os.getenv(name)
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _mock_vector(text: str, dim: int = 768) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    needed = max(1, dim * 4)
    repeated = (digest * ((needed // len(digest)) + 1))[:needed]
    values: List[float] = []
    for index in range(0, needed, 4):
        chunk = int.from_bytes(repeated[index:index + 4], byteorder="big", signed=False)
        values.append((chunk % 1_000_000) / 500_000.0 - 1.0)
    return values[:dim]


class NimRetrievalHTTP:
    """
    Minimal HTTP client for OpenAI-compatible /v1/embeddings endpoints.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        model: str = "nvidia/nv-embedqa-e5-v5",
        timeout: int = 60,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("NIM_LLM_API_KEY", "none")
        self.model = model
        self.mock_mode = (
            _env_truthy("SEEDCORE_MOCK_EXTERNAL_APIS")
            or _env_truthy("NIM_RETRIEVAL_MOCK")
        )
        self.session = httpx.Client(timeout=timeout)
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            **(headers or {}),
        }

    # ---------- core ----------
    def embed(
        self,
        inputs: Union[str, List[str]],
        *,
        input_type: Optional[str] = None,  # "query" or "passage" for asymmetric models
        extra_body: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> List[List[float]]:
        """
        Create embeddings for a single string or a list of strings.

        Returns a list of vectors (one per input). If a single string was passed, still returns [vector].
        """
        if self.mock_mode:
            entries = inputs if isinstance(inputs, list) else [inputs]
            return [_mock_vector(str(entry)) for entry in entries]

        payload: Dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "input": inputs,
        }

        # For NIM servers, use top-level input_type parameter (not extra_body)
        if input_type:
            payload["input_type"] = input_type
        elif extra_body:
            # Only add extra_body if no input_type is specified
            payload["extra_body"] = extra_body

        url = f"{self.base_url}/embeddings"
        resp = self.session.post(url, headers=self.headers, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"NIM retrieval request failed: {resp.status_code} {resp.text}")

        data = resp.json()
        if "data" not in data:
            raise ValueError(f"Unexpected embeddings response: {data}")

        return [row["embedding"] for row in data["data"]]

    # ---------- helpers ----------
    def embed_query(self, text: str, **kwargs) -> List[float]:
        """Convenience for asymmetric models (input_type='query')."""
        return self.embed(text, input_type="query", **kwargs)[0]

    def embed_passage(self, text: str, **kwargs) -> List[float]:
        """Convenience for asymmetric models (input_type='passage')."""
        return self.embed(text, input_type="passage", **kwargs)[0]

    @staticmethod
    def cosine_sim(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity without requiring numpy."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
