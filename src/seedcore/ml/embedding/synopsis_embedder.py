from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

import numpy as np

try:
    from seedcore.ml.driver.nim_retrieval import NimRetrievalHTTP  # adjust import
except Exception:  # pragma: no cover
    NimRetrievalHTTP = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover
    SentenceTransformer = None  # type: ignore


class SynopsisEmbedder:
    """
    Small, dependency-light embedding utility.

    - Backend: nim | sentence-transformer
    - Input: dict (synopsis) or str
    - Output: np.ndarray float32 (dim-adjusted, normalized)
    """

    def __init__(
        self,
        *,
        backend: Optional[str] = None,
        model: Optional[str] = None,
        dim: Optional[int] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: Optional[float] = None,
    ):
        self.backend = (
            (backend or os.getenv("SYNOPSIS_EMBEDDING_BACKEND") or "")
            .lower()
            .replace("_", "-")
        )
        if not self.backend:
            self.backend = (
                "nim"
                if (
                    os.getenv("SYNOPSIS_EMBEDDING_BASE_URL")
                    or os.getenv("NIM_RETRIEVAL_BASE_URL")
                )
                else "sentence-transformer"
            )

        self.model = model or os.getenv(
            "SYNOPSIS_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2"
        )
        self.dim = int(dim or os.getenv("SYNOPSIS_EMBEDDING_DIM", "768"))

        self.base_url = (
            base_url
            or os.getenv("SYNOPSIS_EMBEDDING_BASE_URL")
            or os.getenv("NIM_RETRIEVAL_BASE_URL", "")
        ).lstrip("@")
        self.api_key = (
            api_key
            or os.getenv("SYNOPSIS_EMBEDDING_API_KEY")
            or os.getenv("NIM_RETRIEVAL_API_KEY")
        )
        self.timeout_s = float(
            timeout_s or os.getenv("SYNOPSIS_EMBEDDING_TIMEOUT", "10")
        )

        self._embedder: Optional[Any] = None
        self._failed = False
        self._lock = threading.Lock()

    def _ensure(self) -> Optional[Any]:
        if self._embedder or self._failed:
            return self._embedder

        with self._lock:
            if self._embedder or self._failed:
                return self._embedder

            if self.backend in {"nim", "nim-retrieval"}:
                if NimRetrievalHTTP is None or not self.base_url:
                    self._failed = True
                    return None
                try:
                    self._embedder = NimRetrievalHTTP(
                        base_url=self.base_url,
                        api_key=self.api_key,
                        model=self.model,
                        timeout=int(self.timeout_s),
                    )
                except Exception:
                    self._failed = True
                    return None
            else:
                if SentenceTransformer is None:
                    self._failed = True
                    return None
                try:
                    self._embedder = SentenceTransformer(self.model)
                except Exception:
                    self._failed = True
                    return None

        return self._embedder

    def embed_text(
        self, text: str, *, dim: Optional[int] = None, normalize: bool = True
    ) -> Optional[np.ndarray]:
        emb = self._ensure()
        if emb is None:
            return None

        try:
            if NimRetrievalHTTP is not None and isinstance(emb, NimRetrievalHTTP):
                vectors = emb.embed(text, input_type="passage")
                if not vectors:
                    return None
                vec = np.asarray(vectors[0], dtype=np.float32).reshape(-1)
            else:
                vec = emb.encode(text, convert_to_numpy=True, normalize_embeddings=True)  # type: ignore[attr-defined]
                vec = np.asarray(vec, dtype=np.float32).reshape(-1)
        except Exception:
            return None

        target = int(dim or self.dim)
        vec = self._resize(vec, target)

        if normalize:
            n = float(np.linalg.norm(vec))
            if n > 0:
                vec = vec / n

        return vec.astype(np.float32)

    def embed_synopsis(
        self,
        synopsis: Dict[str, Any],
        *,
        dim: Optional[int] = None,
        normalize: bool = True,
    ) -> Optional[np.ndarray]:
        text = json.dumps(synopsis, sort_keys=True)
        return self.embed_text(text, dim=dim, normalize=normalize)

    @staticmethod
    def _resize(vec: np.ndarray, target_dim: int) -> np.ndarray:
        if vec.size == target_dim:
            return vec
        if vec.size > target_dim:
            return vec[:target_dim]
        return np.pad(vec, (0, target_dim - vec.size), mode="constant")
