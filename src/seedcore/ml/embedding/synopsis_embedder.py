from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

import numpy as np

# Conditional imports for different backends
try:
    import google.generativeai as genai  # pyright: ignore[reportMissingImports]
except ImportError:
    genai = None

try:
    from seedcore.ml.driver.nim_retrieval import NimRetrievalHTTP
except Exception:
    NimRetrievalHTTP = None

try:
    from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]
except Exception:
    SentenceTransformer = None


class SynopsisEmbedder:
    """
    Core embedding utility for SeedCore.
    Priority: Gemini (Default) -> NIM -> Sentence-Transformers (Local)
    """

    def __init__(
        self,
        *,
        backend: Optional[str] = None,
        model: Optional[str] = None,
        dim: Optional[int] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: Optional[float] = None,
    ):
        # 1. Determine Backend
        self.backend = (
            (backend or os.getenv("SYNOPSIS_EMBEDDING_BACKEND") or "gemini")
            .lower()
            .replace("_", "-")
        )

        # 2. Configuration Defaults
        self.api_key = (
            api_key
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("SYNOPSIS_EMBEDDING_API_KEY")
        )
        self.model = model or os.getenv("SYNOPSIS_EMBEDDING_MODEL")
        self.dim = int(dim or os.getenv("SYNOPSIS_EMBEDDING_DIM", "768"))
        self.base_url = base_url or os.getenv("SYNOPSIS_EMBEDDING_BASE_URL")
        self.timeout_s = float(
            timeout_s or os.getenv("SYNOPSIS_EMBEDDING_TIMEOUT", "10")
        )

        # Default model assignment based on backend
        if not self.model:
            if self.backend == "gemini":
                self.model = "models/text-embedding-004"
            else:
                self.model = "sentence-transformers/all-mpnet-base-v2"

        self._embedder: Optional[Any] = None
        self._failed = False
        self._lock = threading.Lock()

    def _ensure(self) -> Optional[Any]:
        """Lazy initialization of the chosen backend."""
        if self._embedder or self._failed:
            return self._embedder

        with self._lock:
            if self._embedder:
                return self._embedder

            try:
                if self.backend == "gemini":
                    if genai is None or not self.api_key:
                        raise ValueError("Gemini dependencies or API key missing.")
                    genai.configure(api_key=self.api_key)
                    # We store the module or a dummy; Gemini calls are mostly functional
                    self._embedder = genai

                elif self.backend in {"nim", "nim-retrieval"}:
                    if NimRetrievalHTTP is None or not self.base_url:
                        raise ValueError("NIM dependencies or Base URL missing.")
                    self._embedder = NimRetrievalHTTP(
                        base_url=self.base_url,
                        api_key=self.api_key,
                        model=self.model,
                        timeout=int(self.timeout_s),
                    )

                else:  # fallback to sentence-transformers
                    if SentenceTransformer is None:
                        raise ValueError("SentenceTransformer not installed.")
                    self._embedder = SentenceTransformer(self.model)

            except Exception as e:
                print(f"SynopsisEmbedder failed to init {self.backend}: {e}")
                self._failed = True
                return None

        return self._embedder

    def embed_text(
        self, text: str, *, dim: Optional[int] = None, normalize: bool = True
    ) -> Optional[np.ndarray]:
        client = self._ensure()
        if client is None:
            return None

        target_dim = int(dim or self.dim)

        try:
            # --- GEMINI LOGIC ---
            if self.backend == "gemini":
                # text-embedding-004 supports 'output_dimensionality'
                result = client.embed_content(
                    model=self.model,
                    content=text,
                    task_type="retrieval_document",
                    output_dimensionality=target_dim,
                )
                vec = np.asarray(result["embedding"], dtype=np.float32)

            # --- NIM LOGIC ---
            elif isinstance(client, NimRetrievalHTTP):
                vectors = client.embed(text, input_type="passage")
                vec = np.asarray(vectors[0], dtype=np.float32).reshape(-1)

            # --- LOCAL ST LOGIC ---
            else:
                vec = client.encode(
                    text, convert_to_numpy=True, normalize_embeddings=True
                )
                vec = np.asarray(vec, dtype=np.float32).reshape(-1)

            # Post-processing
            vec = self._resize(vec, target_dim)
            if normalize:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm

            return vec.astype(np.float32)

        except Exception as e:
            print(f"Embedding error: {e}")
            return None

    def embed_synopsis(
        self, synopsis: Dict[str, Any], **kwargs
    ) -> Optional[np.ndarray]:
        """Converts structured living system data to JSON for embedding."""
        text = json.dumps(synopsis, sort_keys=True)
        return self.embed_text(text, **kwargs)

    @staticmethod
    def _resize(vec: np.ndarray, target_dim: int) -> np.ndarray:
        if vec.size == target_dim:
            return vec
        if vec.size > target_dim:
            return vec[:target_dim]
        return np.pad(vec, (0, target_dim - vec.size), mode="constant")
